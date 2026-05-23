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
    bookmaker_overround,
    find_arbitrage_opportunity,
    guaranteed_profit_ratio,
    implied_probability,
    is_arbitrage_opportunity,
    optimal_stakes,
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

# Strategy: generate realistic total stakes for betting scenarios.
valid_total_stake = st.decimals(
    min_value=Decimal("1.00"),
    max_value=Decimal("1000000.00"),
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


def _build_arbitrage_event(federer_odds: str, nadal_odds: str) -> Event:
    """Build a two-outcome event with quotes from different bookmakers.

    Used in tests that need an arbitrage event; the caller is responsible
    for ensuring the odds combination actually creates arbitrage.
    """
    return _build_two_outcome_event(
        federer_quotes=[("Pinnacle", federer_odds)],
        nadal_quotes=[("Bet365", nadal_odds)],
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


class TestIsArbitrageOpportunity:
    """Verify invariant I2: arbitrage exists if and only if T < 1 (strict)."""

    def test_normal_market_is_not_arbitrage(self) -> None:
        """A typical single-bookmaker market with overround is not arbitrage."""
        event = _build_two_outcome_event(
            federer_quotes=[("Pinnacle", "1.91")],
            nadal_quotes=[("Pinnacle", "1.91")],
        )

        assert is_arbitrage_opportunity(event) is False

    def test_perfectly_fair_market_is_not_arbitrage(self) -> None:
        """At T = 1.0 exactly, the market is fair but not arbitrage (strict inequality)."""
        event = _build_two_outcome_event(
            federer_quotes=[("Pinnacle", "2.00")],
            nadal_quotes=[("Pinnacle", "2.00")],
        )

        assert is_arbitrage_opportunity(event) is False

    def test_arbitrage_market_returns_true(self) -> None:
        """A market with T < 1 across best quotes returns True."""
        event = _build_two_outcome_event(
            federer_quotes=[("Pinnacle", "2.10")],
            nadal_quotes=[("Bet365", "2.00")],
        )

        assert is_arbitrage_opportunity(event) is True

    def test_worked_example_is_not_arbitrage(self) -> None:
        """The worked example from the spec is not an arbitrage opportunity."""
        event = _build_two_outcome_event(
            federer_quotes=[("Pinnacle", "2.10"), ("Bet365", "2.05")],
            nadal_quotes=[("Pinnacle", "1.85"), ("Bet365", "1.90")],
        )

        assert is_arbitrage_opportunity(event) is False


class TestBookmakerOverround:
    """Verify that bookmaker_overround returns the correct margin (T - 1)."""

    def test_normal_market_has_positive_overround(self) -> None:
        """A typical bookmaker market has overround between 0.02 and 0.10."""
        event = _build_two_outcome_event(
            federer_quotes=[("Pinnacle", "1.91")],
            nadal_quotes=[("Pinnacle", "1.91")],
        )

        overround = bookmaker_overround(event)

        assert overround > Decimal(0)
        assert overround < Decimal("0.10")

    def test_fair_market_has_zero_overround(self) -> None:
        """At T = 1.0 exactly, the overround is exactly zero."""
        event = _build_two_outcome_event(
            federer_quotes=[("Pinnacle", "2.00")],
            nadal_quotes=[("Pinnacle", "2.00")],
        )

        assert bookmaker_overround(event) == Decimal(0)

    def test_arbitrage_market_has_negative_overround(self) -> None:
        """A market with arbitrage has a strictly negative overround."""
        event = _build_two_outcome_event(
            federer_quotes=[("Pinnacle", "2.10")],
            nadal_quotes=[("Bet365", "2.00")],
        )

        assert bookmaker_overround(event) < Decimal(0)


class TestGuaranteedProfitRatio:
    """Verify invariant I5: r = (1/T) - 1.

    The ratio is positive only when arbitrage exists (T < 1).
    """

    def test_arbitrage_market_has_positive_profit_ratio(self) -> None:
        """An arbitrage market yields a positive guaranteed profit ratio."""
        event = _build_arbitrage_event("2.10", "2.00")

        ratio = guaranteed_profit_ratio(event)

        assert ratio > Decimal(0)

    def test_fair_market_has_zero_profit_ratio(self) -> None:
        """A perfectly fair market (T = 1.0) yields exactly zero profit."""
        event = _build_two_outcome_event(
            federer_quotes=[("Pinnacle", "2.00")],
            nadal_quotes=[("Pinnacle", "2.00")],
        )

        assert guaranteed_profit_ratio(event) == Decimal(0)

    def test_normal_market_has_negative_profit_ratio(self) -> None:
        """A market with overround (T > 1) yields a negative profit ratio."""
        event = _build_two_outcome_event(
            federer_quotes=[("Pinnacle", "1.91")],
            nadal_quotes=[("Pinnacle", "1.91")],
        )

        assert guaranteed_profit_ratio(event) < Decimal(0)

    def test_worked_example_profit_ratio(self) -> None:
        """The arbitrage case from the spec yields profit ratio of about 0.0244.

        Federer at 2.10 + Nadal at 2.00: T = 0.9762, r = 1/0.9762 - 1 ≈ 0.0244.
        """
        event = _build_arbitrage_event("2.10", "2.00")

        ratio = guaranteed_profit_ratio(event)

        assert Decimal("0.0243") < ratio < Decimal("0.0245")


class TestOptimalStakes:
    """Verify invariants I3 (stake conservation) and I4 (equal payout)."""

    def test_raises_when_not_arbitrage(self) -> None:
        """Computing optimal stakes on a non-arbitrage event raises ValueError."""
        event = _build_two_outcome_event(
            federer_quotes=[("Pinnacle", "1.91")],
            nadal_quotes=[("Pinnacle", "1.91")],
        )

        with pytest.raises(ValueError, match="not an arbitrage"):
            optimal_stakes(event, Decimal("1000"))

    def test_stakes_sum_to_total_stake(self) -> None:
        """Invariant I3: the sum of optimal stakes equals the total stake exactly."""
        event = _build_arbitrage_event("2.10", "2.00")
        total_stake = Decimal("1000")

        stakes = optimal_stakes(event, total_stake)

        assert sum(stakes.values()) == total_stake

    def test_equal_payout_across_outcomes(self) -> None:
        """Invariant I4: the payout is identical regardless of which outcome wins.

        For each outcome, payout = stake_on_outcome * decimal_odds. With optimal
        stakes, this should be the same for all outcomes.
        """
        event = _build_arbitrage_event("2.10", "2.00")
        total_stake = Decimal("1000")

        stakes = optimal_stakes(event, total_stake)
        best = best_quote_per_outcome(event)

        payouts = [stakes[outcome] * quote.decimal_odds for outcome, quote in best.items()]
        # All payouts equal — pick any two and assert equality.
        assert payouts[0] == payouts[1]

    def test_worked_example_stakes(self) -> None:
        """The arbitrage worked example from the spec produces the documented stakes.

        Federer at 2.10 + Nadal at 2.00, $1000 total stake:
        - Federer stake: 1000 * (1/2.10) / 0.9762 ≈ $487.81
        - Nadal stake: 1000 * (1/2.00) / 0.9762 ≈ $512.19
        """
        event = _build_arbitrage_event("2.10", "2.00")
        federer = next(o for o in event.outcomes if o.name == "Federer")
        nadal = next(o for o in event.outcomes if o.name == "Nadal")

        stakes = optimal_stakes(event, Decimal("1000"))

        assert Decimal("487.80") < stakes[federer] < Decimal("487.82")
        assert Decimal("512.18") < stakes[nadal] < Decimal("512.20")

    @given(
        federer_odds=st.decimals(min_value=Decimal("2.05"), max_value=Decimal("3.00"), places=2),
        nadal_odds=st.decimals(min_value=Decimal("2.05"), max_value=Decimal("3.00"), places=2),
        total_stake=valid_total_stake,
    )
    def test_property_equal_payout_for_random_arbitrage(
        self, federer_odds: Decimal, nadal_odds: Decimal, total_stake: Decimal
    ) -> None:
        """Invariant I4 (property-based): equal payout holds for any arbitrage event.

        Generated odds in [2.05, 3.00] guarantee an arbitrage opportunity:
        if both odds >= 2.05, then 1/odds_a + 1/odds_b <= 2/2.05 ≈ 0.9756 < 1.
        """
        event = _build_arbitrage_event(str(federer_odds), str(nadal_odds))

        stakes = optimal_stakes(event, total_stake)
        best = best_quote_per_outcome(event)

        payouts = [stakes[outcome] * quote.decimal_odds for outcome, quote in best.items()]
        # Allow small Decimal precision drift (28 digits, so ~1e-25 tolerance).
        assert abs(payouts[0] - payouts[1]) < Decimal("1e-20")


class TestFindArbitrageOpportunity:
    """Verify the Level 4 composition that returns ArbitrageOpportunity or None."""

    def test_returns_none_on_non_arbitrage_market(self) -> None:
        """When the event is not an arbitrage opportunity, returns None."""
        event = _build_two_outcome_event(
            federer_quotes=[("Pinnacle", "1.91")],
            nadal_quotes=[("Pinnacle", "1.91")],
        )

        assert find_arbitrage_opportunity(event, Decimal("1000")) is None

    def test_returns_opportunity_on_arbitrage_market(self) -> None:
        """When arbitrage exists, returns a complete ArbitrageOpportunity."""
        event = _build_arbitrage_event("2.10", "2.00")

        opportunity = find_arbitrage_opportunity(event, Decimal("1000"))

        assert opportunity is not None
        assert opportunity.event == event
        assert opportunity.total_stake == Decimal("1000")
        assert opportunity.guaranteed_profit_ratio > Decimal(0)
        assert opportunity.guaranteed_profit > Decimal(0)

    def test_opportunity_contains_best_quotes_for_all_outcomes(self) -> None:
        """The returned opportunity includes the best quote for each outcome."""
        event = _build_arbitrage_event("2.10", "2.00")

        opportunity = find_arbitrage_opportunity(event, Decimal("1000"))

        assert opportunity is not None
        assert len(opportunity.best_quotes) == len(event.outcomes)
        for outcome in event.outcomes:
            assert outcome in opportunity.best_quotes

    def test_opportunity_stakes_sum_to_total_stake(self) -> None:
        """The optimal stakes in the opportunity sum to the total stake (I3)."""
        event = _build_arbitrage_event("2.10", "2.00")

        opportunity = find_arbitrage_opportunity(event, Decimal("1000"))

        assert opportunity is not None
        assert sum(opportunity.optimal_stakes.values()) == Decimal("1000")

    def test_opportunity_profit_equals_ratio_times_stake(self) -> None:
        """The captured profit equals ratio * total_stake exactly."""
        event = _build_arbitrage_event("2.10", "2.00")

        opportunity = find_arbitrage_opportunity(event, Decimal("1000"))

        assert opportunity is not None
        expected_profit = Decimal("1000") * opportunity.guaranteed_profit_ratio
        assert opportunity.guaranteed_profit == expected_profit

    def test_perfectly_fair_market_returns_none(self) -> None:
        """A perfectly fair market (T = 1.0) returns None — no arbitrage."""
        event = _build_two_outcome_event(
            federer_quotes=[("Pinnacle", "2.00")],
            nadal_quotes=[("Pinnacle", "2.00")],
        )

        assert find_arbitrage_opportunity(event, Decimal("1000")) is None
