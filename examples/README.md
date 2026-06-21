# Examples

Executable scripts that explore design decisions and demonstrate how to use
the library. Each script can be run with `uv run python examples/<file>.py`.

These are **not tests**. Tests enforce invariants and run in CI; examples
illustrate intent and may evolve as the library evolves.

## Scripts

- **`001_modeling_poc.py`** — validates that the domain models can faithfully
  represent a realistic two-bookmaker tennis event. Run before committing
  to the model structure in Iteration 0.

- **`002_arbitrage_detection_poc.py`** — demonstrates end-to-end arbitrage
  detection: builds two tennis events (one fair, one with arbitrage) and
  shows how `find_arbitrage_opportunity` returns either an
  `ArbitrageOpportunity` with stakes and profit, or `None`.

- **`003_live_odds_poc.py`** — live check against The Odds API: fetches real
  tennis events, runs arbitrage detection, and prints any opportunities.
  Consumes 1 request from the free-tier quota. Not a test; never runs in CI.

- **`004_discord_webhook_poc.py`** — live check of the Discord notification
  connector: posts a sample clean-candidate embed to your channel via the
  webhook. Requires `DISCORD_WEBHOOK_URL` in `.env`. Not a test; never runs in CI.
