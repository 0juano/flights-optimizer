from datetime import datetime

from fli.models import Airline, Airport, FlightLeg, FlightResult

from flights_optimizer.trip_optimizer import FindRequest, _month_bounds, _passes_rules


def make_direct_pair() -> tuple[FlightResult, FlightResult]:
    outbound = FlightResult(
        legs=[
            FlightLeg(
                airline=Airline.IB,
                flight_number="110",
                departure_airport=Airport.EZE,
                arrival_airport=Airport.MAD,
                departure_datetime=datetime(2026, 7, 30, 12, 0),
                arrival_datetime=datetime(2026, 7, 31, 0, 0),
                duration=720,
            )
        ],
        price=2_500_000,
        currency="ARS",
        duration=720,
        stops=0,
    )
    inbound = FlightResult(
        legs=[
            FlightLeg(
                airline=Airline.IB,
                flight_number="107",
                departure_airport=Airport.MAD,
                arrival_airport=Airport.EZE,
                departure_datetime=datetime(2026, 8, 20, 1, 0),
                arrival_datetime=datetime(2026, 8, 20, 13, 30),
                duration=750,
            )
        ],
        price=2_500_000,
        currency="ARS",
        duration=750,
        stops=0,
    )
    return outbound, inbound


def make_request() -> FindRequest:
    return FindRequest(
        origin="EZE",
        prefer=("italy", "spain"),
        month="2026-07",
        stay_days=21,
        layover_min_minutes=60,
        layover_max_minutes=180,
    )


def test_month_bounds_cover_whole_month() -> None:
    assert _month_bounds("2026-07") == ("2026-07-01", "2026-07-31")
    assert _month_bounds("2026-12") == ("2026-12-01", "2026-12-31")


def test_long_layover_is_rejected() -> None:
    direct_outbound, direct_inbound = make_direct_pair()
    request = make_request()

    outbound = FlightResult(
        legs=[
            FlightLeg(
                airline=Airline.IB,
                flight_number="6840",
                departure_airport=Airport.EZE,
                arrival_airport=Airport.FCO,
                departure_datetime=datetime(2026, 7, 30, 10, 0),
                arrival_datetime=datetime(2026, 7, 30, 15, 0),
                duration=720,
            ),
            FlightLeg(
                airline=Airline.IB,
                flight_number="3201",
                departure_airport=Airport.FCO,
                arrival_airport=Airport.MAD,
                departure_datetime=datetime(2026, 7, 30, 19, 0),
                arrival_datetime=datetime(2026, 7, 30, 22, 0),
                duration=180,
            ),
        ],
        price=2_000_000,
        currency="ARS",
        duration=930,
        stops=1,
    )

    accepted, reason = _passes_rules(
        outbound=outbound,
        inbound=direct_inbound,
        direct_outbound=direct_outbound,
        direct_inbound=direct_inbound,
        request=request,
    )

    assert accepted is False
    assert "layover above 180 minutes" in reason


def test_route_with_short_clean_stop_passes() -> None:
    direct_outbound, direct_inbound = make_direct_pair()
    request = make_request()

    outbound = FlightResult(
        legs=[
            FlightLeg(
                airline=Airline.LH,
                flight_number="511",
                departure_airport=Airport.EZE,
                arrival_airport=Airport.FRA,
                departure_datetime=datetime(2026, 7, 30, 16, 50),
                arrival_datetime=datetime(2026, 7, 31, 8, 40),
                duration=710,
            ),
            FlightLeg(
                airline=Airline.LH,
                flight_number="242",
                departure_airport=Airport.FRA,
                arrival_airport=Airport.FCO,
                departure_datetime=datetime(2026, 7, 31, 9, 55),
                arrival_datetime=datetime(2026, 7, 31, 11, 35),
                duration=100,
            ),
        ],
        price=1_900_000,
        currency="ARS",
        duration=885,
        stops=1,
    )
    inbound = FlightResult(
        legs=[
            FlightLeg(
                airline=Airline.LH,
                flight_number="243",
                departure_airport=Airport.FCO,
                arrival_airport=Airport.FRA,
                departure_datetime=datetime(2026, 8, 20, 14, 0),
                arrival_datetime=datetime(2026, 8, 20, 15, 40),
                duration=100,
            ),
            FlightLeg(
                airline=Airline.LH,
                flight_number="510",
                departure_airport=Airport.FRA,
                arrival_airport=Airport.EZE,
                departure_datetime=datetime(2026, 8, 20, 17, 0),
                arrival_datetime=datetime(2026, 8, 21, 5, 0),
                duration=780,
            ),
        ],
        price=1_900_000,
        currency="ARS",
        duration=940,
        stops=1,
    )

    accepted, reason = _passes_rules(
        outbound=outbound,
        inbound=inbound,
        direct_outbound=direct_outbound,
        direct_inbound=direct_inbound,
        request=request,
    )

    assert accepted is True
    assert reason == "accepted"
