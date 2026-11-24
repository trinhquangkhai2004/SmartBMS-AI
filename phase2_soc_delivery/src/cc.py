"""Discharge-positive Coulomb Counting, and separate evaluation-only diagnostics."""
import numpy as np


def coulomb_count(time_s, current_a, capacity_ah, prior_soc):
    """Integrate left-endpoint current over an already clock-audited window."""
    time = np.asarray(time_s, dtype=float)
    current = np.asarray(current_a, dtype=float)
    if time.ndim != 1 or time.size == 0 or current.shape != time.shape:
        raise ValueError("A nonempty aligned time/current series is required")
    if not np.isfinite(time).all() or not np.isfinite(current).all():
        raise ValueError("Current or clock is unavailable")
    if not np.isfinite(capacity_ah) or capacity_ah <= 0 or not 0 <= prior_soc <= 1:
        raise ValueError("Invalid model capacity or initial SoC fraction")
    dt = np.diff(time)
    if np.any(dt < 0):
        raise ValueError("Clock reversal")
    with np.errstate(over='raise', invalid='raise'):
        discharged_ah = np.cumsum(current[:-1] * dt / 3600)
        return np.r_[prior_soc, prior_soc - discharged_ah / capacity_ah]


def score_populations(estimated, reference, voltage_v):
    """Score raw observations in each frozen population, with explicit coverage."""
    z, ref, voltage = [np.asarray(v, dtype=float) for v in (estimated, reference, voltage_v)]
    if z.ndim != 1 or z.shape != ref.shape or z.shape != voltage.shape:
        raise ValueError("Trajectory, reference and measured voltage must align")
    finite_voltage = np.isfinite(voltage)
    flagged = finite_voltage & (voltage < 3.2976)
    valid = np.isfinite(z) & np.isfinite(ref)
    result = dict(flagged_count=int(flagged.sum()), missing_voltage_count=int((~finite_voltage).sum()),
                  flagged_fraction=float(flagged.mean()) if flagged.size else None)
    for name, mask in (('FULL_DYNAMIC', np.ones(z.shape, dtype=bool)),
                       ('NON_FLAGGED', finite_voltage & ~flagged), ('FLAGGED', flagged)):
        scored = mask & valid
        errors = np.abs(100 * (z[scored] - ref[scored]))
        result[name] = dict(numerator=int(scored.sum()), denominator=int(mask.sum()),
                            missing_count=int((mask & ~valid).sum()),
                            MAE_pp=float(errors.mean()) if errors.size else None,
                            RMSE_pp=float(np.sqrt(np.mean(errors**2))) if errors.size else None,
                            P95_abs_pp=float(np.percentile(errors, 95)) if errors.size else None,
                            MAX_abs_pp=float(errors.max()) if errors.size else None)
    return result
