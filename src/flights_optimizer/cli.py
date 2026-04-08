from __future__ import annotations

from .models import FlightOption, SearchRequest
from .optimizer import OptimizationResult, optimize_trip


def format_money(amount: float) -> str:
    return f"${amount:,.0f}"


def print_shortlist(result: OptimizationResult) -> None:
    print("Shortlist")
    print("---------")
    print(
        f"Best value       {result.best_value.option.label:<30} "
        f"{format_money(result.best_value.effective_cost_usd)}"
    )
    print(
        f"Cheapest worth it {result.cheapest_worth_it.option.label:<29} "
        f"{format_money(result.cheapest_worth_it.effective_cost_usd)}"
    )
    print(
        f"Easiest reasonable {result.easiest_reasonable.option.label:<27} "
        f"{format_money(result.easiest_reasonable.effective_cost_usd)}"
    )
    print()


def print_ranked_options(result: OptimizationResult) -> None:
    print("Accepted options")
    print("----------------")
    for item in result.ranked_options:
        print(
            f"{item.option.label:<32} "
            f"ticket={format_money(item.option.price_usd):>7} "
            f"penalty={format_money(item.hassle_penalty_usd):>6} "
            f"effective={format_money(item.effective_cost_usd):>7}"
        )
    print()

    print("Rejected options")
    print("----------------")
    for item in result.rejected_options:
        reason = "; ".join(item.reasons)
        print(
            f"{item.option.label:<32} "
            f"ticket={format_money(item.option.price_usd):>7} "
            f"reason={reason}"
        )
    print()


def build_demo() -> tuple[SearchRequest, FlightOption, list[FlightOption]]:
    request = SearchRequest(origin="DEL", destination="SFO", cabin="business")
    baseline = FlightOption(
        option_id="baseline",
        label="DEL -> SFO nonstop",
        price_usd=4200,
        duration_minutes=930,
        stops=0,
    )

    candidates = [
        FlightOption(
            option_id="sjc-1stop",
            label="DEL -> SJC 1 stop",
            price_usd=2950,
            duration_minutes=1220,
            stops=1,
            layover_minutes=(170,),
        ),
        FlightOption(
            option_id="sfo-1stop",
            label="DEL -> SFO 1 stop",
            price_usd=3350,
            duration_minutes=1180,
            stops=1,
            layover_minutes=(150,),
        ),
        FlightOption(
            option_id="oak-split",
            label="DEL -> OAK split ticket",
            price_usd=2600,
            duration_minutes=1360,
            stops=2,
            layover_minutes=(75, 95),
            self_transfer=True,
            airport_change_count=1,
            reposition_cost_usd=85,
        ),
        FlightOption(
            option_id="sfo-overnight",
            label="DEL -> SFO overnight",
            price_usd=2800,
            duration_minutes=1620,
            stops=1,
            layover_minutes=(610,),
            overnight_layover=True,
        ),
    ]

    return request, baseline, candidates


def main() -> None:
    request, baseline, candidates = build_demo()
    result = optimize_trip(request, baseline, candidates)

    print()
    print("Flight optimizer demo")
    print("=====================")
    print(f"Request: {request.origin} -> {request.destination} ({request.cabin})")
    print(
        f"Baseline: {baseline.label} at {format_money(baseline.price_usd)} "
        f"for {baseline.duration_minutes} minutes"
    )
    print()

    print_shortlist(result)
    print_ranked_options(result)


if __name__ == "__main__":
    main()
