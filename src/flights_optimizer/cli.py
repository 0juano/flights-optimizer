from __future__ import annotations

import argparse
from typing import Iterable

from .live_search import LiveSearchRequest, LiveSearchResult, search_live_trip
from .models import FlightOption, ScoreBreakdown, SearchRequest
from .optimizer import OptimizationResult, optimize_trip


def format_money(amount: float, currency: str | None) -> str:
    value = float(amount)
    precision = 0 if value.is_integer() else 2
    code = currency or "UNKNOWN"
    return f"{code} {value:,.{precision}f}"


def savings_text(item: ScoreBreakdown, baseline: ScoreBreakdown) -> str:
    delta = baseline.effective_cost - item.effective_cost
    if abs(delta) < 0.01:
        return "same as baseline"
    if delta > 0:
        return f"{format_money(delta, item.option.currency)} better than baseline"
    return f"{format_money(abs(delta), item.option.currency)} worse than baseline"


def print_shortlist(result: OptimizationResult) -> None:
    print("Shortlist")
    print("---------")
    for title, item in (
        ("Best value", result.best_value),
        ("Cheapest worth it", result.cheapest_worth_it),
        ("Easiest reasonable", result.easiest_reasonable),
    ):
        print(
            f"{title:<18} {item.option.label:<42} "
            f"{format_money(item.effective_cost, item.option.currency):>18} "
            f"({savings_text(item, result.baseline)})"
        )
    print()


def print_ranked_options(result: OptimizationResult) -> None:
    print("Accepted options")
    print("----------------")
    for item in result.ranked_options:
        print(
            f"{item.option.label:<44} "
            f"fare={format_money(item.option.price, item.option.currency):>16} "
            f"penalty={format_money(item.hassle_penalty, item.option.currency):>16} "
            f"adjusted={format_money(item.effective_cost, item.option.currency):>16}"
        )
    print()

    print("Rejected options")
    print("----------------")
    if not result.rejected_options:
        print("None")
    for item in result.rejected_options:
        reason = "; ".join(item.reasons)
        print(
            f"{item.option.label:<44} "
            f"fare={format_money(item.option.price, item.option.currency):>16} "
            f"reason={reason}"
        )
    print()


def build_demo() -> tuple[SearchRequest, FlightOption, list[FlightOption]]:
    request = SearchRequest(origin="DEL", destination="SFO", cabin="business")
    baseline = FlightOption(
        option_id="baseline",
        label="DEL -> SFO nonstop",
        price=4200,
        currency="USD",
        duration_minutes=930,
        stops=0,
    )

    candidates = [
        FlightOption(
            option_id="sjc-1stop",
            label="DEL -> SJC 1 stop",
            price=2950,
            currency="USD",
            duration_minutes=1220,
            stops=1,
            layover_minutes=(170,),
        ),
        FlightOption(
            option_id="sfo-1stop",
            label="DEL -> SFO 1 stop",
            price=3350,
            currency="USD",
            duration_minutes=1180,
            stops=1,
            layover_minutes=(150,),
        ),
        FlightOption(
            option_id="oak-split",
            label="DEL -> OAK split ticket",
            price=2600,
            currency="USD",
            duration_minutes=1360,
            stops=2,
            layover_minutes=(75, 95),
            self_transfer=True,
            airport_change_count=1,
            reposition_cost=85,
        ),
        FlightOption(
            option_id="sfo-overnight",
            label="DEL -> SFO overnight",
            price=2800,
            currency="USD",
            duration_minutes=1620,
            stops=1,
            layover_minutes=(610,),
            overnight_layover=True,
        ),
    ]

    return request, baseline, candidates


def print_demo_result() -> None:
    request, baseline, candidates = build_demo()
    result = optimize_trip(request, baseline, candidates)

    print()
    print("Flight optimizer demo")
    print("=====================")
    print(f"Request: {request.origin} -> {request.destination} ({request.cabin})")
    print(
        f"Baseline: {baseline.label} at {format_money(baseline.price, baseline.currency)} "
        f"for {baseline.duration_minutes} minutes"
    )
    print()

    print_shortlist(result)
    print_ranked_options(result)


def parse_airport_codes(values: Iterable[str]) -> tuple[str, ...]:
    codes: list[str] = []
    seen: set[str] = set()
    for value in values:
        for part in value.split(","):
            code = part.strip().upper()
            if code and code not in seen:
                seen.add(code)
                codes.append(code)
    return tuple(codes)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bounded search-and-score engine for sane flight options."
    )
    parser.add_argument("origin", nargs="?")
    parser.add_argument("destination", nargs="?")
    parser.add_argument("departure_date", nargs="?")
    parser.add_argument(
        "--cabin",
        default="economy",
        choices=["economy", "premium_economy", "business", "first"],
    )
    parser.add_argument("--max-stops", type=int, default=2, choices=[0, 1, 2])
    parser.add_argument("--flex-days", type=int, default=1)
    parser.add_argument("--per-query", type=int, default=3)
    parser.add_argument("--allow-overnight", action="store_true")
    parser.add_argument("--alt-origin", action="append", default=[])
    parser.add_argument("--alt-destination", action="append", default=[])
    parser.add_argument("--demo", action="store_true")
    return parser


def print_live_result(result: LiveSearchResult) -> None:
    optimization = result.optimization
    baseline = optimization.baseline.option

    print()
    print("Flight optimizer live search")
    print("============================")
    print(
        f"Request: {result.request.origin} -> {result.request.destination} on "
        f"{result.request.departure_date} ({result.request.cabin})"
    )
    print(
        f"Looked at {len(result.route_pairs)} route pair(s) across "
        f"{len(result.search_dates)} date(s), {result.queries_run} query run(s)"
    )
    print(
        f"Baseline: {baseline.label} at {format_money(baseline.price, baseline.currency)} "
        f"for {baseline.duration_minutes} minutes"
    )
    if result.warnings:
        print()
        print("Notes")
        print("-----")
        for warning in result.warnings:
            print(f"- {warning}")
    print()

    print_shortlist(optimization)
    print_ranked_options(optimization)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.demo or not any((args.origin, args.destination, args.departure_date)):
        print_demo_result()
        return

    if not all((args.origin, args.destination, args.departure_date)):
        parser.error("origin, destination, and departure_date are required for live search")

    live_request = LiveSearchRequest(
        origin=args.origin.upper(),
        destination=args.destination.upper(),
        departure_date=args.departure_date,
        cabin=args.cabin,
        allow_overnight=args.allow_overnight,
        max_stops=args.max_stops,
        flex_days=args.flex_days,
        per_query=args.per_query,
        alt_origins=parse_airport_codes(args.alt_origin),
        alt_destinations=parse_airport_codes(args.alt_destination),
    )
    result = search_live_trip(live_request)
    print_live_result(result)


if __name__ == "__main__":
    main()
