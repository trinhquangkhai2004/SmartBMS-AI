"""End-of-charge indicators for an RT-Batt cell, in canonical units."""
import numpy as np


FAST = "Constant current charge"
TOP = "Constant current-constant voltage charge"
BANDS = ((3.45, 3.55), (3.50, 3.58), (3.45, 3.60))
BAND_NAMES = ("delta_q_345_355_ah", "delta_q_350_358_ah", "delta_q_345_360_ah")
STAGE_NAMES = ("q_cc_fast_ah", "q_cc_topup_ah", "q_cc_ah", "q_cv_ah",
               "q_cv_over_q_cc", "q_cv_fraction_total", "cv_duration_s")
FEATURE_NAMES = BAND_NAMES + STAGE_NAMES + ("charge_duration_s", "start_charge_voltage_v")
EPS_AH = 1e-8


def integrate(t, i):
    """Positive charging-current magnitude in A, measured intervals only."""
    return float(np.sum(np.diff(t) * (i[1:] + i[:-1]) * 0.5) / 3600)


def band_capacity(t, v, i, low, high, max_gap):
    """Integrate linearly interpolated current over in-band fractions of intervals."""
    if v[0] > low or np.max(v) < high:
        return None, "PARTIAL_WINDOW"
    start, finish = v[:-1], v[1:]
    dv = finish - start
    flat = dv == 0
    slope = np.where(flat, 1.0, dv)
    left, right = (low - start) / slope, (high - start) / slope
    a = np.clip(np.minimum(left, right), 0, 1)
    b = np.clip(np.maximum(left, right), 0, 1)
    a[flat] = 0
    b[flat] = ((start[flat] >= low) & (start[flat] <= high))
    dt = np.diff(t)
    if np.any((dt > max_gap) & (b > a)):
        return None, "WINDOW_GAP"
    di = np.diff(i)
    ah = np.sum(dt * (b-a) * (i[:-1] + 0.5*(a+b)*di)) / 3600
    return (float(ah), None) if ah > 0 else (None, "EMPTY_WINDOW")


def extract_charge(time_s, voltage_v, current_a, status):
    """Called at charge end. Input charge current is negative in the F2/F3 contract."""
    t, v, amps = [np.asarray(x, dtype=float) for x in (time_s, voltage_v, current_a)]
    st = np.asarray(status)
    out = dict.fromkeys(FEATURE_NAMES)
    reasons = {}
    def missing(names, reason):
        reasons.update({name: reason for name in names if out[name] is None})
    if not (t.ndim == 1 and t.shape == v.shape == amps.shape == st.shape):
        raise ValueError("Charge arrays must have the same one-dimensional shape")
    if (len(t) < 2 or not np.isfinite(t).all() or not np.isfinite(v).all()
            or not np.isfinite(amps).all() or np.any(np.diff(t) <= 0)
            or np.any(amps >= 0) or not np.isin(st, [FAST, TOP]).all()):
        missing(FEATURE_NAMES, "INVALID_CHARGE")
        return out, reasons
    i = -amps
    out.update(charge_duration_s=float(t[-1]-t[0]), start_charge_voltage_v=float(v[0]))
    split = int(np.count_nonzero(st == FAST))
    if split < 2 or len(t)-split < 4 or not np.all(st[:split] == FAST) or not np.all(st[split:] == TOP):
        missing(BAND_NAMES + STAGE_NAMES, "UNRESOLVED_STAGE_ORDER")
        return out, reasons
    max_gap = max(30., 5.*float(np.median(np.diff(t))))
    ft, fi = t[:split], i[:split]
    tt, tv, ti = t[split:], v[split:], i[split:]
    for name, (lo, hi) in zip(BAND_NAMES, BANDS):
        out[name], reason = band_capacity(tt, tv, ti, lo, hi, max_gap)
        if reason:
            reasons[name] = reason
    if np.max(np.diff(ft)) <= max_gap and np.all(np.abs(fi - 5.5) <= 0.165):
        out["q_cc_fast_ah"] = integrate(ft, fi)
    if np.max(np.diff(tt)) > max_gap:
        missing(STAGE_NAMES, "STAGE_GAP")
        return out, reasons
    crossings = np.flatnonzero((np.abs(tv - 3.6) <= 0.005) & (ti <= 0.98 * 1.1))
    if len(crossings):
        k = int(crossings[0])
        if (k >= 2 and len(ti)-k >= 3 and np.all(np.abs(ti[:k]-1.1) <= 0.055)
                and np.all(np.abs(tv[k:]-3.6) <= 0.005)
                and ti[-1] <= 0.5*ti[k] and np.mean(np.diff(ti[k:]) <= 0.01) >= 0.9):
            out["q_cc_topup_ah"] = integrate(tt[:k], ti[:k])
            out["q_cv_ah"] = integrate(tt[k:], ti[k:])
            out["cv_duration_s"] = float(tt[-1]-tt[k])
            if out["q_cc_fast_ah"] is not None:
                cc = out["q_cc_fast_ah"] + out["q_cc_topup_ah"]
                cv = out["q_cv_ah"]
                out["q_cc_ah"] = cc
                if cc > EPS_AH:
                    out["q_cv_over_q_cc"] = cv/cc
                if cc+cv > EPS_AH:
                    out["q_cv_fraction_total"] = cv/(cc+cv)
    missing(STAGE_NAMES, "UNCONFIRMED_STAGE_OR_DENOMINATOR")
    return out, reasons
