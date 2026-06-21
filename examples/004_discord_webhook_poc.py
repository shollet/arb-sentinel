"""POC: post a real arbitrage-candidate notification to Discord via the webhook.

Builds a sample clean candidate (the Arnaldi vs Collignon worked example from
docs/design/notification.md) and delivers it through the notification connector,
so you can confirm the embed renders correctly in your Discord channel.

This is a live POC, not a test. It posts a REAL message to a REAL Discord
channel and requires DISCORD_WEBHOOK_URL in .env. It is not part of the test
suite and never runs in CI -- the test suite mocks Discord with respx.

Run with: uv run python examples/004_discord_webhook_poc.py
"""

import os
from decimal import Decimal

from dotenv import load_dotenv

from arb_sentinel.arbitrage import (
    best_quote_per_outcome,
    find_arbitrage_opportunity,
    total_implied_probability,
)
from arb_sentinel.models import (
    Bookmaker,
    Event,
    Outcome,
    PhantomFilterResult,
    Quote,
)
from arb_sentinel.notification import send_notification, to_discord_payload

TOTAL_STAKE = Decimal("100")


def _sample_candidate() -> PhantomFilterResult:
    """The notification.md worked example as a candidate result.

    Arnaldi 2.04 @ Pinnacle + Collignon 2.04 @ Betfair -> ~2.00% clean margin.
    book_counts of 15 is illustrative for the POC (no real cleaning is run here).
    """
    arnaldi = Outcome(name="Matteo Arnaldi")
    collignon = Outcome(name="Raphael Collignon")
    event = Event(
        description="Matteo Arnaldi vs Raphael Collignon",
        outcomes=[arnaldi, collignon],
        quotes=[
            Quote(
                outcome=arnaldi,
                bookmaker=Bookmaker(name="Pinnacle"),
                decimal_odds=Decimal("2.04"),
            ),
            Quote(
                outcome=collignon,
                bookmaker=Bookmaker(name="Betfair"),
                decimal_odds=Decimal("2.04"),
            ),
        ],
    )

    opportunity = find_arbitrage_opportunity(event, TOTAL_STAKE)
    assert opportunity is not None, "Sample event should be an arbitrage."

    total_implied = total_implied_probability(best_quote_per_outcome(event).values())
    return PhantomFilterResult(
        classification="candidate",
        reason="Live webhook POC.",
        book_counts={arnaldi: 15, collignon: 15},
        raw_total_implied_probability=total_implied,
        clean_total_implied_probability=total_implied,
        opportunity=opportunity,
    )


def main() -> None:
    """Build the sample candidate and post it to Discord."""
    load_dotenv()
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("ERROR: DISCORD_WEBHOOK_URL not set. Copy .env.example to .env and add it.")
        return

    result = _sample_candidate()

    print("Payload to be sent:")
    print(to_discord_payload(result))
    print()

    if send_notification(result, webhook_url):
        print("Sent -- check your Discord channel.")
    else:
        print("Delivery failed (check the URL, network, or Discord status).")


if __name__ == "__main__":
    main()
