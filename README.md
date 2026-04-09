# flights-optimizer

`flights-optimizer` is a terminal-first search and ranking tool for flight options.

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

The current version includes:

- a month-first search flow powered by `fli`
- a polished `fo` terminal command
- round-trip scanning for destination groups like Italy, Spain, and France
- hard filters for stops, layovers, airport changes, overnights, and time versus direct
- automatic price normalization to USD
- saved search history, result drill-down, and comparison views
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

1. Expand destination presets and airport families.
2. Add date-range and themed search templates.
3. Improve scoring so the shortlist balances price, trip shape, and simplicity.
4. Keep the final ranking deterministic and explainable.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
fo demo
fo find --from EZE --prefer italy,spain --month 2026-07 --stay 21
```

## CLI flow

The terminal interface is built around four commands:

- `fo find`
  Scan a month, fetch real itineraries, reject bad fits, and show the shortlist.
- `fo show`
  Open one saved result and see the full trip details.
- `fo compare`
  Put a few saved results side by side.
- `fo history`
  See recent searches and their winners.

The main command looks like this:

```bash
fo find \
  --from EZE \
  --prefer italy,spain \
  --month 2026-07 \
  --stay 21 \
  --max-stops 1 \
  --layover 60:180 \
  --vs-direct 30
```

That produces a report with:

- the trip rules at the top
- a scan summary for each airport that was checked
- the best few options in USD
- a clear winner panel
- rejected routes with the reason they failed
- next-step commands for digging deeper

Example follow-up commands:

```bash
fo show 1
fo compare 1 2 3
fo history
```

## Design principles

- Bounded, not open-ended.
- Search dates first, then inspect real itineraries.
- Hard rules for obviously bad routes.
- Clear explanations over "AI magic."
- A terminal experience that reads like a decision brief, not a raw dump.

## Inspiration

- [`punitarani/fli`](https://github.com/punitarani/fli)
- [`karpathy/autoresearch`](https://github.com/karpathy/autoresearch)

The repo borrows the search-loop mindset, but applies it to trip options rather
than self-modifying code.
