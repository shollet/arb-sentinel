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

    Returns Decimal(0) for an empty collection — the natural identity for
    sums. Callers that require non-empty inputs should validate upstream.
    """
    return sum(
        (implied_probability(quote.decimal_odds) for quote in quotes),
        start=Decimal(0),
    )


def is_arbitrage_opportunity(event: Event) -> bool:
    """Whether this event presents an arbitrage opportunity.

    An arbitrage exists when, picking the best quote available for each
    outcome across all bookmakers, the sum of implied probabilities falls
    strictly below 1.
    """
    best = best_quote_per_outcome(event)
    return total_implied_probability(best.values()) < Decimal(1)


def bookmaker_overround(event: Event) -> Decimal:
    """The margin built into the event's best quotes, as a decimal.

    The overround is the amount by which the sum of implied probabilities
    exceeds 1. A typical single-bookmaker market has an overround of 0.02
    to 0.10. A negative overround indicates an arbitrage opportunity.
    """
    best = best_quote_per_outcome(event)
    return total_implied_probability(best.values()) - Decimal(1)


def guaranteed_profit_ratio(event: Event) -> Decimal:
    """The fraction of total stake returned as profit, guaranteed regardless of outcome.

    For an arbitrage opportunity, this is what a bettor earns above their
    capital. A ratio of 0.0504 means a $1000 stake yields $50.40 of
    guaranteed profit. The ratio is positive only when arbitrage exists.
    """
    best = best_quote_per_outcome(event)
    total = total_implied_probability(best.values())
    return Decimal(1) / total - Decimal(1)


def optimal_stakes(event: Event, total_stake: Decimal) -> dict[Outcome, Decimal]:
    """The stake allocation per outcome that guarantees equal payout regardless of outcome.

    Returns the distribution of capital across outcomes such that whichever
    outcome wins, the bettor receives the same payout. The formula
    proportionally weights each outcome by its implied probability divided
    by the total implied probability.

    Raises ValueError if the event is not an arbitrage opportunity.
    """
    if not is_arbitrage_opportunity(event):
        raise ValueError("Cannot compute optimal stakes: event is not an arbitrage opportunity.")

    best = best_quote_per_outcome(event)
    total = total_implied_probability(best.values())
    return {
        outcome: total_stake * implied_probability(quote.decimal_odds) / total
        for outcome, quote in best.items()
    }
