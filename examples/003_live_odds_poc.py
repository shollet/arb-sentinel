"""POC: end-to-end arbitrage detection on live tennis odds.

Hits The Odds API for real tennis events, runs arbitrage detection on
each, and prints any opportunities found.

This is a live POC, not a test. Each execution consumes one request
from the free-tier monthly quota (500 requests/month). It is not part
of the test suite and never runs in CI -- it exists to validate the
end-to-end pipeline with real data.

Run with: uv run python examples/003_live_odds_poc.py
"""

import os
from decimal import Decimal

from dotenv import load_dotenv

from arb_sentinel.arbitrage import find_arbitrage_opportunity
from arb_sentinel.odds_api import fetch_events

SPORT_KEY = "tennis_atp_french_open"
TOTAL_STAKE = Decimal("1000")


def main() -> None:
    """Fetch live events, detect arbitrage, print results."""
    load_dotenv()
    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("ERROR: ODDS_API_KEY not set. Copy .env.example to .env and add your key.")
        return

    print(f"Fetching live events for {SPORT_KEY}...")
    events = fetch_events(sport_key=SPORT_KEY, api_key=api_key)
    print(f"Found {len(events)} events.")
    print()

    if not events:
        print("No events available right now. The tournament may be off-season.")
        return

    opportunities_found = 0
    for event in events:
        opportunity = find_arbitrage_opportunity(event, total_stake=TOTAL_STAKE)
        if opportunity is None:
            continue

        opportunities_found += 1
        print(f"ARBITRAGE: {opportunity.event.description}")
        print(f"  Profit ratio: {opportunity.guaranteed_profit_ratio * 100:.2f}%")
        print(
            f"  Guaranteed profit on ${opportunity.total_stake}: "
            f"${opportunity.guaranteed_profit:.2f}"
        )
        print("  Stake allocation:")
        for outcome, stake in opportunity.optimal_stakes.items():
            best = opportunity.best_quotes[outcome]
            print(
                f"    ${stake:.2f} on {outcome.name} @ {best.decimal_odds} ({best.bookmaker.name})"
            )
        print()

    plural = "y" if opportunities_found == 1 else "ies"
    print(
        f"Summary: {opportunities_found} arbitrage opportunit{plural} "
        f"found out of {len(events)} events."
    )


if __name__ == "__main__":
    main()
