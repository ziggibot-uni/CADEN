"""Phase-change and trend diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
import math

from scipy.stats import kendalltau


@dataclass(frozen=True)
class MannKendallResult:
	tau: float
	pvalue: float
	trend: str


def mann_kendall_trend(values: list[float]) -> MannKendallResult:
	"""Compute a Mann-Kendall trend test over an ordered series.

	Returns Kendall's tau, p-value, and a coarse trend label.
	"""
	if len(values) < 3:
		raise ValueError("at least 3 values are required for trend detection")

	x = list(range(len(values)))
	tau, pvalue = kendalltau(x, values)
	tau_f = float(0.0 if tau is None else tau)
	p_f = float(1.0 if pvalue is None else pvalue)
	if math.isnan(tau_f):
		tau_f = 0.0
	if math.isnan(p_f):
		p_f = 1.0

	if p_f < 0.05 and tau_f > 0:
		trend = "increasing"
	elif p_f < 0.05 and tau_f < 0:
		trend = "decreasing"
	else:
		trend = "no-trend"

	return MannKendallResult(tau=tau_f, pvalue=p_f, trend=trend)
