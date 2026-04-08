from flights_optimizer.models import FlightOption, SearchRequest
from flights_optimizer.live_search import _flight_result_to_option
from flights_optimizer.optimizer import optimize_trip
from flights_optimizer.scoring import ScoringRules, evaluate_option
from fli.models import Airline, Airport, FlightLeg, FlightResult
from datetime import datetime


def make_request() -> SearchRequest:
    return SearchRequest(origin="DEL", destination="SFO", cabin="business")


def make_baseline() -> FlightOption:
    return FlightOption(
        option_id="baseline",
        label="Baseline nonstop",
        price=4200,
        currency="USD",
        duration_minutes=930,
        stops=0,
    )


def test_rejects_tight_self_transfer() -> None:
    option = FlightOption(
        option_id="split",
        label="Split ticket",
        price=2600,
        currency="USD",
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
        price=3350,
        currency="USD",
        duration_minutes=1180,
        stops=1,
        layover_minutes=(150,),
    )
    chaotic = FlightOption(
        option_id="chaos",
        label="Two stops and airport change",
        price=3200,
        currency="USD",
        duration_minutes=1400,
        stops=2,
        layover_minutes=(140, 200),
        self_transfer=True,
        airport_change_count=1,
        reposition_cost=85,
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
    assert cleaner_score.effective_cost < chaotic_score.effective_cost


def test_optimizer_returns_useful_shortlist() -> None:
    baseline = make_baseline()
    request = make_request()

    candidates = [
        FlightOption(
            option_id="best",
            label="Best value",
            price=2950,
            currency="USD",
            duration_minutes=1220,
            stops=1,
            layover_minutes=(170,),
        ),
        FlightOption(
            option_id="cheap-but-bad",
            label="Cheap but bad",
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
            option_id="easy",
            label="Easy option",
            price=4050,
            currency="USD",
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
            price=4100,
            currency="USD",
            duration_minutes=1440,
            stops=1,
            layover_minutes=(240,),
        ),
        FlightOption(
            option_id="worse-2",
            label="Rejected overnight",
            price=3000,
            currency="USD",
            duration_minutes=1700,
            stops=1,
            layover_minutes=(700,),
            overnight_layover=True,
        ),
    ]

    result = optimize_trip(request, baseline, candidates)

    assert result.best_value.option.option_id == "baseline"
    assert result.cheapest_worth_it.option.option_id == "baseline"


def test_scaled_rules_follow_baseline_price() -> None:
    rules = ScoringRules.scaled_for_baseline(2000)

    assert rules.stop_penalty == 60.0
    assert rules.airport_change_penalty == 100.0
    assert rules.self_transfer_penalty == 140.0


def test_fli_result_conversion_builds_option_metadata() -> None:
    flight = FlightResult(
        legs=[
            FlightLeg(
                airline=Airline.AA,
                flight_number="1202",
                departure_airport=Airport.JFK,
                arrival_airport=Airport.DFW,
                departure_datetime=datetime(2026, 5, 20, 7, 4),
                arrival_datetime=datetime(2026, 5, 20, 10, 6),
                duration=242,
            ),
            FlightLeg(
                airline=Airline.AA,
                flight_number="1181",
                departure_airport=Airport.DFW,
                arrival_airport=Airport.LAX,
                departure_datetime=datetime(2026, 5, 20, 11, 9),
                arrival_datetime=datetime(2026, 5, 20, 12, 33),
                duration=204,
            ),
        ],
        price=254085,
        currency="ARS",
        duration=509,
        stops=1,
    )

    option = _flight_result_to_option(
        flight=flight,
        primary_origin="JFK",
        primary_destination="LAX",
        baseline_price=254085,
    )

    assert option.label == "2026-05-20 07:04 JFK -> LAX via DFW (1 stop, 8h 29m)"
    assert option.layover_minutes == (63,)
    assert option.airport_change_count == 0
    assert option.reposition_cost == 0
    assert option.currency == "ARS"
