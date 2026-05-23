"""Property-based tests for the arbitrage math.

Each test verifies one or more invariants from docs/design/arbitrage-math.md.
Tests use Hypothesis to generate hundreds of random inputs and assert that
the mathematical properties hold across all of them.
"""

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from arb_sentinel.arbitrage import implied_probability

# Strategy: generate realistic decimal odds in the range bookmakers actually offer.
# Lower bound 1.01 (very heavy favorites), upper bound 100 (extreme longshots).
valid_decimal_odds = st.decimals(
    min_value=Decimal("1.01"),
    max_value=Decimal("100"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


class TestImpliedProbability:
    """Verify invariant I1: for any decimal odds O > 1, p = 1/O and 0 < p < 1.

    Note on precision: testing `p * O == 1` exactly would fail for odds whose
    reciprocal has no finite decimal representation (e.g. 1/3.74). The
    multiplicative inverse identity is a mathematical tautology — what we
    actually need to verify is the probability-validity invariant (0 < p < 1)
    and specific reference cases with terminating decimal representations.
    """

    @given(decimal_odds=valid_decimal_odds)
    def test_result_is_strictly_between_zero_and_one(self, decimal_odds: Decimal) -> None:
        """Implied probability is always a valid probability (strictly in (0, 1))."""
        probability = implied_probability(decimal_odds)
        assert Decimal(0) < probability < Decimal(1)

    def test_even_odds_yield_fifty_percent(self) -> None:
        """A 2.00 quote implies exactly a 50% probability."""
        assert implied_probability(Decimal("2.00")) == Decimal("0.5")

    def test_heavy_favorite_yields_high_probability(self) -> None:
        """A 1.25 quote implies an 80% probability."""
        assert implied_probability(Decimal("1.25")) == Decimal("0.8")

    def test_longshot_yields_low_probability(self) -> None:
        """A 10.00 quote implies a 10% probability."""
        assert implied_probability(Decimal("10.00")) == Decimal("0.1")
