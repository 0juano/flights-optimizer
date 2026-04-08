from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class SearchRequest:
    origin: str
    destination: str
    cabin: str = "economy"
    allow_overnight: bool = False
    max_stops: int = 2

    def __post_init__(self) -> None:
        if self.max_stops < 0:
            raise ValueError("max_stops must be zero or greater")


@dataclass(slots=True)
class FlightOption:
    option_id: str
    label: str
    price_usd: float
    duration_minutes: int
    stops: int
    layover_minutes: tuple[int, ...] = field(default_factory=tuple)
    baggage_fees_usd: float = 0.0
    reposition_cost_usd: float = 0.0
    airport_change_count: int = 0
    self_transfer: bool = False
    overnight_layover: bool = False

    def __post_init__(self) -> None:
        if self.price_usd < 0:
            raise ValueError("price_usd must be zero or greater")
        if self.duration_minutes <= 0:
            raise ValueError("duration_minutes must be greater than zero")
        if self.stops < 0:
            raise ValueError("stops must be zero or greater")
        if self.airport_change_count < 0:
            raise ValueError("airport_change_count must be zero or greater")
        if len(self.layover_minutes) > self.stops:
            raise ValueError("layover_minutes cannot outnumber stops")
        if any(minutes <= 0 for minutes in self.layover_minutes):
            raise ValueError("layover_minutes must contain positive values")


@dataclass(slots=True)
class ScoreBreakdown:
    option: FlightOption
    effective_cost_usd: float
    price_savings_usd: float
    hassle_penalty_usd: float
    accepted: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def rejected(self) -> bool:
        return not self.accepted
