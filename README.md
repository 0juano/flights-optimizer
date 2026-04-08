# flights-optimizer

`flights-optimizer` is a bounded search-and-score engine for flight options.

The goal is simple:

```text
trip request
   ->
baseline route
   ->
try smarter variations
   ->
reject bad options
   ->
rank what is left by real travel cost
   ->
show a short sane shortlist
```

This repo starts with the part that matters most for trust: the judgment layer.
It does not try to be a full booking product on day one.

## Why this exists

Flight tools usually optimize for sticker price.
People actually care about a mix of price, duration, stop count, airport changes,
self-transfers, and whether a route still feels worth it after the savings.

This project treats those tradeoffs as first-class inputs.

## Current scope

The initial public version includes:

- a small flight option model
- a scoring system for "real" trip cost
- rejection rules for obviously bad options
- a shortlist builder that picks the best-value, cheapest-worth-it, and easiest reasonable routes
- a first live one-way search flow powered by `fli`
- tests and a runnable demo

## Planned shape

The intended architecture is:

```text
flight data (for example fli)
   +
search loop
   +
hard filters
   +
scoring + reranking
   =
flight optimizer
```

Near-term roadmap:

1. Plug in a real flight data source.
2. Generate route/date/airport variations from a user request.
3. Run a bounded search loop instead of a one-shot query.
4. Keep the final ranking deterministic and explainable.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
python -m flights_optimizer
python -m flights_optimizer JFK LAX 2026-05-20 --flex-days 1
```

## Demo output

The demo compares a baseline itinerary against a handful of alternatives and
prints:

- which routes are rejected
- each option's adjusted cost after penalties
- the short final shortlist

For live searches, the CLI will:

- get the baseline flight for the requested route and date
- search nearby dates and any optional alternate airports you allow
- score the returned flights in the same currency Google returns
- print a shortlist plus the rejected options

Example:

```bash
python -m flights_optimizer JFK LAX 2026-05-20 \
  --cabin economy \
  --flex-days 1 \
  --alt-origin EWR \
  --alt-destination BUR
```

## Design principles

- Bounded, not open-ended.
- Cheap search most of the time, stronger judgment only when needed.
- Hard rules for obviously bad routes.
- Clear explanations over "AI magic."

## Inspiration

- [`punitarani/fli`](https://github.com/punitarani/fli)
- [`karpathy/autoresearch`](https://github.com/karpathy/autoresearch)

The repo borrows the search-loop mindset, but applies it to trip options rather
than self-modifying code.
