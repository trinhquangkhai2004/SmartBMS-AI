"""Causal SoH guard for P3.6 replay, P3.7 evaluation and later F3 packaging.

The caller must deliver observations in eligible charge-cycle order per cell.
A model/schema effective version identifies the persisted baseline namespace.
"""
from dataclasses import asdict, dataclass, field
from math import isfinite


@dataclass
class CellState:
    model_version: str
    last_cycle: int | None = None
    baseline: float | None = None
    baseline_cycle: int | None = None
    baseline_version: int = 0
    pending: list[float] = field(default_factory=list)
    pending_cycle: int | None = None

    def clear_pending(self):
        self.pending.clear()
        self.pending_cycle = None


class EvaluationGuard:
    def __init__(self, policy, snapshot=None):
        self.feature_names = tuple(policy["primary_features"])
        self.feature_limits = tuple(tuple(policy["feature_bounds"][name]["weighted"])
                                    for name in self.feature_names)
        self.min_violations = policy["min_feature_violations"]
        self.sigma_limit = policy["sigma_threshold_pp"]
        self.delta = policy["delta_max_pp"]
        self.confirmations = policy["resync_confirm_k"]
        self.stability = policy["resync_stability_pp"]
        self.gap = policy["max_confirmation_gap_cycles"]
        if (not self.feature_limits
            or any(not isfinite(lo) or not isfinite(hi) or lo > hi for lo, hi in self.feature_limits)
            or not 1 <= self.min_violations <= len(self.feature_limits)
            or not all(isfinite(v) and v >= 0 for v in (self.sigma_limit, self.delta, self.stability))
            or self.confirmations < 2 or self.gap < 1):
            raise ValueError("Invalid guard policy thresholds")
        self.states = {cell: CellState(**values) for cell, values in (snapshot or {}).items()}

    def snapshot(self):
        """Return JSON-compatible, detached state for a restart."""
        return {cell: asdict(state) for cell, state in self.states.items()}

    def model_status(self, features, sigma_trees_pp):
        if len(features) != len(self.feature_limits) or any(v is None or not isfinite(v) for v in features):
            return "MISSING_FEATURE"
        breaches = sum(v < low or v > high for v, (low, high) in zip(features, self.feature_limits))
        if breaches >= self.min_violations:
            return "OUT_OF_DOMAIN"
        if sigma_trees_pp is None or not isfinite(sigma_trees_pp) or not 0 <= sigma_trees_pp <= self.sigma_limit:
            return "MODEL_UNCERTAIN"
        return None

    def evaluate(self, cell_id, model_version, cycle_id, features, raw_soh, sigma_trees_pp,
                 *, history_valid=True, stale=False):
        if stale:
            prior_status = "STALE_INPUT"
        elif not history_valid:
            prior_status = "INSUFFICIENT_HISTORY"
        else:
            prior_status = self.model_status(features, sigma_trees_pp)
        return self.advance(cell_id, model_version, cycle_id, raw_soh, prior_status)

    def advance(self, cell_id, model_version, cycle_id, raw_soh, prior_status):
        """Apply chronology/jump rules after per-row guards; also used by development replay."""
        state = self.states.get(cell_id)
        if state is None or state.model_version != model_version:
            state = self.states[cell_id] = CellState(model_version)
        if state.last_cycle is not None and cycle_id <= state.last_cycle:
            return self._result(state, "STALE_INPUT", "NONINCREASING_CYCLE")
        state.last_cycle = cycle_id
        if prior_status:
            state.clear_pending()
            return self._result(state, prior_status)
        if raw_soh is None or not isfinite(raw_soh):
            state.clear_pending()
            return self._result(state, "MODEL_UNCERTAIN", "NONFINITE_PREDICTION")
        if state.baseline is None:
            state.baseline_version = 1
            return self._accept(state, raw_soh, cycle_id, "BASELINE_INITIALIZED")
        if abs(raw_soh - state.baseline) <= self.delta:
            return self._accept(state, raw_soh, cycle_id)

        reason = None
        if state.pending_cycle is not None:
            if cycle_id - state.pending_cycle > self.gap:
                reason = "CONFIRMATION_GAP_EXCEEDED"
            else:
                lo = min(raw_soh, min(state.pending))
                hi = max(raw_soh, max(state.pending))
                if hi - lo > self.stability:
                    reason = "UNSTABLE_CONFIRMATION"
        if reason:
            state.clear_pending()
        state.pending.append(raw_soh)
        state.pending_cycle = cycle_id
        confirmations = len(state.pending)
        if confirmations < self.confirmations:
            return self._result(state, "SOH_JUMP_ANOMALY", reason or "JUMP_PENDING",
                                confirmation_count=confirmations)
        previous = state.baseline
        state.baseline_version += 1
        return self._accept(state, raw_soh, cycle_id, "SOH_BASELINE_RESYNCED",
                            previous_baseline_pp=previous, confirmation_count=confirmations)

    def _accept(self, state, raw_soh, cycle_id, reason=None, **audit):
        state.baseline = raw_soh
        state.baseline_cycle = cycle_id
        state.clear_pending()
        return self._result(state, "VALID", reason, **audit)

    @staticmethod
    def _result(state, status, reason=None, **audit):
        return dict(status=status, soh_percent=state.baseline if status == "VALID" else None,
                    reason=reason, last_valid_soh=state.baseline, last_valid_cycle=state.baseline_cycle,
                    baseline_version=state.baseline_version, **audit)
