"""Streaming fixed 1-RC EKF for offline, single-cell research.

Time is in seconds, discharge current in A, SoC in fractions, and voltage in V.
All priors and tuning values are explicit. Reference labels have no runtime input.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


WARNING_THRESHOLD_V = 3.2976
WARNING_POLICY_VERSION = "g10-conditional-v1.2"
P22_OCV_SHA256 = "ca9872be1836d000b8ec6b2f970c371064a54dad59efa8d2ea8c084a2111107b"
P22_CAPACITY_SHA256 = "bcd2f28b57d9b21ed43f99561d6b8dfc263aaf2ba38c2e60759584f27479e8e0"


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _read_pinned_document(path, pin):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != pin:
        raise ValueError(f"SHA-256 mismatch for {Path(path).name}")
    return json.loads(raw)


def load_frozen_calibration(ocv_path, capacity_path):
    """Read the exact two artifacts pinned by the verified P2.2 manifest."""
    ocv = _read_pinned_document(ocv_path, P22_OCV_SHA256)
    capacity = _read_pinned_document(capacity_path, P22_CAPACITY_SHA256)
    if (ocv["schema_version"] != "p2.2.1" or ocv["status"] != "VALID"
            or ocv["source_cell_id"] != "SP20-3" or ocv["target_cell_id"] != "SP20-2"
            or ocv["selected_branch"] != "discharge" or ocv["interpolator"] != "PCHIP"
            or ocv["transfer_assumption"] is not True or ocv["extrapolate"] is not False
            or ocv["units"] != {"z":"fraction", "ocv":"V", "docv_dz":"V/fraction"}):
        raise ValueError("Unsupported OCV schema, units or transfer provenance")
    if (capacity["schema_version"] != "p2.2.1" or capacity["status"] != "VALID"
            or capacity["source_cell_id"] != "SP20-2"
            or capacity["current_convention"] != "discharge positive; raw counter semantics unchanged; Ah"
            or not finite(capacity["capacity_model_ah"]) or capacity["capacity_model_ah"] <= 0):
        raise ValueError("Unsupported model capacity schema, units or provenance")
    curve = OCV(ocv["z_knots"], ocv["ocv_v_knots"])
    if (curve.z_min, curve.z_max) != (ocv["z_min"], ocv["z_max"]):
        raise ValueError("OCV knots disagree with the declared interpolation domain")
    return curve, capacity["capacity_model_ah"]


def load_research_ecm(path, *, approval, policy, profile, audit_log, research_opt_in=False):
    """Authorize the unchanged original ECM for P2.5 development only.

    Returns the source document with the original schema. A replay adapter
    must extract coefficients/units from the verified document. The user's
    approval record and associated policy must independently pin its bytes.
    No released/production loader is overridden.
    """
    path, audit_log = Path(path), Path(audit_log)
    if path.resolve() == audit_log.resolve():
        raise ValueError("Candidate and audit log must be distinct files")
    event = dict(timestamp_utc=datetime.now(timezone.utc).isoformat(), milestone="P2.5",
                 profile=profile, research_opt_in=research_opt_in, scientific_release=False,
                 approval_record_id=approval.get("approval_record_id"), decision="DENY",
                 candidate_file=path.name, expected_ecm_sha256=approval.get("ecm_sha256"),
                 actual_ecm_sha256=None)
    try:
        if research_opt_in is not True or profile not in ("DST", "FUDS"):
            raise PermissionError("Only explicit P2.5 offline research on DST/FUDS is authorized")
        if (approval.get("decision") != "APPROVED_CONDITIONAL"
                or approval.get("conditional_execution_allowed") is not True
                or approval.get("scientific_release") is not False
                or not isinstance(approval.get("scope"), (list, tuple)) or "P2.5" not in approval["scope"]
                or not approval.get("approval_source") or not event["approval_record_id"]):
            raise PermissionError("Missing approval evidence or P2.5 research scope")
        pin = approval.get("ecm_sha256")
        if not isinstance(pin, str) or not re.fullmatch("[a-f0-9]{64}", pin):
            raise PermissionError("Approval does not identify original ECM bytes")
        if (policy.get("ecm_sha256") != pin or policy.get("scientific_release") is not False
                or policy.get("approval_record_id") != event["approval_record_id"]
                or policy.get("warning_threshold_v") != WARNING_THRESHOLD_V):
            raise PermissionError("Research policy does not match approval, release hold or warning threshold")
        raw = path.read_bytes()
        event["actual_ecm_sha256"] = hashlib.sha256(raw).hexdigest()
        if event["actual_ecm_sha256"] != pin:
            raise ValueError("ECM candidate differs from the pinned original")
        doc = json.loads(raw)
        if (not isinstance(doc, dict) or doc.get("lock_status") != "NEEDS_REVIEW_NOT_RELEASED"
                or doc.get("scientific_release", False) is not False):
            raise ValueError("Expected the original unreleased ECM lock")
        event.update(decision="ALLOW", reason="Pinned candidate under conditional research approval")
        return doc
    except (ValueError, OSError, TypeError) as exc:
        event["reason"] = str(exc)
        raise
    finally:
        audit_log.parent.mkdir(parents=True, exist_ok=True)
        with audit_log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, allow_nan=False)+"\n")


@dataclass(frozen=True)
class FixedRC:
    r0_ohm: float
    r1_ohm: float
    c1_f: float
    capacity_ah: float

    def __post_init__(self):
        if not all(finite(x) and x > 0 for x in vars(self).values()):
            raise ValueError("R0, R1, C1 and model capacity must be positive and finite")
        if not finite(self.r1_ohm * self.c1_f) or self.r1_ohm*self.c1_f == 0:
            raise ValueError("Invalid RC time constant")


class OCV:
    """Monotone piecewise cubic Hermite interpolation, no extrapolation.

    Interior slopes use the weighted harmonic mean. End slopes are one-sided
    three-point estimates with the PCHIP shape-preserving limit.
    """
    def __init__(self, z_knots, ocv_v_knots):
        self.z = tuple(z_knots)
        v = tuple(ocv_v_knots)
        if len(v) != len(self.z) or len(v) < 2 or not all(map(finite, (*self.z, *v))):
            raise ValueError("Expected two or more paired finite OCV knots")
        self.z_min, self.z_max = self.z[0], self.z[-1]
        if not 0 <= self.z_min < self.z_max <= 1:
            raise ValueError("OCV endpoints must lie within physical SoC bounds")
        h = [b-a for a,b in zip(self.z, self.z[1:])]
        if min(h) <= 0 or any(b < a for a,b in zip(v, v[1:])):
            raise ValueError("Expected strictly increasing SoC and nondecreasing OCV")
        slopes = [(b-a)/width for a,b,width in zip(v, v[1:], h)]
        if len(h) == 1:
            derivatives = [slopes[0], slopes[0]]
        else:
            def end_slope(h0, h1, m0, m1):
                result = ((2*h0+h1)*m0-h0*m1)/(h0+h1)
                return max(0.0, min(3*m0, result))

            derivatives = [end_slope(h[0], h[1], slopes[0], slopes[1])]
            for j in range(1, len(h)):
                left, right = slopes[j-1], slopes[j]
                w1, w2 = 2*h[j]+h[j-1], h[j]+2*h[j-1]
                derivatives.append((w1+w2)/(w1/left+w2/right) if left and right else 0.)
            derivatives.append(end_slope(h[-1], h[-2], slopes[-1], slopes[-2]))
        self.coeffs = []
        for k, width in enumerate(h):
            slope, left, right = slopes[k], derivatives[k], derivatives[k+1]
            self.coeffs.append((v[k], left, (3*slope-2*left-right)/width,
                                (left+right-2*slope)/(width*width)))

    def evaluate(self, z):
        if not finite(z) or not self.z_min <= z <= self.z_max:
            raise ValueError("OCV lookup outside calibrated SoC domain")
        k = min(len(self.coeffs)-1, bisect.bisect_right(self.z, z)-1)
        dx = z - self.z[k]
        c0, c1, c2, c3 = self.coeffs[k]
        return c0+dx*(c1+dx*(c2+dx*c3)), c1+dx*(2*c2+dx*3*c3)


def _covariance_ok(zz, zv, vv):
    # The correlation-form bound avoids overflow in a determinant of large P.
    return (all(map(finite, (zz, zv, vv))) and min(zz, vv) >= 0 and
            abs(zv) <= math.sqrt(zz)*math.sqrt(vv)*(1+1e-12))


def _joseph(zz, zv, vv, kz, kv, hz, r):
    # H=(hz,-1); J=I-KH. Store the three distinct entries of symmetric P.
    a, b, c, d = 1-kz*hz, kz, -kv*hz, 1+kv
    az, av = a*zz+b*zv, a*zv+b*vv
    cz, cv = c*zz+d*zv, c*zv+d*vv
    return (az*a+av*b+r*kz*kz, az*c+av*d+r*kz*kv, cz*c+cv*d+r*kv*kv)


class EKF:
    """One instance per run. Q(dt)=diag(q_per_s_diag)*dt, R in V².

    reset() sets a sourced prior; the first observation corrects at zero elapsed
    time. A long interval needs independent evidence from the adapter.
    Prediction-only states are reported separately from a valid SoC output.
    """
    def __init__(self, model, ocv, *, p0_diag, q_per_s_diag, r_v2,
                 max_gap_active_s, model_version, approval_record_id, current_range_a=None):
        self.model, self.ocv = model, ocv
        self.p0_diag, self.q_per_s_diag = tuple(p0_diag), tuple(q_per_s_diag)
        if (len(self.p0_diag) != 2 or len(self.q_per_s_diag) != 2
                or not all(finite(n) and n >= 0 for n in (*self.p0_diag, *self.q_per_s_diag))):
            raise ValueError("P0 and Q per second require two finite nonnegative variances")
        if not all(finite(n) and n > 0 for n in (r_v2, max_gap_active_s)):
            raise ValueError("Positive finite R and active-gap threshold required")
        if not model_version or not approval_record_id:
            raise ValueError("Model version and approval record ID required")
        if current_range_a is not None:
            if (len(current_range_a) != 2 or not all(map(finite, current_range_a))
                    or current_range_a[0] >= current_range_a[1]):
                raise ValueError("Invalid calibrated current bounds")
        self.current_range_a = current_range_a
        self.r, self.max_gap_active_s = r_v2, max_gap_active_s
        self.model_version, self.approval_record_id = model_version, approval_record_id
        self.run_id = None
        self.ready = False

    def reset(self, z, vrc=0., *, run_id, first_voltage_used_for_prior=False):
        if not finite(z) or not 0 <= z <= 1 or not finite(vrc) or not run_id:
            raise ValueError("Finite stated SoC/vRC prior and run ID required")
        self.run_id, self.ready = run_id, True
        self.z, self.vrc = z, vrc
        self.p = (self.p0_diag[0], 0., self.p0_diag[1])
        self.last_t = self.last_i = self.last_v = self.last_step = None
        self.transition_corrected = False
        self.boundary_count = 0
        self.last_status = "NOT_READY"
        self.first_voltage_used_for_prior = bool(first_voltage_used_for_prior)

    def _initial_row(self, t, v):
        flag = v < WARNING_THRESHOLD_V if finite(v) else None
        initialized = self.run_id is not None
        p = self.p if initialized else (None, None, None)
        return dict(run_id=self.run_id, timestamp_s=t if finite(t) else None,
                    voltage_v=v if finite(v) else None, status="NOT_READY",
                    reason="A sourced prior is required", model_version=self.model_version,
                    approval_record_id=self.approval_record_id, warning_policy_version=WARNING_POLICY_VERSION,
                    LOW_SOC_MODEL_UNCERTAIN=flag, warning_flag=flag,
                    low_soc_voltage_threshold_v=WARNING_THRESHOLD_V, soc_pct=None,
                    soc_state_fraction=None, vrc_v=None, voltage_pred_v=None,
                    innovation_v=None, z_pred=None, z_unconstrained=None, dt_s=None,
                    boundary_projected=False, boundary_overshoot=None,
                    boundary_count=self.boundary_count if initialized else 0, corrected=False,
                    p_zz=p[0], p_zv=p[1], p_vv=p[2], f_vrc=None, h_z=None,
                    h_vrc=None, innovation_variance_v2=None, k_z=None, k_vrc=None)

    def update(self, t, i_discharge, v, *, step=None, clock_event=None, interval="unverified", temperature_c=25.):
        """Process one observation, using I_prev over (t_prev,t], I_now for R0.

        For a verified rest, prior current must also be within 5 mA of zero
        (P2.2 rest classification). The endpoint can be a new load transition.
        A missing V can retain current history. Missing I, an unobserved long
        gap, or a failed numerical check requires a fresh external prior.
        """
        row = self._initial_row(t, v)
        if not self.ready:
            return row
        if not finite(t) or (self.last_t is not None and t < self.last_t):
            row.update(status="INVALID_INPUT", reason="Invalid or decreasing timestamp")
            return row
        if not finite(i_discharge):
            self.ready = False
            row.update(status="INVALID_INPUT", reason="Missing current; new prior required")
            return row
        if interval not in ("unverified", "verified_rest", "verified_constant_current"):
            raise ValueError("Unrecognized interval evidence")
        first = self.last_t is None
        dt = 0. if first else t-self.last_t
        row["dt_s"] = dt
        if (dt > self.max_gap_active_s and
                (interval == "unverified" or (interval == "verified_rest" and abs(self.last_i) > .005))):
            self.ready = False
            row.update(status="GAP_UNOBSERVED", reason="Long interval without consistent evidence; new prior required")
            return row
        if not first and dt == 0:
            changed = self.last_i != i_discharge or self.last_v != v
            transition = (clock_event == "ZERO_DT_NEW_TRANSITION" or
                          (step is not None and self.last_step is not None and step != self.last_step))
            if not (transition and changed and not self.transition_corrected):
                status = self.last_status
                if not finite(v) or not finite(temperature_c):
                    status = "INVALID_INPUT"
                elif (temperature_c != 25. or (self.current_range_a is not None and
                      not self.current_range_a[0] <= i_discharge <= self.current_range_a[1])):
                    status = "OUT_OF_DOMAIN"
                # I_now remains the left-end current for the following interval,
                # even when the repeated timestamp contributes no voltage update.
                self.last_i, self.last_v, self.last_step = i_discharge, v, step
                row.update(status=status, reason="Same-time observation preserved without a second correction",
                           soc_pct=100*self.z if status == "VALID" else None, soc_state_fraction=self.z,
                           vrc_v=self.vrc)
                return row
        if dt > 0 or first:
            self.transition_corrected = False
        prev_i = 0. if first or (interval == "verified_rest" and abs(self.last_i) <= .005) else self.last_i
        tau = self.model.r1_ohm * self.model.c1_f
        a = math.exp(-dt/tau)
        z = self.z - prev_i*dt/(3600*self.model.capacity_ah)
        vrc = a*self.vrc - self.model.r1_ohm*math.expm1(-dt/tau)*prev_i
        pz, pzv, pv = self.p
        p = (pz+self.q_per_s_diag[0]*dt, a*pzv, a*a*pv+self.q_per_s_diag[1]*dt)
        row.update(z_pred=z, f_vrc=a)
        if not all(map(finite, (z,vrc))) or not _covariance_ok(*p):
            return self._numerical_error(row)
        in_domain = (self.ocv.z_min <= z <= self.ocv.z_max and temperature_c == 25.
                     and (self.current_range_a is None or self.current_range_a[0] <= i_discharge <= self.current_range_a[1]))
        if not finite(v) or not finite(temperature_c):
            status, reason = "INVALID_INPUT", "Voltage or temperature missing; prediction only"
        elif not in_domain:
            status, reason = "OUT_OF_DOMAIN", "Outside calibrated SoC, temperature or current domain; prediction only"
        elif first and self.first_voltage_used_for_prior:
            status, reason = "VALID", "First voltage used in polarization prior; no independent correction"
        else:
            ocv, hz = self.ocv.evaluate(z)
            predicted = ocv-vrc-self.model.r0_ohm*i_discharge
            residual = v-predicted
            zz,zv,vv = p
            cov_z, cov_v = zz*hz-zv, zv*hz-vv
            s = hz*cov_z-cov_v+self.r
            if not all(map(finite, (predicted, residual, hz, s))) or s <= 0:
                return self._numerical_error(row)
            kz, kv = cov_z/s, cov_v/s
            z, vrc = z+kz*residual, vrc+kv*residual
            p = _joseph(zz, zv, vv, kz, kv, hz, self.r)
            if not all(map(finite, (z,vrc))) or not _covariance_ok(*p):
                return self._numerical_error(row)
            row.update(voltage_pred_v=predicted, innovation_v=residual, h_z=hz, h_vrc=-1.,
                       innovation_variance_v2=s, k_z=kz, k_vrc=kv, corrected=True)
            if not first and dt == 0:
                self.transition_corrected = True
            status, reason = "VALID", "Voltage correction"
        projected = min(1., max(0., z))
        self.boundary_count += int(projected != z)
        self.z, self.vrc, self.p = projected, vrc, p
        self.last_t, self.last_i, self.last_v, self.last_step = t, i_discharge, v, step
        self.last_status = status
        row.update(status=status, reason=reason, z_unconstrained=z, boundary_overshoot=abs(z-projected),
                   boundary_projected=z != projected, boundary_count=self.boundary_count,
                   soc_state_fraction=projected, vrc_v=vrc, soc_pct=100*projected if status == "VALID" else None,
                   p_zz=p[0], p_zv=p[1], p_vv=p[2])
        return row

    def _numerical_error(self, row):
        self.ready = False
        row.update(status="NUMERICAL_ERROR", reason="Nonfinite state/innovation or invalid covariance; new prior required")
        return row
