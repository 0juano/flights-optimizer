from __future__ import annotations

from dataclasses import dataclass

from .models import FlightOption, ScoreBreakdown, SearchRequest


@dataclass(slots=True)
class ScoringRules:
    min_connection_minutes: int = 45
    min_self_transfer_minutes: int = 180
    stop_penalty: float = 60.0
    airport_change_penalty: float = 125.0
    self_transfer_penalty: float = 180.0
    overnight_penalty: float = 90.0
    long_trip_penalty_per_hour: float = 12.0
    long_layover_threshold_minutes: int = 180
    long_layover_penalty_per_hour: float = 8.0

    @classmethod
    def scaled_for_baseline(cls, baseline_price: float) -> "ScoringRules":
        """Scale penalties off the baseline fare so live searches stay currency-neutral."""
        safe_price = max(baseline_price, 1.0)
        return cls(
            stop_penalty=round(safe_price * 0.03, 2),
            airport_change_penalty=round(safe_price * 0.05, 2),
            self_transfer_penalty=round(safe_price * 0.07, 2),
            overnight_penalty=round(safe_price * 0.04, 2),
            long_trip_penalty_per_hour=round(safe_price * 0.005, 2),
            long_layover_penalty_per_hour=round(safe_price * 0.003, 2),
        )


def evaluate_option(
    option: FlightOption,
    baseline: FlightOption,
    request: SearchRequest,
    rules: ScoringRules | None = None,
) -> ScoreBreakdown:
    active_rules = rules or ScoringRules()
    reasons: list[str] = []

    if option.currency != baseline.currency:
        reasons.append(f"currency mismatch ({option.currency} vs {baseline.currency})")

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
    penalty += option.stops * active_rules.stop_penalty
    penalty += option.airport_change_count * active_rules.airport_change_penalty

    if option.self_transfer:
        penalty += active_rules.self_transfer_penalty

    if option.overnight_layover:
        penalty += active_rules.overnight_penalty

    extra_trip_minutes = max(0, option.duration_minutes - baseline.duration_minutes)
    penalty += (extra_trip_minutes / 60.0) * active_rules.long_trip_penalty_per_hour

    for layover in option.layover_minutes:
        if layover > active_rules.long_layover_threshold_minutes:
            overflow_minutes = layover - active_rules.long_layover_threshold_minutes
            penalty += (overflow_minutes / 60.0) * active_rules.long_layover_penalty_per_hour

    effective_cost = (
        option.price
        + option.baggage_fees
        + option.reposition_cost
        + penalty
    )

    price_savings = baseline.price - option.price

    return ScoreBreakdown(
        option=option,
        effective_cost=round(effective_cost, 2),
        price_savings=round(price_savings, 2),
        hassle_penalty=round(penalty, 2),
        accepted=not reasons,
        reasons=tuple(reasons),
    )
