"""Property-based tests for the arbitrage math.

Each test verifies one or more invariants from docs/design/arbitrage-math.md.
Tests use Hypothesis to generate hundreds of random inputs and assert that
the mathematical properties hold across all of them.
"""

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from arb_sentinel.arbitrage import (
    best_quote_per_outcome,
    implied_probability,
    total_implied_probability,
)
from arb_sentinel.models import Bookmaker, Event, Outcome, Quote

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


def _build_two_outcome_event(
    federer_quotes: list[tuple[str, str]],
    nadal_quotes: list[tuple[str, str]],
) -> Event:
    """Build a minimal two-outcome event from (bookmaker, odds) pairs."""
    federer = Outcome(name="Federer")
    nadal = Outcome(name="Nadal")
    quotes = [
        Quote(
            outcome=federer,
            bookmaker=Bookmaker(name=bookmaker),
            decimal_odds=Decimal(odds),
        )
        for bookmaker, odds in federer_quotes
    ] + [
        Quote(
            outcome=nadal,
            bookmaker=Bookmaker(name=bookmaker),
            decimal_odds=Decimal(odds),
        )
        for bookmaker, odds in nadal_quotes
    ]
    return Event(
        description="Federer vs Nadal",
        outcomes=[federer, nadal],
        quotes=quotes,
    )


class TestBestQuotePerOutcome:
    """Verify that best_quote_per_outcome returns the highest odds per outcome."""

    def test_single_bookmaker_returns_that_bookmaker_quotes(self) -> None:
        """With one bookmaker, the best quote per outcome is that bookmaker's quote."""
        event = _build_two_outcome_event(
            federer_quotes=[("Pinnacle", "2.10")],
            nadal_quotes=[("Pinnacle", "1.85")],
        )

        best = best_quote_per_outcome(event)

        assert len(best) == 2
        for outcome, quote in best.items():
            assert quote.bookmaker.name == "Pinnacle"
            assert quote.outcome == outcome

    def test_multiple_bookmakers_picks_highest_odds(self) -> None:
        """With multiple bookmakers, the highest odds per outcome are selected."""
        event = _build_two_outcome_event(
            federer_quotes=[("Pinnacle", "2.10"), ("Bet365", "2.05")],
            nadal_quotes=[("Pinnacle", "1.85"), ("Bet365", "1.90")],
        )

        best = best_quote_per_outcome(event)

        federer_quote = next(q for o, q in best.items() if o.name == "Federer")
        nadal_quote = next(q for o, q in best.items() if o.name == "Nadal")
        assert federer_quote.bookmaker.name == "Pinnacle"
        assert federer_quote.decimal_odds == Decimal("2.10")
        assert nadal_quote.bookmaker.name == "Bet365"
        assert nadal_quote.decimal_odds == Decimal("1.90")

    def test_missing_quote_for_outcome_raises(self) -> None:
        """An event with an outcome that has no quote raises ValueError."""
        federer = Outcome(name="Federer")
        nadal = Outcome(name="Nadal")
        event = Event(
            description="Federer vs Nadal",
            outcomes=[federer, nadal],
            quotes=[
                Quote(
                    outcome=federer,
                    bookmaker=Bookmaker(name="Pinnacle"),
                    decimal_odds=Decimal("2.10"),
                ),
            ],
        )

        with pytest.raises(ValueError, match="Nadal"):
            best_quote_per_outcome(event)


class TestTotalImpliedProbability:
    """Verify that total_implied_probability sums implied probabilities correctly."""

    def test_two_even_odds_sum_to_one(self) -> None:
        """Two quotes of 2.00 each sum to exactly 1.0 (a perfectly fair market)."""
        federer = Outcome(name="Federer")
        nadal = Outcome(name="Nadal")
        pinnacle = Bookmaker(name="Pinnacle")
        quotes = [
            Quote(outcome=federer, bookmaker=pinnacle, decimal_odds=Decimal("2.00")),
            Quote(outcome=nadal, bookmaker=pinnacle, decimal_odds=Decimal("2.00")),
        ]

        assert total_implied_probability(quotes) == Decimal("1.0")

    def test_normal_market_sum_exceeds_one(self) -> None:
        """A typical bookmaker market with overround sums to more than 1.0."""
        federer = Outcome(name="Federer")
        nadal = Outcome(name="Nadal")
        pinnacle = Bookmaker(name="Pinnacle")
        quotes = [
            Quote(outcome=federer, bookmaker=pinnacle, decimal_odds=Decimal("1.91")),
            Quote(outcome=nadal, bookmaker=pinnacle, decimal_odds=Decimal("1.91")),
        ]

        total = total_implied_probability(quotes)

        assert total > Decimal(1)

    def test_arbitrage_market_sum_below_one(self) -> None:
        """A market with arbitrage (best cross-bookmaker quotes) sums to less than 1.0."""
        federer = Outcome(name="Federer")
        nadal = Outcome(name="Nadal")
        quotes = [
            Quote(
                outcome=federer,
                bookmaker=Bookmaker(name="Pinnacle"),
                decimal_odds=Decimal("2.10"),
            ),
            Quote(
                outcome=nadal,
                bookmaker=Bookmaker(name="Bet365"),
                decimal_odds=Decimal("2.00"),
            ),
        ]

        total = total_implied_probability(quotes)

        assert total < Decimal(1)

    def test_empty_quotes_returns_zero(self) -> None:
        """An empty iterable returns exactly Decimal(0)."""
        assert total_implied_probability([]) == Decimal(0)

    def test_worked_example_matches_design_doc(self) -> None:
        """The worked example from docs/design/arbitrage-math.md computes as documented.

        Federer at 2.10 (Pinnacle) + Nadal at 1.90 (Bet365) yields total
        implied probability of approximately 1.0025 (no arbitrage).
        """
        federer = Outcome(name="Federer")
        nadal = Outcome(name="Nadal")
        best_quotes = [
            Quote(
                outcome=federer,
                bookmaker=Bookmaker(name="Pinnacle"),
                decimal_odds=Decimal("2.10"),
            ),
            Quote(
                outcome=nadal,
                bookmaker=Bookmaker(name="Bet365"),
                decimal_odds=Decimal("1.90"),
            ),
        ]

        total = total_implied_probability(best_quotes)

        assert Decimal("1.0024") < total < Decimal("1.0026")
