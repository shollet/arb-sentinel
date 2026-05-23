"""Pure functions implementing the arbitrage detection math.

The math is organized bottom-up in layers, from atomic operations to
composition. See docs/design/arbitrage-math.md for the complete
specification, invariants, and references.
"""

from collections.abc import Iterable
from decimal import Decimal

from arb_sentinel.models import Event, Outcome, Quote


def implied_probability(decimal_odds: Decimal) -> Decimal:
    """The probability a bookmaker implicitly assigns to an outcome.

    Derived as the inverse of decimal odds: a quote of 2.00 implies a 50%
    probability, a quote of 4.00 implies 25%.
    """
    return Decimal(1) / decimal_odds


def best_quote_per_outcome(event: Event) -> dict[Outcome, Quote]:
    """For each outcome in the event, return the quote with the highest odds.

    The highest decimal odds maximize the potential payout for backing that
    outcome. Picking the best price across bookmakers is what creates
    arbitrage opportunities.

    Raises ValueError if any outcome has no quote.
    """
    best: dict[Outcome, Quote] = {}
    for outcome in event.outcomes:
        quotes_for_outcome = [q for q in event.quotes if q.outcome == outcome]
        if not quotes_for_outcome:
            raise ValueError(f"No quote available for outcome: {outcome.name}")
        best[outcome] = max(quotes_for_outcome, key=lambda q: q.decimal_odds)
    return best


def total_implied_probability(quotes: Iterable[Quote]) -> Decimal:
    """Sum of implied probabilities across a collection of quotes.

    For a fair, frictionless market with all outcomes covered, this sum
    equals 1 exactly. Bookmakers build in a margin (the overround), so
    the sum on a single bookmaker is typically 1.02 to 1.10. When the
    sum across the best quotes from different bookmakers drops below 1,
    an arbitrage opportunity exists.
    """
    return sum(
        (implied_probability(quote.decimal_odds) for quote in quotes),
        start=Decimal(0),
    )
