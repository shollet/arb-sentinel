"""POC: end-to-end arbitrage detection on two tennis events.

Demonstrates how the math module finds an arbitrage opportunity when
cross-bookmaker quotes underprice an event, and returns None when the
event is fairly or unfavorably priced.

Run with: uv run python examples/002_arbitrage_detection_poc.py
"""

from decimal import Decimal

from arb_sentinel.arbitrage import find_arbitrage_opportunity
from arb_sentinel.models import Bookmaker, Event, Outcome, Quote


def _build_event(
    description: str,
    federer_quote: tuple[str, str],
    nadal_quote: tuple[str, str],
) -> Event:
    """Build a two-outcome event with one quote per outcome from a chosen bookmaker."""
    federer = Outcome(name="Federer")
    nadal = Outcome(name="Nadal")
    return Event(
        description=description,
        outcomes=[federer, nadal],
        quotes=[
            Quote(
                outcome=federer,
                bookmaker=Bookmaker(name=federer_quote[0]),
                decimal_odds=Decimal(federer_quote[1]),
            ),
            Quote(
                outcome=nadal,
                bookmaker=Bookmaker(name=nadal_quote[0]),
                decimal_odds=Decimal(nadal_quote[1]),
            ),
        ],
    )


def _print_opportunity_or_skip(event: Event, total_stake: Decimal) -> None:
    """Print the arbitrage opportunity for an event, or report that none exists."""
    opportunity = find_arbitrage_opportunity(event, total_stake)

    print(f"Event: {event.description}")

    if opportunity is None:
        print("  No arbitrage opportunity.")
        print()
        return

    print(f"  Arbitrage detected (profit ratio: {opportunity.guaranteed_profit_ratio * 100:.2f}%)")
    print(f"  Total stake: ${opportunity.total_stake}")
    print(f"  Guaranteed profit: ${opportunity.guaranteed_profit:.2f}")
    print("  Stake allocation:")
    for outcome, stake in opportunity.optimal_stakes.items():
        best = opportunity.best_quotes[outcome]
        print(f"    ${stake:.2f} on {outcome.name} @ {best.decimal_odds} ({best.bookmaker.name})")
    print()


def main() -> None:
    """Show arbitrage detection on a fair market vs an arbitrage market."""
    total_stake = Decimal("1000")

    fair_event = _build_event(
        description="Federer vs Nadal -- single bookmaker, normal market",
        federer_quote=("Pinnacle", "1.91"),
        nadal_quote=("Pinnacle", "1.91"),
    )
    _print_opportunity_or_skip(fair_event, total_stake)

    arbitrage_event = _build_event(
        description="Federer vs Nadal -- best cross-bookmaker quotes",
        federer_quote=("Pinnacle", "2.10"),
        nadal_quote=("Bet365", "2.00"),
    )
    _print_opportunity_or_skip(arbitrage_event, total_stake)


if __name__ == "__main__":
    main()
