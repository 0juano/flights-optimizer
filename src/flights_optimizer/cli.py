from __future__ import annotations

import argparse
from datetime import datetime

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from .history import list_reports, load_report, save_report
from .trip_optimizer import FindRequest, SearchReport, TripOption, run_monthly_search

console = Console()


def format_money(amount: float, currency: str = "USD") -> str:
    value = float(amount)
    precision = 0 if value.is_integer() else 2
    return f"{currency.upper()} {value:,.{precision}f}"


def format_minutes(minutes: int) -> str:
    hours, mins = divmod(minutes, 60)
    return f"{hours}h {mins:02d}m"


def format_month_label(raw: str) -> str:
    return datetime.strptime(raw, "%Y-%m").strftime("%B %Y")


def format_timestamp(raw: str) -> str:
    value = datetime.fromisoformat(raw)
    return value.strftime("%b %d %H:%M")


def parse_countries(raw: str) -> tuple[str, ...]:
    items: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        value = part.strip().lower()
        if value and value not in seen:
            items.append(value)
            seen.add(value)
    return tuple(items)


def parse_layover_window(raw: str) -> tuple[int, int]:
    if ":" not in raw:
        raise argparse.ArgumentTypeError("layover window must look like 60:180")
    left, right = raw.split(":", 1)
    try:
        start = int(left)
        end = int(right)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("layover window must contain integers") from exc
    if start < 0 or end < start:
        raise argparse.ArgumentTypeError("layover window must be min:max with max >= min")
    return start, end


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fo",
        description="Sleek terminal optimizer for sane flight choices.",
    )
    subparsers = parser.add_subparsers(dest="command")

    find_parser = subparsers.add_parser("find", help="Scan a month and rank the best trip options.")
    find_parser.add_argument("--from", dest="origin", required=True, help="Origin airport code, e.g. EZE")
    find_parser.add_argument("--prefer", required=True, help="Comma-separated country list, e.g. italy,spain")
    find_parser.add_argument("--month", required=True, help="Departure month in YYYY-MM format")
    find_parser.add_argument("--stay", type=int, required=True, help="Trip length in days")
    find_parser.add_argument(
        "--cabin",
        default="economy",
        choices=["economy", "premium_economy", "business", "first"],
    )
    find_parser.add_argument("--max-stops", type=int, default=1, choices=[0, 1, 2])
    find_parser.add_argument(
        "--layover",
        default="60:180",
        help="Allowed layover range in minutes, e.g. 60:180",
    )
    find_parser.add_argument(
        "--vs-direct",
        type=int,
        default=30,
        help="Maximum slowdown versus direct per leg, as a percent",
    )
    find_parser.add_argument("--currency", default="USD", choices=["USD"])
    find_parser.add_argument("--top-windows", type=int, default=2, help="Date windows per airport to inspect")
    find_parser.add_argument(
        "--top-flights",
        type=int,
        default=5,
        help="Candidate itineraries per date window to inspect",
    )
    find_parser.add_argument("--allow-overnight", action="store_true")

    show_parser = subparsers.add_parser("show", help="Show full details for one result from the last search.")
    show_parser.add_argument("selection", help="Rank number from the last search, or a saved search id")
    show_parser.add_argument("rank", nargs="?", help="If a search id is given first, show this rank from that search")

    compare_parser = subparsers.add_parser(
        "compare", help="Compare a few ranked options from the last search."
    )
    compare_parser.add_argument("selections", nargs="+", help="Rank numbers from the last search")

    history_parser = subparsers.add_parser("history", help="List recent saved searches.")
    history_parser.add_argument("--limit", type=int, default=8)

    subparsers.add_parser("demo", help="Show a sample command without running a search.")

    return parser


def render_report(report: SearchReport) -> None:
    header = Table.grid(expand=True)
    header.add_column(justify="left")
    header.add_row(
        Text(
            f"From {report.request.origin}  |  {report.request.stay_days} nights  |  "
            f"{', '.join(country.title() for country in report.request.prefer)}  |  {report.request.currency}",
            style="bold white",
        )
    )
    header.add_row(
        Text(
            f"Max {report.request.max_stops} stop  |  Layovers "
            f"{report.request.layover_min_minutes}-{report.request.layover_max_minutes}m  |  "
            f"Each leg <= {report.request.direct_time_limit_pct}% slower than direct",
            style="cyan",
        )
    )
    console.print(
        Panel(
            header,
            title=f"[bold]Europe in {format_month_label(report.request.month)}[/bold]",
            subtitle=f"saved as {report.search_id}",
            border_style="bright_blue",
            box=box.ROUNDED,
        )
    )

    console.print(Rule("[bold cyan]Scan Summary[/bold cyan]"))
    scans = Table(box=box.SIMPLE_HEAVY, expand=True)
    scans.add_column("Destination", style="bold white")
    scans.add_column("Windows", justify="right")
    scans.add_column("Best Window", justify="right")
    scans.add_column("Accepted", justify="right")
    scans.add_column("Status", style="cyan")
    for scan in report.scans:
        scans.add_row(
            f"{scan.destination_city} ({scan.destination_airport})",
            str(scan.candidate_windows),
            format_money(scan.cheapest_window_price_usd or 0) if scan.cheapest_window_price_usd else "-",
            str(scan.accepted_options),
            scan.status,
        )
    console.print(scans)

    console.print(Rule("[bold cyan]Best Picks[/bold cyan]"))
    if not report.options:
        console.print(
            Panel(
                "No trips survived the rules. Try relaxing layovers or the direct-time cap.",
                border_style="red",
            )
        )
    else:
        winners = Table(box=box.SIMPLE_HEAVY, expand=True)
        winners.add_column("#", justify="right", style="bold cyan")
        winners.add_column("Destination", style="bold white")
        winners.add_column("Dates", style="white")
        winners.add_column("Price", justify="right", style="bold green")
        winners.add_column("Shape", style="white")
        winners.add_column("Why It Won", style="cyan")
        for index, option in enumerate(report.options[:6], start=1):
            winners.add_row(
                str(index),
                f"{option.destination_city} ({option.destination_airport})",
                f"{option.departure_date} -> {option.return_date}",
                format_money(option.total_price_usd),
                "NONSTOP" if option.nonstop else f"{option.total_stops} total stops",
                option.reason,
            )
        console.print(winners)

        best = report.options[0]
        console.print()
        console.print(
            Panel(
                (
                    f"[bold]{best.destination_city}[/bold] is the current winner.\n"
                    f"{format_money(best.total_price_usd)}  |  "
                    f"{best.departure_date} -> {best.return_date}  |  "
                    f"{'Nonstop both ways' if best.nonstop else f'{best.total_stops} total stops'}\n"
                    f"{best.reason}"
                ),
                title="Top Recommendation",
                border_style="green",
                box=box.ROUNDED,
            )
        )

    if report.rejected:
        console.print(Rule("[bold cyan]Rejected[/bold cyan]"))
        rejected = Table(box=box.SIMPLE, expand=True)
        rejected.add_column("Route", style="white")
        rejected.add_column("Dates", style="white")
        rejected.add_column("Reason", style="red")
        for item in report.rejected[:8]:
            rejected.add_row(
                f"{item.destination_city} ({item.destination_airport})",
                f"{item.departure_date} -> {item.return_date}",
                item.reason,
            )
        console.print(rejected)

    if report.warnings:
        console.print(Rule("[bold cyan]Notes[/bold cyan]"))
        for warning in report.warnings:
            console.print(f"[yellow]-[/yellow] {warning}")

    console.print()
    next_steps = (
        "Next: [bold]fo show 1[/bold]  |  [bold]fo compare 1 2 3[/bold]  |  [bold]fo history[/bold]"
        if report.options
        else (
            "Try again with looser rules:\n\n"
            "[bold]fo find ... --layover 60:240[/bold]\n"
            "[bold]fo find ... --allow-overnight[/bold]\n\n"
            "Saved searches stay available in [bold]fo history[/bold]."
        )
    )
    console.print(
        Panel(
            next_steps,
            border_style="bright_blue",
            box=box.ROUNDED,
        )
    )


def render_option_detail(report: SearchReport, option: TripOption, rank: int) -> None:
    facts = Table.grid(expand=True)
    facts.add_column()
    facts.add_column(justify="right")
    facts.add_row("Destination", f"{option.destination_city} ({option.destination_airport})")
    facts.add_row("Dates", f"{option.departure_date} -> {option.return_date}")
    facts.add_row("Price", format_money(option.total_price_usd))
    facts.add_row("Direct Baseline", format_money(option.direct_price_usd))
    facts.add_row("Savings vs Direct", format_money(option.savings_vs_direct_usd))
    facts.add_row("Trip Shape", "Nonstop both ways" if option.nonstop else f"{option.total_stops} total stops")
    facts.add_row(
        "Time vs Direct",
        f"Out {option.outbound_ratio_to_direct:.0%}  |  Return {option.return_ratio_to_direct:.0%}",
    )

    console.print(
        Panel(
            facts,
            title=f"[bold]Option {rank} from {report.search_id}[/bold]",
            subtitle=option.reason,
            border_style="bright_blue",
            box=box.ROUNDED,
        )
    )

    for label, segment in (("Outbound", option.outbound), ("Return", option.inbound)):
        segment_table = Table.grid(expand=True)
        segment_table.add_column()
        segment_table.add_column(justify="right")
        segment_table.add_row("Route", segment.route)
        segment_table.add_row("Duration", format_minutes(segment.duration_minutes))
        segment_table.add_row("Stops", str(segment.stops))
        segment_table.add_row("Departure", format_timestamp(segment.departure_time))
        segment_table.add_row("Arrival", format_timestamp(segment.arrival_time))
        segment_table.add_row(
            "Layovers",
            ", ".join(format_minutes(item) for item in segment.layovers_minutes) or "None",
        )
        segment_table.add_row("Flights", "  ".join(segment.flight_numbers))
        segment_table.add_row("Airlines", ", ".join(segment.airlines))
        console.print(
            Panel(
                segment_table,
                title=label,
                border_style="cyan",
                box=box.ROUNDED,
            )
        )


def render_compare(report: SearchReport, options: list[tuple[int, TripOption]]) -> None:
    table = Table(box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("Option", style="bold cyan")
    table.add_column("Place", style="bold white")
    table.add_column("Price", justify="right", style="green")
    table.add_column("Shape", justify="right")
    table.add_column("Out", justify="right")
    table.add_column("Back", justify="right")
    table.add_column("Why", style="cyan")
    for rank, option in options:
        table.add_row(
            str(rank),
            f"{option.destination_city} ({option.destination_airport})",
            format_money(option.total_price_usd),
            "Nonstop" if option.nonstop else f"{option.total_stops} stops",
            format_minutes(option.outbound.duration_minutes),
            format_minutes(option.inbound.duration_minutes),
            option.reason,
        )
    console.print(
        Panel(
            table,
            title=f"[bold]Compare from {report.search_id}[/bold]",
            border_style="bright_blue",
            box=box.ROUNDED,
        )
    )


def render_history(limit: int) -> None:
    reports = list_reports(limit=limit)
    if not reports:
        console.print("No saved searches yet.")
        return
    table = Table(box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("Search", style="bold cyan")
    table.add_column("When", style="white")
    table.add_column("Trip", style="white")
    table.add_column("Winner", style="bold white")
    table.add_column("Price", justify="right", style="green")
    for report in reports:
        winner = report.options[0] if report.options else None
        table.add_row(
            report.search_id,
            datetime.fromisoformat(report.created_at).strftime("%b %d %H:%M"),
            f"{report.request.origin} • {format_month_label(report.request.month)} • {report.request.stay_days} nights",
            f"{winner.destination_city} ({winner.destination_airport})" if winner else "No winner",
            format_money(winner.total_price_usd) if winner else "-",
        )
    console.print(table)


def resolve_rank(report: SearchReport, raw: str) -> tuple[int, TripOption]:
    if not report.options:
        raise ValueError("that saved search has no surviving options to inspect")
    rank = int(raw)
    if rank < 1 or rank > len(report.options):
        raise ValueError(f"rank must be between 1 and {len(report.options)}")
    return rank, report.options[rank - 1]


def print_demo() -> None:
    console.print(
        Panel(
            (
                "Try this:\n\n"
                "[bold]fo find --from EZE --prefer italy,spain --month 2026-07 --stay 21 "
                "--max-stops 1 --layover 60:180 --vs-direct 30[/bold]\n\n"
                "Then inspect the results with [bold]fo show 1[/bold] or "
                "[bold]fo compare 1 2 3[/bold]."
            ),
            title="Flight Optimizer",
            border_style="bright_blue",
            box=box.ROUNDED,
        )
    )


def run_find(args: argparse.Namespace) -> None:
    layover_min, layover_max = parse_layover_window(args.layover)
    request = FindRequest(
        origin=args.origin,
        prefer=parse_countries(args.prefer),
        month=args.month,
        stay_days=args.stay,
        cabin=args.cabin,
        max_stops=args.max_stops,
        layover_min_minutes=layover_min,
        layover_max_minutes=layover_max,
        direct_time_limit_pct=args.vs_direct,
        currency=args.currency,
        top_date_windows=args.top_windows,
        top_flights_per_window=args.top_flights,
        allow_overnight=args.allow_overnight,
    )
    with console.status("[bold cyan]Searching for good trip windows...[/bold cyan]", spinner="dots"):
        report = run_monthly_search(request)
        save_report(report)
    render_report(report)


def run_show(args: argparse.Namespace) -> None:
    if args.rank:
        report = load_report(args.selection)
        rank, option = resolve_rank(report, args.rank)
    else:
        report = load_report()
        rank, option = resolve_rank(report, args.selection)
    render_option_detail(report, option, rank)


def run_compare(args: argparse.Namespace) -> None:
    report = load_report()
    resolved = [resolve_rank(report, item) for item in args.selections]
    render_compare(report, resolved)


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "demo" or args.command is None:
            print_demo()
            return
        if args.command == "find":
            run_find(args)
            return
        if args.command == "show":
            run_show(args)
            return
        if args.command == "compare":
            run_compare(args)
            return
        if args.command == "history":
            render_history(args.limit)
            return
    except Exception as exc:
        console.print(Panel(str(exc), title="Search Failed", border_style="red"))
        raise SystemExit(1) from exc

    parser.error("unknown command")


if __name__ == "__main__":
    main()
