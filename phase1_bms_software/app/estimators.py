"""Substitution points only. Future input models/configuration remain undefined."""
from typing import Protocol

from app.schemas import EstimationResult


class SoCEstimator(Protocol):
    def estimate(self, measurement_window, config) -> EstimationResult: ...


class SoHEstimator(Protocol):
    def estimate(self, historical_data, config) -> EstimationResult: ...


class NotReadyEstimator:
    def estimate(self, data, config) -> EstimationResult:
        return EstimationResult()
