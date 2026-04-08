from __future__ import annotations

from dataclasses import dataclass

from .models import FlightOption, ScoreBreakdown, SearchRequest


@dataclass(slots=True)
class ScoringRules:
    min_connection_minutes: int = 45
    min_self_transfer_minutes: int = 180
    stop_penalty_usd: float = 60.0
    airport_change_penalty_usd: float = 125.0
    self_transfer_penalty_usd: float = 180.0
    overnight_penalty_usd: float = 90.0
    long_trip_penalty_per_hour_usd: float = 12.0
    long_layover_threshold_minutes: int = 180
    long_layover_penalty_per_hour_usd: float = 8.0


def evaluate_option(
    option: FlightOption,
    baseline: FlightOption,
    request: SearchRequest,
    rules: ScoringRules | None = None,
) -> ScoreBreakdown:
    active_rules = rules or ScoringRules()
    reasons: list[str] = []

    if option.stops > request.max_stops:
        reasons.append(f"too many stops ({option.stops} > {request.max_stops})")

    if option.overnight_layover and not request.allow_overnight:
        reasons.append("overnight layover not allowed")

    for layover in option.layover_minutes:
        if option.self_transfer and layover < active_rules.min_self_transfer_minutes:
            reasons.append(
                f"self-transfer layover below {active_rules.min_self_transfer_minutes} minutes"
            )
            break
        if not option.self_transfer and layover < active_rules.min_connection_minutes:
            reasons.append(
                f"connection below {active_rules.min_connection_minutes} minutes"
            )
            break

    penalty = 0.0
    penalty += option.stops * active_rules.stop_penalty_usd
    penalty += option.airport_change_count * active_rules.airport_change_penalty_usd

    if option.self_transfer:
        penalty += active_rules.self_transfer_penalty_usd

    if option.overnight_layover:
        penalty += active_rules.overnight_penalty_usd

    extra_trip_minutes = max(0, option.duration_minutes - baseline.duration_minutes)
    penalty += (extra_trip_minutes / 60.0) * active_rules.long_trip_penalty_per_hour_usd

    for layover in option.layover_minutes:
        if layover > active_rules.long_layover_threshold_minutes:
            overflow_minutes = layover - active_rules.long_layover_threshold_minutes
            penalty += (overflow_minutes / 60.0) * active_rules.long_layover_penalty_per_hour_usd

    effective_cost = (
        option.price_usd
        + option.baggage_fees_usd
        + option.reposition_cost_usd
        + penalty
    )

    price_savings = baseline.price_usd - option.price_usd

    return ScoreBreakdown(
        option=option,
        effective_cost_usd=round(effective_cost, 2),
        price_savings_usd=round(price_savings, 2),
        hassle_penalty_usd=round(penalty, 2),
        accepted=not reasons,
        reasons=tuple(reasons),
    )
