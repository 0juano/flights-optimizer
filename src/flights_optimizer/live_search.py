from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from fli.models import (
    Airport,
    FlightResult,
    FlightSearchFilters,
    FlightSegment,
    MaxStops,
    PassengerInfo,
    SeatType,
    SortBy,
    TripType,
)
from fli.search.flights import SearchFlights

from .models import FlightOption, SearchRequest
from .optimizer import OptimizationResult, optimize_trip
from .scoring import ScoringRules

_CABIN_MAP = {
    "economy": SeatType.ECONOMY,
    "premium_economy": SeatType.PREMIUM_ECONOMY,
    "business": SeatType.BUSINESS,
    "first": SeatType.FIRST,
}

_STOP_MAP = {
    0: MaxStops.NON_STOP,
    1: MaxStops.ONE_STOP_OR_FEWER,
    2: MaxStops.TWO_OR_FEWER_STOPS,
}


@dataclass(slots=True)
class LiveSearchRequest:
    origin: str
    destination: str
    departure_date: str
    cabin: str = "economy"
    allow_overnight: bool = False
    max_stops: int = 2
    flex_days: int = 1
    per_query: int = 3
    alt_origins: tuple[str, ...] = field(default_factory=tuple)
    alt_destinations: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        self.origin = self.origin.upper()
        self.destination = self.destination.upper()
        self.cabin = self.cabin.lower()
        if self.cabin not in _CABIN_MAP:
            raise ValueError(f"unsupported cabin class: {self.cabin}")
        if self.max_stops < 0:
            raise ValueError("max_stops must be zero or greater")
        if self.flex_days < 0:
            raise ValueError("flex_days must be zero or greater")
        if self.per_query < 1:
            raise ValueError("per_query must be at least 1")
        date.fromisoformat(self.departure_date)
        self.alt_origins = tuple(code.upper() for code in self.alt_origins if code.upper() != self.origin)
        self.alt_destinations = tuple(
            code.upper() for code in self.alt_destinations if code.upper() != self.destination
        )

    @property
    def route_pairs(self) -> tuple[tuple[str, str], ...]:
        origins = (self.origin, *self.alt_origins)
        destinations = (self.destination, *self.alt_destinations)
        return tuple((origin, destination) for origin in origins for destination in destinations)

    @property
    def search_dates(self) -> tuple[str, ...]:
        target_date = date.fromisoformat(self.departure_date)
        dates = [
            (target_date + timedelta(days=offset)).isoformat()
            for offset in range(-self.flex_days, self.flex_days + 1)
        ]
        return tuple(dates)


@dataclass(slots=True)
class LiveSearchResult:
    request: LiveSearchRequest
    optimization: OptimizationResult
    route_pairs: tuple[tuple[str, str], ...]
    search_dates: tuple[str, ...]
    queries_run: int
    warnings: tuple[str, ...] = field(default_factory=tuple)


def search_live_trip(request: LiveSearchRequest) -> LiveSearchResult:
    client = SearchFlights()
    warnings: list[str] = []
    queries_run = 0

    baseline_results = _search_flights(
        client=client,
        origin=request.origin,
        destination=request.destination,
        departure_date=request.departure_date,
        cabin=request.cabin,
        max_stops=request.max_stops,
        sort_by=SortBy.BEST,
    )
    queries_run += 1
    if not baseline_results:
        raise ValueError("no flights found for the requested route and date")

    baseline_result = baseline_results[0]
    baseline_option = _flight_result_to_option(
        flight=baseline_result,
        primary_origin=request.origin,
        primary_destination=request.destination,
        baseline_price=baseline_result.price,
    )

    candidates_by_id: dict[str, FlightOption] = {}
    for origin, destination in request.route_pairs:
        for departure_date in request.search_dates:
            try:
                results = _search_flights(
                    client=client,
                    origin=origin,
                    destination=destination,
                    departure_date=departure_date,
                    cabin=request.cabin,
                    max_stops=request.max_stops,
                    sort_by=SortBy.CHEAPEST,
                )
                queries_run += 1
            except Exception as exc:
                warnings.append(f"{origin} -> {destination} on {departure_date} failed: {exc}")
                continue

            for flight in results[: request.per_query]:
                if flight.currency and baseline_option.currency and flight.currency != baseline_option.currency:
                    warnings.append(
                        f"Skipped {origin} -> {destination} on {departure_date} because "
                        f"it came back in {flight.currency} instead of {baseline_option.currency}"
                    )
                    continue

                option = _flight_result_to_option(
                    flight=flight,
                    primary_origin=request.origin,
                    primary_destination=request.destination,
                    baseline_price=baseline_option.price,
                )
                candidates_by_id[option.option_id] = option

    search_request = SearchRequest(
        origin=request.origin,
        destination=request.destination,
        cabin=request.cabin,
        allow_overnight=request.allow_overnight,
        max_stops=request.max_stops,
    )
    optimization = optimize_trip(
        request=search_request,
        baseline_option=baseline_option,
        candidates=[item for item in candidates_by_id.values() if item.option_id != baseline_option.option_id],
        rules=ScoringRules.scaled_for_baseline(baseline_option.price),
    )

    return LiveSearchResult(
        request=request,
        optimization=optimization,
        route_pairs=request.route_pairs,
        search_dates=request.search_dates,
        queries_run=queries_run,
        warnings=tuple(warnings),
    )


def _search_flights(
    client: SearchFlights,
    origin: str,
    destination: str,
    departure_date: str,
    cabin: str,
    max_stops: int,
    sort_by: SortBy,
) -> list[FlightResult]:
    filters = FlightSearchFilters(
        trip_type=TripType.ONE_WAY,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[
            FlightSegment(
                departure_airport=[[_airport(origin), 0]],
                arrival_airport=[[_airport(destination), 0]],
                travel_date=departure_date,
            )
        ],
        stops=_max_stops(max_stops),
        seat_type=_CABIN_MAP[cabin],
        sort_by=sort_by,
    )
    results = client.search(filters) or []
    return list(results)


def _airport(code: str) -> Airport:
    try:
        return getattr(Airport, code.upper())
    except AttributeError as exc:
        raise ValueError(f"unknown airport code: {code}") from exc


def _max_stops(value: int) -> MaxStops:
    return _STOP_MAP.get(value, MaxStops.ANY)


def _flight_result_to_option(
    flight: FlightResult,
    primary_origin: str,
    primary_destination: str,
    baseline_price: float,
) -> FlightOption:
    layovers: list[int] = []
    airport_change_count = 0
    overnight_layover = False

    for previous_leg, next_leg in zip(flight.legs, flight.legs[1:]):
        layover_minutes = int((next_leg.departure_datetime - previous_leg.arrival_datetime).total_seconds() // 60)
        layovers.append(max(layover_minutes, 1))
        if previous_leg.arrival_airport != next_leg.departure_airport:
            airport_change_count += 1
        if next_leg.departure_datetime.date() > previous_leg.arrival_datetime.date():
            overnight_layover = True

    departure_code = flight.legs[0].departure_airport.name
    arrival_code = flight.legs[-1].arrival_airport.name
    via_codes = [leg.arrival_airport.name for leg in flight.legs[:-1]]
    departure_stamp = flight.legs[0].departure_datetime.strftime("%Y-%m-%d %H:%M")
    hours, minutes = divmod(flight.duration, 60)
    duration_label = f"{hours}h {minutes:02d}m"
    stops_label = "nonstop" if flight.stops == 0 else f"{flight.stops} stop"
    if flight.stops != 1:
        stops_label += "s"
    route_label = f"{departure_stamp} {departure_code} -> {arrival_code}"
    if via_codes:
        route_label += f" via {', '.join(via_codes)}"
    route_label += f" ({stops_label}, {duration_label})"

    reposition_cost = 0.0
    endpoint_penalty = baseline_price * 0.015
    if departure_code != primary_origin:
        reposition_cost += endpoint_penalty
    if arrival_code != primary_destination:
        reposition_cost += endpoint_penalty

    option_id = "|".join(
        f"{leg.departure_airport.name}-{leg.arrival_airport.name}-{leg.airline.name}-"
        f"{leg.flight_number}-{leg.departure_datetime.isoformat()}"
        for leg in flight.legs
    )

    return FlightOption(
        option_id=option_id,
        label=route_label,
        price=flight.price,
        currency=flight.currency or "UNKNOWN",
        duration_minutes=flight.duration,
        stops=flight.stops,
        layover_minutes=tuple(layovers),
        airport_change_count=airport_change_count,
        reposition_cost=round(reposition_cost, 2),
        overnight_layover=overnight_layover,
    )
