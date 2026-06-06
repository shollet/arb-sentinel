# arb-sentinel

A sport-agnostic arbitrage detection system. Built incrementally. Paper-traded.

## Status

**Iteration 0 — complete. Iteration 1 — in progress (scoping).**

The project is built one validated hypothesis at a time. Iteration 0 delivered the
detection core — arbitrage math, domain models, and The Odds API integration — fully
covered by property-based and integration tests. What it validated is the *mechanics*:
the pipeline reliably computes arbitrage from cross-bookmaker quotes. What stays open is
the *empirical* question — whether real, clean arbitrages actually surface — because
running detection manually and on demand samples too little of a continuously-moving
market to catch one.

Iteration 1 addresses exactly that: continuous background observation with automatic
notification when an opportunity appears.

See [ROADMAP.md](./ROADMAP.md) for the full scope, principles, decision log, and the
Iteration 0 validation verdict.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) (the project manager). Install it with
`brew install uv` on macOS.

```bash
git clone git@github.com:shollet/arb-sentinel.git
cd arb-sentinel
uv sync
uv run arb-sentinel
```

`uv sync` installs Python 3.12 and all dependencies in a project-local `.venv/`.
Nothing is installed globally.

## Development

Lint and format:

```bash
uv run ruff check .
uv run ruff format .
```

Run tests:

```bash
uv run pytest
```

## Roadmap

The full plan, current iteration scope, and architectural decisions are documented
in [ROADMAP.md](./ROADMAP.md).

## License

[MIT](./LICENSE) © 2026 Shayan Hollet
