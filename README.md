# arb-sentinel

A sport-agnostic arbitrage detection system. Built incrementally. Paper-traded.

## Status

🚧 **Iteration 0 — in progress.**

The project is being built one validated hypothesis at a time. The current iteration
is the simplest possible: detect arbitrage opportunities on tennis matches manually,
with no automation, no persistence, and no UI. The goal is to verify that real
opportunities exist and can be detected reliably before investing in any infrastructure.

See [ROADMAP.md](./ROADMAP.md) for the full scope, principles, and decision log.

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
