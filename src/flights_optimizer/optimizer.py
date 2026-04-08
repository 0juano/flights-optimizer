from __future__ import annotations

from dataclasses import dataclass

from .models import FlightOption, ScoreBreakdown, SearchRequest
from .scoring import ScoringRules, evaluate_option


@dataclass(slots=True)
class OptimizationResult:
    baseline: ScoreBreakdown
    ranked_options: list[ScoreBreakdown]
    rejected_options: list[ScoreBreakdown]
    best_value: ScoreBreakdown
    cheapest_worth_it: ScoreBreakdown
    easiest_reasonable: ScoreBreakdown


def optimize_trip(
    request: SearchRequest,
    baseline_option: FlightOption,
    candidates: list[FlightOption],
    rules: ScoringRules | None = None,
) -> OptimizationResult:
    active_rules = rules or ScoringRules()
    baseline = evaluate_option(baseline_option, baseline_option, request, active_rules)

    accepted_by_id: dict[str, ScoreBreakdown] = {baseline.option.option_id: baseline}
    rejected: list[ScoreBreakdown] = []

    for option in candidates:
        scored = evaluate_option(option, baseline_option, request, active_rules)
        if scored.accepted:
            accepted_by_id[option.option_id] = scored
        else:
            rejected.append(scored)

    ranked = sorted(
        accepted_by_id.values(),
        key=lambda item: (
            item.effective_cost,
            item.option.duration_minutes,
            item.option.stops,
            item.option.price,
        ),
    )

    cheaper_than_baseline = [
        item
        for item in ranked
        if item.option.option_id != baseline.option.option_id
        and item.option.price < baseline.option.price
        and item.effective_cost < baseline.effective_cost
    ]

    easiest_reasonable = min(
        ranked,
        key=lambda item: (
            item.option.stops,
            item.option.airport_change_count,
            int(item.option.self_transfer),
            int(item.option.overnight_layover),
            item.option.duration_minutes,
            item.effective_cost,
        ),
    )

    return OptimizationResult(
        baseline=baseline,
        ranked_options=ranked,
        rejected_options=sorted(rejected, key=lambda item: item.option.price),
        best_value=ranked[0],
        cheapest_worth_it=cheaper_than_baseline[0] if cheaper_than_baseline else baseline,
        easiest_reasonable=easiest_reasonable,
    )
