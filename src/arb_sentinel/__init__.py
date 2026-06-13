"""arb-sentinel: a sport-agnostic arbitrage detection system."""

import os
from decimal import Decimal

from dotenv import load_dotenv

from arb_sentinel.arbitrage import find_arbitrage_opportunity
from arb_sentinel.odds_api import (
    GRAND_SLAM_PRIORITY,
    fetch_active_sports,
    fetch_events,
    select_tournament,
)

DEFAULT_TOTAL_STAKE = Decimal("1000")


def main() -> None:
    """Fetch live tennis odds and print any arbitrage opportunities to the console.

    The entry point for `python -m arb_sentinel`. Loads the API key from
    a local .env file, discovers the active tennis tournament, fetches its
    events, runs arbitrage detection on each, and prints a summary.
    """
    load_dotenv()
    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("ERROR: ODDS_API_KEY not set. Copy .env.example to .env and add your key.")
        return

    sports = fetch_active_sports(api_key=api_key)
    sport_key = select_tournament(sports, GRAND_SLAM_PRIORITY)
    if sport_key is None:
        print("No active tennis tournament found. Skipping poll (0 credits).")
        return

    print(f"Fetching events for {sport_key}...")
    events = fetch_events(sport_key=sport_key, api_key=api_key)
    print(f"Found {len(events)} events to analyze.")
    print()

    opportunities_found = 0
    for event in events:
        opportunity = find_arbitrage_opportunity(event, total_stake=DEFAULT_TOTAL_STAKE)
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
