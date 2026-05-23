"""POC: validate the domain modeling against a realistic Odds API response.

This script demonstrates that the Bookmaker/Outcome/Quote/Event models can
faithfully represent a realistic sports betting event with multiple
bookmakers offering quotes on the same outcomes.

Run with: uv run python examples/001_modeling_poc.py
"""

from decimal import Decimal

from arb_sentinel.models import Bookmaker, Event, Outcome, Quote


def main() -> None:
    """Build a realistic two-bookmaker tennis event and inspect it."""

    federer = Outcome(name="Federer")
    nadal = Outcome(name="Nadal")

    pinnacle = Bookmaker(name="Pinnacle")
    bet365 = Bookmaker(name="Bet365")

    quotes = [
        Quote(outcome=federer, bookmaker=pinnacle, decimal_odds=Decimal("2.10")),
        Quote(outcome=nadal, bookmaker=pinnacle, decimal_odds=Decimal("1.85")),
        Quote(outcome=federer, bookmaker=bet365, decimal_odds=Decimal("2.05")),
        Quote(outcome=nadal, bookmaker=bet365, decimal_odds=Decimal("1.90")),
    ]

    event = Event(
        description="ATP - Federer vs Nadal - Match Winner",
        outcomes=[federer, nadal],
        quotes=quotes,
    )

    print(f"Event: {event.description}")
    print(f"Outcomes: {[o.name for o in event.outcomes]}")
    print(f"Number of quotes: {len(event.quotes)}")
    print()
    print("All quotes:")
    for quote in event.quotes:
        print(f"  {quote.outcome.name:10s} @ {quote.decimal_odds} from {quote.bookmaker.name}")

    print()
    print("Best odds per outcome:")
    for outcome in event.outcomes:
        outcome_quotes = [q for q in event.quotes if q.outcome == outcome]
        best = max(outcome_quotes, key=lambda q: q.decimal_odds)
        print(f"  {outcome.name}: {best.decimal_odds} @ {best.bookmaker.name}")


if __name__ == "__main__":
    main()
