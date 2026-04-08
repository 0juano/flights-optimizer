from flights_optimizer.models import FlightOption, SearchRequest
from flights_optimizer.optimizer import optimize_trip
from flights_optimizer.scoring import ScoringRules, evaluate_option


def make_request() -> SearchRequest:
    return SearchRequest(origin="DEL", destination="SFO", cabin="business")


def make_baseline() -> FlightOption:
    return FlightOption(
        option_id="baseline",
        label="Baseline nonstop",
        price_usd=4200,
        duration_minutes=930,
        stops=0,
    )


def test_rejects_tight_self_transfer() -> None:
    option = FlightOption(
        option_id="split",
        label="Split ticket",
        price_usd=2600,
        duration_minutes=1360,
        stops=2,
        layover_minutes=(75, 120),
        self_transfer=True,
    )

    result = evaluate_option(option, make_baseline(), make_request())

    assert result.rejected is True
    assert "self-transfer layover below 180 minutes" in result.reasons


def test_penalties_make_cleaner_route_win() -> None:
    baseline = make_baseline()
    request = make_request()

    cleaner = FlightOption(
        option_id="clean",
        label="One stop",
        price_usd=3350,
        duration_minutes=1180,
        stops=1,
        layover_minutes=(150,),
    )
    chaotic = FlightOption(
        option_id="chaos",
        label="Two stops and airport change",
        price_usd=3200,
        duration_minutes=1400,
        stops=2,
        layover_minutes=(140, 200),
        self_transfer=True,
        airport_change_count=1,
        reposition_cost_usd=85,
    )

    cleaner_score = evaluate_option(cleaner, baseline, request)
    chaotic_score = evaluate_option(
        chaotic,
        baseline,
        request,
        ScoringRules(min_self_transfer_minutes=120),
    )

    assert cleaner_score.accepted is True
    assert chaotic_score.accepted is True
    assert cleaner_score.effective_cost_usd < chaotic_score.effective_cost_usd


def test_optimizer_returns_useful_shortlist() -> None:
    baseline = make_baseline()
    request = make_request()

    candidates = [
        FlightOption(
            option_id="best",
            label="Best value",
            price_usd=2950,
            duration_minutes=1220,
            stops=1,
            layover_minutes=(170,),
        ),
        FlightOption(
            option_id="cheap-but-bad",
            label="Cheap but bad",
            price_usd=2600,
            duration_minutes=1360,
            stops=2,
            layover_minutes=(75, 95),
            self_transfer=True,
            airport_change_count=1,
            reposition_cost_usd=85,
        ),
        FlightOption(
            option_id="easy",
            label="Easy option",
            price_usd=4050,
            duration_minutes=960,
            stops=0,
        ),
    ]

    result = optimize_trip(request, baseline, candidates)

    assert result.best_value.option.option_id == "best"
    assert result.cheapest_worth_it.option.option_id == "best"
    assert result.easiest_reasonable.option.option_id == "baseline"
    assert [item.option.option_id for item in result.rejected_options] == ["cheap-but-bad"]


def test_baseline_survives_when_alternatives_are_worse() -> None:
    baseline = make_baseline()
    request = make_request()

    candidates = [
        FlightOption(
            option_id="worse-1",
            label="Worse one-stop",
            price_usd=4100,
            duration_minutes=1440,
            stops=1,
            layover_minutes=(240,),
        ),
        FlightOption(
            option_id="worse-2",
            label="Rejected overnight",
            price_usd=3000,
            duration_minutes=1700,
            stops=1,
            layover_minutes=(700,),
            overnight_layover=True,
        ),
    ]

    result = optimize_trip(request, baseline, candidates)

    assert result.best_value.option.option_id == "baseline"
    assert result.cheapest_worth_it.option.option_id == "baseline"
