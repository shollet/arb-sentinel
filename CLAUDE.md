# arb-sentinel — Claude Code guide

This file tells Claude Code how to work in this repo. It is the operating contract.
The *why* lives in `ROADMAP.md` (vision, decision log) and `docs/design/` (per-subsystem
specs). Read those when a task touches them — do not duplicate them here.

## What this project is

A sport-agnostic sports-arbitrage detection system, built incrementally, **paper-trade
only** (it observes and notifies, never places bets). Tennis / h2h for now. Public repo,
career portfolio. See `ROADMAP.md` for the full picture.

## Three principles (govern every change)

1. **Validate before you build** — each iteration tests one hypothesis.
2. **Earn complexity** — no tool, dependency, or abstraction without a documented reason
   in the ROADMAP decision log.
3. **Ship and document** — working code + a decision log entry + an updated ROADMAP.

## Non-negotiables

- **Decimal, never float** for any odds, probability, stake, or money value.
  Property-based tests use Decimal tolerance, not exact float equality.
- **Pydantic v2 models are `frozen`** and carry no business logic — they are validated,
  immutable value objects.
- **Domain logic = pure functions** (no I/O, no side effects), organized in layers. All
  I/O stays in the integration layer (`odds_api.py`). Keep this separation intact.
- **Spec-first.** For any non-trivial business logic, the matching doc under
  `docs/design/` is the contract. Read it before writing code. If the code must diverge,
  update the spec first and note it in the ROADMAP decision log.
- **English everywhere** — code, comments, docs, commits.
- **Comment only the non-obvious** — the "why", invariants, real complexity. No
  step-by-step narration comments.

## How we work

- **Plan before editing.** Propose the approach and wait for approval before changing
  files. Keep changes minimal and scoped to the task at hand.
- **Read the relevant spec first.** Before implementing, read the matching design doc:
  `phantom-filtering.md` for the filter, `odds-api-integration.md` for API/mapping,
  `arbitrage-math.md` for the math. Before tooling decisions, read the ADRs in
  `docs/adr/`.
- **One logical change at a time**, grouped into a clean commit.

## Verify before every commit

Run the full sequence and get it fully green before committing:

```
uv run ruff check . && uv run ruff format --check . && uv run pytest
```

If `ruff format --check` reports formatting, run `uv run ruff format .` then re-run
`uv run ruff check .`.

**You (Claude Code) may fix ruff issues yourself** as part of this loop — both formatting
and `ruff check` violations, including small, behavior-preserving code changes needed to
satisfy a rule (not only `--fix`). **But** if satisfying the linter would require changing
behavior or business logic, stop and ask instead of silently altering logic — a lint
warning can be pointing at a real bug.

## Commits

Conventional Commits, with a body that explains the **why**, not just the what. Group
related changes; build green before committing.

Example:

```
feat(odds-api): discover active tennis tournaments dynamically

Replace the hardcoded sport_key with a /sports lookup that filters active
tennis_* keys and selects one via a configurable priority list. /sports does
not count against the API quota, so discovery is free; this removes manual
babysitting of the tournament config and lets the poller follow the season.
See ROADMAP decision log 2026-06-06.
```

## Tests

- **Property-based (Hypothesis)** for math and invariants. Assert the invariant
  (e.g. `0 < p < 1`, `clean_T >= raw_T`), not brittle exact equalities.
- **Fixture + respx mocking** for all I/O. Never call the real Odds API in tests — it
  burns quota. Live checks live in `examples/` and never run in CI.
- New behavior ships with tests. CI (lint + format + tests) must stay green.

## Project layout

- `src/arb_sentinel/` — `models.py` (frozen domain types), `arbitrage.py` (pure math,
  layered), `odds_api.py` (integration / I/O), `__init__.py` (entry point, orchestration).
- `tests/` — pytest; `tests/fixtures/` holds JSON for offline API mocking; no
  `__init__.py` in `tests/`.
- `docs/design/` — per-subsystem specs (the contracts). `docs/adr/` — architecture
  decision records.
- `examples/` — runnable POCs and live checks, separate from the test suite.
- Managed by `uv`; lint/format with `ruff`; Python 3.12.

## Current iteration — IT1

Moving from manual, on-demand detection to **continuous, windowed background observation**
of one dynamically-selected tennis tournament, with Discord webhook alerts for clean
candidates and a JSONL journal. **Zero new Python dependencies** — the webhook is an
`httpx` POST, the journal is stdlib `json` + a file, scheduling is OS cron. The full scope
and Definition of Done are in `ROADMAP.md` (Current Iteration — Iteration 1); the filter
design is in `docs/design/phantom-filtering.md`.

Hypothesis under test: do real, clean arbitrages surface often enough under continuous
observation to justify continuing — and can we notify automatically when one appears?

IT1 is observation + notification only. Out of scope: **no execution, no database, no AI
agents, no Docker/CD, pre-match only** (in-play stays filtered at the mapper).
