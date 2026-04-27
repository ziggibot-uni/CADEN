"""Learning-quality diagnostics and optimization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from scipy.stats import binomtest


@dataclass(frozen=True)
class BiasTestResult:
	successes: int
	trials: int
	pvalue: float
	biased: bool


@dataclass(frozen=True)
class ScheduleCandidate:
	id: str
	mood: float
	energy: float
	productivity: float


def pareto_frontier(candidates: Iterable[ScheduleCandidate]) -> list[ScheduleCandidate]:
	"""Return non-dominated candidates maximizing mood, energy, productivity."""
	items = list(candidates)
	frontier: list[ScheduleCandidate] = []
	for candidate in items:
		dominated = False
		for other in items:
			if other is candidate:
				continue
			if (
				other.mood >= candidate.mood
				and other.energy >= candidate.energy
				and other.productivity >= candidate.productivity
				and (
					other.mood > candidate.mood
					or other.energy > candidate.energy
					or other.productivity > candidate.productivity
				)
			):
				dominated = True
				break
		if not dominated:
			frontier.append(candidate)
	return frontier


def infer_preference_weights(
	overrides: Iterable[tuple[ScheduleCandidate, ScheduleCandidate]],
) -> dict[str, float]:
	"""Infer axis preference weights from Sean's selected-vs-rejected pairs."""
	delta_mood = 0.0
	delta_energy = 0.0
	delta_productivity = 0.0
	count = 0
	for selected, rejected in overrides:
		delta_mood += selected.mood - rejected.mood
		delta_energy += selected.energy - rejected.energy
		delta_productivity += selected.productivity - rejected.productivity
		count += 1

	if count == 0:
		return {}

	raw = {
		"mood": max(0.0, delta_mood / count),
		"energy": max(0.0, delta_energy / count),
		"productivity": max(0.0, delta_productivity / count),
	}
	total = raw["mood"] + raw["energy"] + raw["productivity"]
	if total <= 0.0:
		return {}
	return {
		"mood": raw["mood"] / total,
		"energy": raw["energy"] / total,
		"productivity": raw["productivity"] / total,
	}


def rank_frontier_with_preferences(
	frontier: Iterable[ScheduleCandidate],
	preferences: dict[str, float],
) -> list[ScheduleCandidate]:
	"""Rank Pareto-equivalent candidates by learned revealed preferences."""
	if not preferences:
		return list(frontier)

	def _score(item: ScheduleCandidate) -> float:
		return (
			item.mood * float(preferences.get("mood", 0.0))
			+ item.energy * float(preferences.get("energy", 0.0))
			+ item.productivity * float(preferences.get("productivity", 0.0))
		)

	return sorted(list(frontier), key=_score, reverse=True)


def detect_directional_bias(
	successes: int,
	trials: int,
	*,
	expected_rate: float = 0.5,
	alpha: float = 0.05,
) -> BiasTestResult:
	"""Use a binomial test to detect directional bias in outcomes."""
	if trials <= 0:
		raise ValueError("trials must be > 0")
	if successes < 0 or successes > trials:
		raise ValueError("successes must be between 0 and trials")
	if not 0.0 < expected_rate < 1.0:
		raise ValueError("expected_rate must be in (0, 1)")

	result = binomtest(successes, trials, expected_rate)
	pvalue = float(result.pvalue)
	return BiasTestResult(
		successes=successes,
		trials=trials,
		pvalue=pvalue,
		biased=pvalue < alpha,
	)
