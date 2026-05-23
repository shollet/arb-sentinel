"""Pure functions implementing the arbitrage detection math.

The math is organized bottom-up in layers, from atomic operations to
composition. See docs/design/arbitrage-math.md for the complete
specification, invariants, and references.
"""

from decimal import Decimal


def implied_probability(decimal_odds: Decimal) -> Decimal:
    """The probability a bookmaker implicitly assigns to an outcome.

    Derived as the inverse of decimal odds: a quote of 2.00 implies a 50%
    probability, a quote of 4.00 implies 25%.
    """
    return Decimal(1) / decimal_odds
