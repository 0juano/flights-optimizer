from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from urllib.request import urlopen

from fli.models import (
    Airport,
    DateSearchFilters,
    FlightLeg,
    FlightResult,
    FlightSearchFilters,
    FlightSegment,
    MaxStops,
    PassengerInfo,
    SeatType,
    SortBy,
    TripType,
)
from fli.search.dates import SearchDates
from fli.search.flights import SearchFlights

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

_COUNTRY_AIRPORTS: dict[str, tuple[tuple[str, str], ...]] = {
    "italy": (("Rome", "FCO"), ("Milan", "MXP")),
    "spain": (("Barcelona", "BCN"), ("Madrid", "MAD")),
    "france": (("Paris", "CDG"), ("Paris Orly", "ORY")),
}


@dataclass(slots=True)
class FindRequest:
    origin: str
    month: str
    stay_days: int
    prefer: tuple[str, ...]
    cabin: str = "economy"
    max_stops: int = 1
    layover_min_minutes: int = 60
    layover_max_minutes: int = 180
    direct_time_limit_pct: int = 30
    currency: str = "USD"
    top_date_windows: int = 2
    top_flights_per_window: int = 5
    allow_overnight: bool = False

    def __post_init__(self) -> None:
        self.origin = self.origin.upper()
        self.cabin = self.cabin.lower()
        self.currency = self.currency.upper()
        self.prefer = tuple(country.lower() for country in self.prefer)
        if self.cabin not in _CABIN_MAP:
            raise ValueError(f"unsupported cabin class: {self.cabin}")
        if self.stay_days < 1:
            raise ValueError("stay_days must be at least 1")
        if self.max_stops < 0 or self.max_stops > 2:
            raise ValueError("max_stops must be between 0 and 2")
        if self.layover_min_minutes < 0:
            raise ValueError("layover_min_minutes must be zero or greater")
        if self.layover_max_minutes < self.layover_min_minutes:
            raise ValueError("layover_max_minutes must be greater than layover_min_minutes")
        if self.direct_time_limit_pct < 0:
            raise ValueError("direct_time_limit_pct must be zero or greater")
        if self.top_date_windows < 1:
            raise ValueError("top_date_windows must be at least 1")
        if self.top_flights_per_window < 1:
            raise ValueError("top_flights_per_window must be at least 1")
        if not self.prefer:
            raise ValueError("prefer must contain at least one country")
        if any(country not in _COUNTRY_AIRPORTS for country in self.prefer):
            unknown = [country for country in self.prefer if country not in _COUNTRY_AIRPORTS]
            raise ValueError(f"unsupported preferences: {', '.join(sorted(unknown))}")
        _month_bounds(self.month)

    @property
    def destinations(self) -> tuple[tuple[str, str, str], ...]:
        rows: list[tuple[str, str, str]] = []
        for country in self.prefer:
            for city, airport in _COUNTRY_AIRPORTS[country]:
                rows.append((country.title(), city, airport))
        return tuple(rows)


@dataclass(slots=True)
class SearchWindow:
    departure_date: str
    return_date: str
    price: float
    currency: str


@dataclass(slots=True)
class SegmentSummary:
    route: str
    duration_minutes: int
    stops: int
    layovers_minutes: tuple[int, ...]
    airlines: tuple[str, ...]
    flight_numbers: tuple[str, ...]
    departure_time: str
    arrival_time: str


@dataclass(slots=True)
class TripOption:
    option_id: str
    destination_country: str
    destination_city: str
    destination_airport: str
    departure_date: str
    return_date: str
    total_price: float
    total_price_currency: str
    total_price_usd: float
    direct_price_usd: float
    total_stops: int
    nonstop: bool
    outbound_ratio_to_direct: float
    return_ratio_to_direct: float
    savings_vs_direct_usd: float
    reason: str
    outbound: SegmentSummary
    inbound: SegmentSummary


@dataclass(slots=True)
class RejectedCandidate:
    destination_country: str
    destination_city: str
    destination_airport: str
    departure_date: str
    return_date: str
    reason: str


@dataclass(slots=True)
class DestinationScan:
    destination_country: str
    destination_city: str
    destination_airport: str
    candidate_windows: int
    cheapest_window_price_usd: float | None
    accepted_options: int
    status: str


@dataclass(slots=True)
class SearchReport:
    search_id: str
    created_at: str
    request: FindRequest
    options: list[TripOption]
    rejected: list[RejectedCandidate]
    scans: list[DestinationScan]
    fx_rate_ars_per_usd: float | None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "SearchReport":
        request = FindRequest(**payload["request"])
        options = [
            TripOption(
                **{
                    **item,
                    "outbound": SegmentSummary(**item["outbound"]),
                    "inbound": SegmentSummary(**item["inbound"]),
                }
            )
            for item in payload["options"]
        ]
        rejected = [RejectedCandidate(**item) for item in payload["rejected"]]
        scans = [DestinationScan(**item) for item in payload["scans"]]
        return cls(
            search_id=payload["search_id"],
            created_at=payload["created_at"],
            request=request,
            options=options,
            rejected=rejected,
            scans=scans,
            fx_rate_ars_per_usd=payload.get("fx_rate_ars_per_usd"),
            warnings=tuple(payload.get("warnings", [])),
        )


def run_monthly_search(
    request: FindRequest,
    progress: callable | None = None,
) -> SearchReport:
    dates_client = SearchDates()
    flights_client = SearchFlights()
    search_id = _build_search_id()
    warnings: list[str] = []
    rejections: list[RejectedCandidate] = []
    scans: list[DestinationScan] = []
    options: list[TripOption] = []
    fx_rates = _load_exchange_rates()
    month_start, month_end = _month_bounds(request.month)

    for country, city, airport in request.destinations:
        if progress:
            progress(f"Scanning {city} date windows")
        try:
            windows = _scan_dates(
                client=dates_client,
                origin=request.origin,
                destination=airport,
                from_date=month_start,
                to_date=month_end,
                stay_days=request.stay_days,
                cabin=request.cabin,
                max_stops=request.max_stops,
            )
        except Exception as exc:
            scans.append(
                DestinationScan(
                    destination_country=country,
                    destination_city=city,
                    destination_airport=airport,
                    candidate_windows=0,
                    cheapest_window_price_usd=None,
                    accepted_options=0,
                    status=f"date scan failed: {exc}",
                )
            )
            warnings.append(f"{city}: date scan failed ({exc})")
            continue

        chosen_windows = windows[: request.top_date_windows]
        accepted_for_destination = 0
        cheapest_window_price_usd = (
            _convert_to_usd(chosen_windows[0].price, chosen_windows[0].currency, fx_rates)
            if chosen_windows
            else None
        )

        for window in chosen_windows:
            if progress:
                progress(f"Checking {city} {window.departure_date} -> {window.return_date}")
            try:
                direct_options = _search_round_trip(
                    client=flights_client,
                    origin=request.origin,
                    destination=airport,
                    departure_date=window.departure_date,
                    return_date=window.return_date,
                    cabin=request.cabin,
                    max_stops=0,
                    sort_by=SortBy.DURATION,
                )
            except Exception as exc:
                rejections.append(
                    RejectedCandidate(
                        destination_country=country,
                        destination_city=city,
                        destination_airport=airport,
                        departure_date=window.departure_date,
                        return_date=window.return_date,
                        reason=f"direct baseline failed: {exc}",
                    )
                )
                continue

            if not direct_options:
                rejections.append(
                    RejectedCandidate(
                        destination_country=country,
                        destination_city=city,
                        destination_airport=airport,
                        departure_date=window.departure_date,
                        return_date=window.return_date,
                        reason="no direct baseline found",
                    )
                )
                continue

            direct_outbound, direct_inbound = direct_options[0]
            direct_price_usd = _convert_to_usd(
                direct_outbound.price,
                direct_outbound.currency or "USD",
                fx_rates,
            )

            try:
                trip_options = _search_round_trip(
                    client=flights_client,
                    origin=request.origin,
                    destination=airport,
                    departure_date=window.departure_date,
                    return_date=window.return_date,
                    cabin=request.cabin,
                    max_stops=request.max_stops,
                    sort_by=SortBy.CHEAPEST,
                )
            except Exception as exc:
                rejections.append(
                    RejectedCandidate(
                        destination_country=country,
                        destination_city=city,
                        destination_airport=airport,
                        departure_date=window.departure_date,
                        return_date=window.return_date,
                        reason=f"flight search failed: {exc}",
                    )
                )
                continue

            accepted_here = 0
            for outbound, inbound in trip_options[: request.top_flights_per_window]:
                accepted, reason = _passes_rules(
                    outbound=outbound,
                    inbound=inbound,
                    direct_outbound=direct_outbound,
                    direct_inbound=direct_inbound,
                    request=request,
                )
                if not accepted:
                    rejections.append(
                        RejectedCandidate(
                            destination_country=country,
                            destination_city=city,
                            destination_airport=airport,
                            departure_date=window.departure_date,
                            return_date=window.return_date,
                            reason=reason,
                        )
                    )
                    continue

                options.append(
                    _build_option(
                        country=country,
                        city=city,
                        airport=airport,
                        departure_date=window.departure_date,
                        return_date=window.return_date,
                        outbound=outbound,
                        inbound=inbound,
                        direct_outbound=direct_outbound,
                        direct_inbound=direct_inbound,
                        direct_price_usd=direct_price_usd,
                        fx_rates=fx_rates,
                    )
                )
                accepted_here += 1
                accepted_for_destination += 1

            if accepted_here == 0:
                rejections.append(
                    RejectedCandidate(
                        destination_country=country,
                        destination_city=city,
                        destination_airport=airport,
                        departure_date=window.departure_date,
                        return_date=window.return_date,
                        reason="no itineraries survived the layover and direct-time rules",
                    )
                )

        scans.append(
            DestinationScan(
                destination_country=country,
                destination_city=city,
                destination_airport=airport,
                candidate_windows=len(chosen_windows),
                cheapest_window_price_usd=cheapest_window_price_usd,
                accepted_options=accepted_for_destination,
                status="ready" if accepted_for_destination else "no good fits",
            )
        )

    deduped = _dedupe_options(options)
    ranked = sorted(
        deduped,
        key=lambda item: (
            item.total_price_usd,
            item.total_stops,
            item.outbound.duration_minutes + item.inbound.duration_minutes,
        ),
    )
    _assign_reasons(ranked)

    return SearchReport(
        search_id=search_id,
        created_at=datetime.now().isoformat(timespec="seconds"),
        request=request,
        options=ranked,
        rejected=_dedupe_rejections(rejections),
        scans=scans,
        fx_rate_ars_per_usd=fx_rates.get("ARS"),
        warnings=tuple(warnings),
    )


def _build_search_id() -> str:
    return datetime.now().strftime("fo-%Y%m%d-%H%M%S")


def _month_bounds(value: str) -> tuple[str, str]:
    start = date.fromisoformat(f"{value}-01")
    if start.month == 12:
        next_month = date(start.year + 1, 1, 1)
    else:
        next_month = date(start.year, start.month + 1, 1)
    end = next_month - timedelta(days=1)
    return start.isoformat(), end.isoformat()


def _scan_dates(
    client: SearchDates,
    origin: str,
    destination: str,
    from_date: str,
    to_date: str,
    stay_days: int,
    cabin: str,
    max_stops: int,
) -> list[SearchWindow]:
    return_seed = (date.fromisoformat(from_date) + timedelta(days=stay_days)).isoformat()
    filters = DateSearchFilters(
        trip_type=TripType.ROUND_TRIP,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[
            FlightSegment(
                departure_airport=[[_airport(origin), 0]],
                arrival_airport=[[_airport(destination), 0]],
                travel_date=from_date,
            ),
            FlightSegment(
                departure_airport=[[_airport(destination), 0]],
                arrival_airport=[[_airport(origin), 0]],
                travel_date=return_seed,
            ),
        ],
        stops=_max_stops(max_stops),
        seat_type=_CABIN_MAP[cabin],
        from_date=from_date,
        to_date=to_date,
        duration=stay_days,
    )
    results = client.search(filters) or []
    windows = [
        SearchWindow(
            departure_date=item.date[0].date().isoformat(),
            return_date=item.date[1].date().isoformat(),
            price=item.price,
            currency=item.currency or "USD",
        )
        for item in results
    ]
    windows.sort(key=lambda item: item.price)
    return windows


def _search_round_trip(
    client: SearchFlights,
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str,
    cabin: str,
    max_stops: int,
    sort_by: SortBy,
) -> list[tuple[FlightResult, FlightResult]]:
    filters = FlightSearchFilters(
        trip_type=TripType.ROUND_TRIP,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[
            FlightSegment(
                departure_airport=[[_airport(origin), 0]],
                arrival_airport=[[_airport(destination), 0]],
                travel_date=departure_date,
            ),
            FlightSegment(
                departure_airport=[[_airport(destination), 0]],
                arrival_airport=[[_airport(origin), 0]],
                travel_date=return_date,
            ),
        ],
        stops=_max_stops(max_stops),
        seat_type=_CABIN_MAP[cabin],
        sort_by=sort_by,
        show_all_results=False,
    )
    results = client.search(filters, top_n=5) or []
    return [item for item in results if isinstance(item, tuple) and len(item) == 2]


def _passes_rules(
    outbound: FlightResult,
    inbound: FlightResult,
    direct_outbound: FlightResult,
    direct_inbound: FlightResult,
    request: FindRequest,
) -> tuple[bool, str]:
    for segment, label in ((outbound, "outbound"), (inbound, "return")):
        layovers = _layovers(segment.legs)
        if not request.allow_overnight and _has_overnight(segment.legs):
            return False, f"{label} has an overnight layover"
        if _has_airport_change(segment.legs):
            return False, f"{label} changes airports"
        if any(layover < request.layover_min_minutes for layover in layovers):
            return False, f"{label} has a layover below {request.layover_min_minutes} minutes"
        if any(layover > request.layover_max_minutes for layover in layovers):
            return False, f"{label} has a layover above {request.layover_max_minutes} minutes"

    outbound_cap = direct_outbound.duration * (1 + request.direct_time_limit_pct / 100)
    inbound_cap = direct_inbound.duration * (1 + request.direct_time_limit_pct / 100)
    if outbound.duration > outbound_cap:
        return False, "outbound is too slow versus direct"
    if inbound.duration > inbound_cap:
        return False, "return is too slow versus direct"
    return True, "accepted"


def _build_option(
    *,
    country: str,
    city: str,
    airport: str,
    departure_date: str,
    return_date: str,
    outbound: FlightResult,
    inbound: FlightResult,
    direct_outbound: FlightResult,
    direct_inbound: FlightResult,
    direct_price_usd: float,
    fx_rates: dict[str, float],
) -> TripOption:
    total_price_usd = _convert_to_usd(outbound.price, outbound.currency or "USD", fx_rates)
    outbound_summary = _segment_summary(outbound)
    inbound_summary = _segment_summary(inbound)
    outbound_ratio = outbound.duration / direct_outbound.duration
    inbound_ratio = inbound.duration / direct_inbound.duration

    option_id = "|".join(
        [departure_date, return_date, airport]
        + [f"{leg.airline.name}-{leg.flight_number}" for leg in outbound.legs]
        + [f"{leg.airline.name}-{leg.flight_number}" for leg in inbound.legs]
    )

    return TripOption(
        option_id=option_id,
        destination_country=country,
        destination_city=city,
        destination_airport=airport,
        departure_date=departure_date,
        return_date=return_date,
        total_price=outbound.price,
        total_price_currency=outbound.currency or "USD",
        total_price_usd=round(total_price_usd, 2),
        direct_price_usd=round(direct_price_usd, 2),
        total_stops=outbound.stops + inbound.stops,
        nonstop=(outbound.stops + inbound.stops) == 0,
        outbound_ratio_to_direct=round(outbound_ratio, 3),
        return_ratio_to_direct=round(inbound_ratio, 3),
        savings_vs_direct_usd=round(direct_price_usd - total_price_usd, 2),
        reason="",
        outbound=outbound_summary,
        inbound=inbound_summary,
    )


def _dedupe_options(options: list[TripOption]) -> list[TripOption]:
    kept: dict[str, TripOption] = {}
    for option in options:
        existing = kept.get(option.option_id)
        if existing is None or option.total_price_usd < existing.total_price_usd:
            kept[option.option_id] = option
    return list(kept.values())


def _dedupe_rejections(rejections: list[RejectedCandidate]) -> list[RejectedCandidate]:
    seen: set[tuple[str, str, str, str]] = set()
    kept: list[RejectedCandidate] = []
    for item in rejections:
        key = (
            item.destination_airport,
            item.departure_date,
            item.return_date,
            item.reason,
        )
        if key in seen:
            continue
        seen.add(key)
        kept.append(item)
    return kept


def _assign_reasons(options: list[TripOption]) -> None:
    if not options:
        return

    options[0].reason = "Cheapest overall that passed every rule."

    best_by_country: dict[str, TripOption] = {}
    for option in options:
        best_by_country.setdefault(option.destination_country, option)

    best_nonstop = next((item for item in options if item.nonstop), None)

    for option in options:
        if option.reason:
            continue
        if best_nonstop and option.option_id == best_nonstop.option_id:
            option.reason = "Best nonstop option."
            continue
        if best_by_country[option.destination_country].option_id == option.option_id:
            option.reason = f"Best {option.destination_country.lower()} option."
            continue
        if option.savings_vs_direct_usd > 0:
            option.reason = "Cheaper than the direct baseline and still within the time cap."
        else:
            option.reason = "Clean fit inside the rules."


def _segment_summary(segment: FlightResult) -> SegmentSummary:
    first_leg = segment.legs[0]
    last_leg = segment.legs[-1]
    path_codes = [first_leg.departure_airport.name, *[leg.arrival_airport.name for leg in segment.legs]]
    airlines = tuple(dict.fromkeys(leg.airline.value for leg in segment.legs))
    flight_numbers = tuple(f"{leg.airline.name.lstrip('_')}{leg.flight_number}" for leg in segment.legs)
    return SegmentSummary(
        route=" -> ".join(path_codes),
        duration_minutes=segment.duration,
        stops=segment.stops,
        layovers_minutes=_layovers(segment.legs),
        airlines=airlines,
        flight_numbers=flight_numbers,
        departure_time=first_leg.departure_datetime.isoformat(),
        arrival_time=last_leg.arrival_datetime.isoformat(),
    )


def _layovers(legs: list[FlightLeg]) -> tuple[int, ...]:
    layovers: list[int] = []
    for previous_leg, next_leg in zip(legs, legs[1:]):
        minutes = int((next_leg.departure_datetime - previous_leg.arrival_datetime).total_seconds() // 60)
        layovers.append(max(minutes, 0))
    return tuple(layovers)


def _has_overnight(legs: list[FlightLeg]) -> bool:
    return any(
        next_leg.departure_datetime.date() > previous_leg.arrival_datetime.date()
        for previous_leg, next_leg in zip(legs, legs[1:])
    )


def _has_airport_change(legs: list[FlightLeg]) -> bool:
    return any(
        previous_leg.arrival_airport != next_leg.departure_airport
        for previous_leg, next_leg in zip(legs, legs[1:])
    )


def _airport(code: str) -> Airport:
    try:
        return getattr(Airport, code.upper())
    except AttributeError as exc:
        raise ValueError(f"unknown airport code: {code}") from exc


def _max_stops(value: int) -> MaxStops:
    return _STOP_MAP.get(value, MaxStops.ANY)


def _load_exchange_rates() -> dict[str, float]:
    with urlopen("https://open.er-api.com/v6/latest/USD", timeout=20) as response:
        payload = json.load(response)
    if payload.get("result") != "success":
        raise ValueError("exchange-rate lookup failed")
    rates = payload.get("rates")
    if not isinstance(rates, dict):
        raise ValueError("exchange-rate payload did not include rates")
    return {str(code).upper(): float(value) for code, value in rates.items()}


def _convert_to_usd(amount: float, currency: str, rates: dict[str, float]) -> float:
    code = currency.upper()
    if code == "USD":
        return float(amount)
    if code not in rates:
        raise ValueError(f"missing FX rate for {code}")
    return float(amount) / rates[code]
