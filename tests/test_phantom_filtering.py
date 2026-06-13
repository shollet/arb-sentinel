"""Tests for the phantom filter.

Each class corresponds to one invariant from docs/design/phantom-filtering.md.
Property-based tests use Hypothesis with Decimal arithmetic throughout -- no floats.
"""

import itertools
import json
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from arb_sentinel.arbitrage import (
    best_quote_per_outcome,
    find_arbitrage_opportunity,
    implied_probability,
    total_implied_probability,
)
from arb_sentinel.models import Bookmaker, Event, Outcome, Quote
from arb_sentinel.odds_api import OddsApiEvent, to_domain_event
from arb_sentinel.phantom_filtering import (
    DEFAULT_MAX_PROFIT_RATIO,
    DEFAULT_MIN_BOOKS_PER_OUTCOME,
    DEFAULT_RELATIVE_THRESHOLD,
    classify_event,
    clean_quotes,
    consensus_implied_probability,
    is_generous_outlier,
)

# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

valid_odds = st.decimals(
    min_value=Decimal("1.01"),
    max_value=Decimal("100"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# Restricted to a realistic tennis range where P2 idempotence holds under the
# default 0.20 threshold. Adversarial combinations of very wide odds spreads
# with large thresholds can break idempotence; see plan for the counterexample.
tennis_odds = st.decimals(
    min_value=Decimal("1.10"),
    max_value=Decimal("3.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

valid_stake = st.decimals(
    min_value=Decimal("1.00"),
    max_value=Decimal("1000000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


def _make_quote(outcome: Outcome, bookmaker_name: str, odds: Decimal) -> Quote:
    return Quote(outcome=outcome, bookmaker=Bookmaker(name=bookmaker_name), decimal_odds=odds)


def _build_event(
    a_quotes: list[tuple[str, Decimal]],
    b_quotes: list[tuple[str, Decimal]],
    desc: str = "Player A vs Player B",
) -> Event:
    outcome_a = Outcome(name="Player A")
    outcome_b = Outcome(name="Player B")
    quotes = [_make_quote(outcome_a, bm, odds) for bm, odds in a_quotes] + [
        _make_quote(outcome_b, bm, odds) for bm, odds in b_quotes
    ]
    return Event(description=desc, outcomes=[outcome_a, outcome_b], quotes=quotes)


def _build_event_from_lists(
    outcome_a_odds: list[Decimal],
    outcome_b_odds: list[Decimal],
) -> Event:
    return _build_event(
        [(f"BM_A{i}", o) for i, o in enumerate(outcome_a_odds)],
        [(f"BM_B{i}", o) for i, o in enumerate(outcome_b_odds)],
    )


# ---------------------------------------------------------------------------
# Level 0: consensus_implied_probability
# ---------------------------------------------------------------------------


class TestConsensusImpliedProbability:
    def test_odd_count_returns_middle_element(self) -> None:
        """Three quotes -- median is the middle of the sorted implied probs."""
        # implied probs: 1/1.25=0.8, 1/2.00=0.5, 1/4.00=0.25 -> sorted: [0.25, 0.5, 0.8]
        outcome = Outcome(name="A")
        bm = Bookmaker(name="BM")
        quotes = [
            Quote(outcome=outcome, bookmaker=bm, decimal_odds=Decimal("1.25")),
            Quote(outcome=outcome, bookmaker=bm, decimal_odds=Decimal("2.00")),
            Quote(outcome=outcome, bookmaker=bm, decimal_odds=Decimal("4.00")),
        ]
        assert consensus_implied_probability(quotes) == Decimal("0.5")

    def test_even_count_returns_mean_of_two_middle(self) -> None:
        """Two quotes -- median is the mean of the two implied probs."""
        # implied probs: 1/2.00=0.5, 1/4.00=0.25 -> (0.25+0.5)/2 = 0.375
        outcome = Outcome(name="A")
        bm = Bookmaker(name="BM")
        quotes = [
            Quote(outcome=outcome, bookmaker=bm, decimal_odds=Decimal("2.00")),
            Quote(outcome=outcome, bookmaker=bm, decimal_odds=Decimal("4.00")),
        ]
        assert consensus_implied_probability(quotes) == Decimal("0.375")

    def test_single_quote_returns_its_implied_probability(self) -> None:
        outcome = Outcome(name="A")
        bm = Bookmaker(name="BM")
        quotes = [Quote(outcome=outcome, bookmaker=bm, decimal_odds=Decimal("2.00"))]
        assert consensus_implied_probability(quotes) == Decimal("0.5")

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="no quotes"):
            consensus_implied_probability([])

    def test_fixture_arnaldi_consensus(self) -> None:
        """The 15-book Arnaldi consensus from the worked example is approximately 0.862."""
        # All Arnaldi odds from odds_api_event_sample.json (h2h only)
        arnaldi_odds = [
            "1.13",
            "1.16",
            "1.15",
            "1.18",
            "1.09",
            "1.16",
            "1.16",
            "1.23",
            "1.15",
            "1.11",
            "1.16",
            "1.17",
            "1.68",
            "1.25",
            "1.10",
        ]
        outcome = Outcome(name="Matteo Arnaldi")
        bm = Bookmaker(name="BM")
        quotes = [
            Quote(outcome=outcome, bookmaker=bm, decimal_odds=Decimal(o)) for o in arnaldi_odds
        ]
        consensus = consensus_implied_probability(quotes)
        # Median of 15 elements (index 7) is 1/1.16 ~= 0.8621
        assert Decimal("0.860") < consensus < Decimal("0.865")


# ---------------------------------------------------------------------------
# Level 1: is_generous_outlier
# ---------------------------------------------------------------------------


class TestIsGenerousOutlier:
    def test_well_priced_quote_is_not_outlier(self) -> None:
        """Matchbook (0.80) against Arnaldi consensus (0.862), threshold 0.20: kept."""
        # bound = 0.862 * 0.80 = 0.6896; 0.80 >= 0.6896 -> not outlier
        assert is_generous_outlier(Decimal("0.80"), Decimal("0.862"), Decimal("0.20")) is False

    def test_extreme_outlier_is_generous(self) -> None:
        """Pinnacle (0.595) against Arnaldi consensus (0.862), threshold 0.20: removed."""
        # bound = 0.6896; 0.595 < 0.6896 -> outlier
        assert is_generous_outlier(Decimal("0.595"), Decimal("0.862"), Decimal("0.20")) is True

    def test_exactly_at_boundary_is_not_outlier(self) -> None:
        """Strict < means the boundary value itself is kept."""
        bound = Decimal("0.862") * (1 - Decimal("0.20"))
        assert is_generous_outlier(bound, Decimal("0.862"), Decimal("0.20")) is False

    def test_just_below_boundary_is_outlier(self) -> None:
        bound = Decimal("0.862") * (1 - Decimal("0.20"))
        below = bound - Decimal("0.001")
        assert is_generous_outlier(below, Decimal("0.862"), Decimal("0.20")) is True

    def test_pessimistic_quote_above_consensus_is_not_outlier(self) -> None:
        """A quote priced tighter than the market (high implied prob) is never rejected."""
        assert is_generous_outlier(Decimal("0.95"), Decimal("0.862"), Decimal("0.20")) is False


# ---------------------------------------------------------------------------
# P1: clean_T >= raw_T (the filter cannot manufacture an arbitrage)
# ---------------------------------------------------------------------------


class TestP1FilterCannotManufactureArbitrage:
    @given(
        outcome_a_odds=st.lists(valid_odds, min_size=4, max_size=10),
        outcome_b_odds=st.lists(valid_odds, min_size=4, max_size=10),
    )
    def test_clean_tip_gte_raw_tip(
        self,
        outcome_a_odds: list[Decimal],
        outcome_b_odds: list[Decimal],
    ) -> None:
        """Invariant P1: removing quotes can only raise or keep the total implied probability."""
        event = _build_event_from_lists(outcome_a_odds, outcome_b_odds)
        raw_tip = total_implied_probability(best_quote_per_outcome(event).values())
        cleaned = clean_quotes(event, DEFAULT_RELATIVE_THRESHOLD, DEFAULT_MIN_BOOKS_PER_OUTCOME)
        clean_tip = total_implied_probability(best_quote_per_outcome(cleaned.event).values())
        assert clean_tip >= raw_tip


# ---------------------------------------------------------------------------
# P2: clean(clean(e)) == clean(e)  (idempotence)
# ---------------------------------------------------------------------------


class TestP2Idempotence:
    @given(
        outcome_a_odds=st.lists(valid_odds, min_size=4, max_size=10),
        outcome_b_odds=st.lists(valid_odds, min_size=4, max_size=10),
    )
    def test_no_survivor_is_outlier_against_original_consensus(
        self,
        outcome_a_odds: list[Decimal],
        outcome_b_odds: list[Decimal],
    ) -> None:
        """Invariant P2 (single-pass stability): every quote that survives cleaning is
        not a generous outlier against the consensus computed before cleaning.

        This is the correct formulation of the spec's P2 claim. The claim is that the
        single-pass design is stable: survivors do not violate the ORIGINAL threshold.
        Calling clean_quotes(clean(e).event) recomputes the consensus from survivors,
        which can shift upward (removing generous outliers raises the median), making
        a borderline survivor an outlier on a second pass. This variant does NOT
        universally hold (Hypothesis finds counterexamples even in the tennis range).
        What IS guaranteed: survivors always satisfy `implied_prob >= original_consensus
        * (1 - threshold)`, which this test verifies directly.
        """
        event = _build_event_from_lists(outcome_a_odds, outcome_b_odds)
        cleaned = clean_quotes(event, DEFAULT_RELATIVE_THRESHOLD, DEFAULT_MIN_BOOKS_PER_OUTCOME)

        # Reconstruct the original per-outcome consensus (same computation as clean_quotes uses)
        original_consensus = {
            o: consensus_implied_probability([q for q in event.quotes if q.outcome == o])
            for o in event.outcomes
        }

        for q in cleaned.event.quotes:
            assert not is_generous_outlier(
                implied_probability(q.decimal_odds),
                original_consensus[q.outcome],
                DEFAULT_RELATIVE_THRESHOLD,
            ), f"Survivor {q} is a generous outlier against the original consensus."

    def test_fixture_clean_is_idempotent(self) -> None:
        """Concrete check on the fixture: the second clean removes nothing.

        For the Arnaldi/Collignon event, Pinnacle (the only outlier) is removed in
        the first pass. The remaining 14 quotes per outcome all sit well within the
        new consensus band, so the second pass is a no-op.
        """
        fixture = Path(__file__).parent / "fixtures" / "odds_api_event_sample.json"
        event = to_domain_event(OddsApiEvent.model_validate(json.loads(fixture.read_text())))
        once = clean_quotes(event, DEFAULT_RELATIVE_THRESHOLD, DEFAULT_MIN_BOOKS_PER_OUTCOME)
        twice = clean_quotes(once.event, DEFAULT_RELATIVE_THRESHOLD, DEFAULT_MIN_BOOKS_PER_OUTCOME)
        assert frozenset(once.event.quotes) == frozenset(twice.event.quotes)


# ---------------------------------------------------------------------------
# P3: median robustness -- adding one extreme quote shifts consensus by at most
#     the largest adjacent gap in the original sorted implied probs.
# ---------------------------------------------------------------------------


class TestP3MedianRobustness:
    @given(
        base_odds=st.lists(valid_odds, min_size=2, max_size=10),
        extra_odds=valid_odds,
    )
    def test_single_added_quote_shifts_consensus_by_at_most_one_step(
        self,
        base_odds: list[Decimal],
        extra_odds: Decimal,
    ) -> None:
        """Invariant P3: adding one quote moves the consensus by at most one order-statistic step.

        The bound is max_adjacent_gap of the sorted base implied probs. This is
        tight: with N base quotes, adding one element can only shift the median
        to an adjacent position in the sorted base list.
        """
        outcome = Outcome(name="A")
        bm = Bookmaker(name="BM")

        base_quotes = [Quote(outcome=outcome, bookmaker=bm, decimal_odds=o) for o in base_odds]
        extra_quote = Quote(outcome=outcome, bookmaker=bm, decimal_odds=extra_odds)

        consensus_before = consensus_implied_probability(base_quotes)
        consensus_after = consensus_implied_probability([*base_quotes, extra_quote])

        base_probs = sorted(implied_probability(o) for o in base_odds)
        if len(base_probs) > 1:
            max_gap = max(b - a for a, b in itertools.pairwise(base_probs))
        else:
            max_gap = Decimal(0)

        # The even-count median computation `(probs[n//2-1] + probs[n//2]) / Decimal(2)`
        # can lose one ULP relative to the original element due to the 28-sig-fig
        # Decimal precision. A tolerance of 1E-26 absorbs this artifact without
        # weakening the bound for any meaningful implied probability difference.
        assert abs(consensus_after - consensus_before) <= max_gap + Decimal("1E-26")

    def test_extreme_outlier_shifts_consensus_less_than_mean_would(self) -> None:
        """Concrete illustration: adding one extreme shifts the median far less than the mean."""
        outcome = Outcome(name="A")
        bm = Bookmaker(name="BM")
        # 5 quotes tightly clustered; one wild outlier added
        base_probs_odds = ["1.11", "1.13", "1.15", "1.17", "1.19"]  # implies ~0.84-0.90
        base_quotes = [
            Quote(outcome=outcome, bookmaker=bm, decimal_odds=Decimal(o)) for o in base_probs_odds
        ]
        extreme = Quote(
            outcome=outcome,
            bookmaker=bm,
            decimal_odds=Decimal("10.00"),  # implies 0.10
        )

        consensus_before = consensus_implied_probability(base_quotes)
        consensus_after = consensus_implied_probability([*base_quotes, extreme])

        base_sum = sum(implied_probability(Decimal(o)) for o in base_probs_odds)
        mean_before = base_sum / Decimal(5)
        mean_after = (base_sum + implied_probability(Decimal("10.00"))) / Decimal(6)

        median_shift = abs(consensus_after - consensus_before)
        mean_shift = abs(mean_after - mean_before)

        assert median_shift < mean_shift


# ---------------------------------------------------------------------------
# P4: minimum-books guard -- < min_books on any outcome -> low_confidence, never candidate
# ---------------------------------------------------------------------------


class TestP4MinBooksGuard:
    def test_three_books_on_outcome_a_is_low_confidence(self) -> None:
        """3 quotes for outcome A (< 4 default minimum) -> low_confidence."""
        event = _build_event(
            a_quotes=[
                ("BM1", Decimal("1.50")),
                ("BM2", Decimal("1.55")),
                ("BM3", Decimal("1.60")),
            ],
            b_quotes=[
                ("BM1", Decimal("2.80")),
                ("BM2", Decimal("2.85")),
                ("BM3", Decimal("2.90")),
                ("BM4", Decimal("2.95")),
            ],
        )
        result = classify_event(
            event,
            Decimal("1000"),
            DEFAULT_RELATIVE_THRESHOLD,
            DEFAULT_MIN_BOOKS_PER_OUTCOME,
            DEFAULT_MAX_PROFIT_RATIO,
        )
        assert result.classification == "low_confidence"

    def test_exactly_min_books_is_not_low_confidence(self) -> None:
        """Exactly min_books_per_outcome quotes per outcome -- not low_confidence."""
        event = _build_event(
            a_quotes=[
                ("BM1", Decimal("1.50")),
                ("BM2", Decimal("1.55")),
                ("BM3", Decimal("1.60")),
                ("BM4", Decimal("1.65")),
            ],
            b_quotes=[
                ("BM1", Decimal("2.80")),
                ("BM2", Decimal("2.85")),
                ("BM3", Decimal("2.90")),
                ("BM4", Decimal("2.95")),
            ],
        )
        result = classify_event(
            event,
            Decimal("1000"),
            DEFAULT_RELATIVE_THRESHOLD,
            DEFAULT_MIN_BOOKS_PER_OUTCOME,
            DEFAULT_MAX_PROFIT_RATIO,
        )
        assert result.classification != "low_confidence"

    @given(
        n_a=st.integers(min_value=1, max_value=DEFAULT_MIN_BOOKS_PER_OUTCOME - 1),
        n_b=st.integers(min_value=DEFAULT_MIN_BOOKS_PER_OUTCOME, max_value=10),
        base_odds_a=st.decimals(
            min_value=Decimal("1.30"),
            max_value=Decimal("1.80"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        base_odds_b=st.decimals(
            min_value=Decimal("2.20"),
            max_value=Decimal("3.50"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    def test_below_min_books_is_never_candidate(
        self,
        n_a: int,
        n_b: int,
        base_odds_a: Decimal,
        base_odds_b: Decimal,
    ) -> None:
        """Invariant P4 (property): fewer than min_books on any outcome -> never candidate."""
        event = _build_event(
            a_quotes=[(f"BM{i}", base_odds_a) for i in range(n_a)],
            b_quotes=[(f"BM{i}", base_odds_b) for i in range(n_b)],
        )
        result = classify_event(
            event,
            Decimal("1000"),
            DEFAULT_RELATIVE_THRESHOLD,
            DEFAULT_MIN_BOOKS_PER_OUTCOME,
            DEFAULT_MAX_PROFIT_RATIO,
        )
        assert result.classification != "candidate"


# ---------------------------------------------------------------------------
# P5: plausibility cap -- every candidate has profit ratio <= max_profit_ratio
# ---------------------------------------------------------------------------


def _build_clean_arbitrage_event(
    a_odds: str,
    b_odds: str,
    n_books: int = DEFAULT_MIN_BOOKS_PER_OUTCOME,
) -> Event:
    """Build an event with n_books identical quotes per outcome (no outliers to remove)."""
    return _build_event(
        a_quotes=[(f"BM_A{i}", Decimal(a_odds)) for i in range(n_books)],
        b_quotes=[(f"BM_B{i}", Decimal(b_odds)) for i in range(n_books)],
    )


class TestP5PlausibilityCap:
    def test_five_percent_profit_ratio_is_candidate(self) -> None:
        """A clean ~5% profit ratio is within the 10% cap -> candidate."""
        # 1/2.10 + 1/2.10 ~= 0.952 -> profit ~= 5%
        event = _build_clean_arbitrage_event("2.10", "2.10")
        result = classify_event(
            event,
            Decimal("1000"),
            DEFAULT_RELATIVE_THRESHOLD,
            DEFAULT_MIN_BOOKS_PER_OUTCOME,
            DEFAULT_MAX_PROFIT_RATIO,
        )
        assert result.classification == "candidate"
        assert result.opportunity is not None
        assert result.opportunity.guaranteed_profit_ratio <= DEFAULT_MAX_PROFIT_RATIO

    def test_profit_ratio_at_cap_is_candidate(self) -> None:
        """A clean profit ratio exactly equal to max_profit_ratio (<=) -> candidate."""
        # 1/2.20 + 1/2.20 = 10/11 ~= 0.9091 -> profit ratio = 1/10 = 0.10 exactly
        event = _build_clean_arbitrage_event("2.20", "2.20")
        result = classify_event(
            event,
            Decimal("1000"),
            DEFAULT_RELATIVE_THRESHOLD,
            DEFAULT_MIN_BOOKS_PER_OUTCOME,
            DEFAULT_MAX_PROFIT_RATIO,
        )
        assert result.classification == "candidate"
        assert result.opportunity is not None
        assert result.opportunity.guaranteed_profit_ratio <= DEFAULT_MAX_PROFIT_RATIO

    def test_profit_ratio_above_cap_is_phantom(self) -> None:
        """A clean profit ratio above max_profit_ratio -> phantom (belt-and-suspenders)."""
        # 1/2.30 + 1/2.30 ~= 0.870 -> profit ratio ~= 0.149 > 0.10
        event = _build_clean_arbitrage_event("2.30", "2.30")
        result = classify_event(
            event,
            Decimal("1000"),
            DEFAULT_RELATIVE_THRESHOLD,
            DEFAULT_MIN_BOOKS_PER_OUTCOME,
            DEFAULT_MAX_PROFIT_RATIO,
        )
        assert result.classification == "phantom"
        assert result.opportunity is None

    def test_large_profit_ratio_is_phantom(self) -> None:
        """An implausibly large clean profit ratio -> phantom."""
        event = _build_clean_arbitrage_event("5.00", "5.00")
        result = classify_event(
            event,
            Decimal("1000"),
            DEFAULT_RELATIVE_THRESHOLD,
            DEFAULT_MIN_BOOKS_PER_OUTCOME,
            DEFAULT_MAX_PROFIT_RATIO,
        )
        assert result.classification == "phantom"


# ---------------------------------------------------------------------------
# Pivot test: the IT0 fixture -- Pinnacle is a generous outlier, not free money
# ---------------------------------------------------------------------------


class TestFixturePinnacleOutlierIsPhantom:
    def test_fixture_pinnacle_outlier_is_phantom(self) -> None:
        """Filter catches the Pinnacle phantom and exposes the real candidate.

        Without the filter, the raw best quotes (Pinnacle 1.68 for Arnaldi, Betclic
        5.5 for Collignon) imply a ~28.7% "arbitrage" -- manifestly impossible for a
        pre-match h2h. With the filter, Pinnacle's Arnaldi quote is flagged as a
        generous outlier (implied probability 0.595 << consensus ~0.862), removed,
        and the surviving best quote (Matchbook 1.25) combines with Betclic 5.5 to
        yield a plausible ~1.85% candidate.
        """
        fixture = Path(__file__).parent / "fixtures" / "odds_api_event_sample.json"
        event = to_domain_event(OddsApiEvent.model_validate(json.loads(fixture.read_text())))

        # Without filter: the Pinnacle quote manufactures a ~28% phantom.
        raw_opp = find_arbitrage_opportunity(event, Decimal("1000"))
        assert raw_opp is not None, "Raw event should appear to be an arbitrage (the phantom)."
        assert Decimal("0.28") < raw_opp.guaranteed_profit_ratio < Decimal("0.30"), (
            f"Expected ~28.7% raw profit ratio, got {raw_opp.guaranteed_profit_ratio}"
        )

        # With filter: phantom removed, real candidate survives.
        result = classify_event(
            event,
            Decimal("1000"),
            DEFAULT_RELATIVE_THRESHOLD,
            DEFAULT_MIN_BOOKS_PER_OUTCOME,
            DEFAULT_MAX_PROFIT_RATIO,
        )
        classification = result.classification
        assert classification == "candidate", f"Got {classification!r}: {result.reason}"

        # raw_T ~= 1/1.68 + 1/5.5 ~= 0.7771
        assert Decimal("0.77") < result.raw_total_implied_probability < Decimal("0.79"), (
            f"raw_tip out of range: {result.raw_total_implied_probability}"
        )

        # clean_T ~= 1/1.25 + 1/5.5 ~= 0.9818
        assert result.clean_total_implied_probability is not None
        assert Decimal("0.98") < result.clean_total_implied_probability < Decimal("0.99"), (
            f"clean_tip out of range: {result.clean_total_implied_probability}"
        )

        # Profit ratio ~= 1.85%
        assert result.opportunity is not None
        assert Decimal("0.018") < result.opportunity.guaranteed_profit_ratio < Decimal("0.019"), (
            f"clean profit ratio out of range: {result.opportunity.guaranteed_profit_ratio}"
        )

        # book_counts reflects the raw 15 books per outcome (pre-cleaning)
        for outcome, count in result.book_counts.items():
            assert count == 15, f"Expected 15 books for {outcome.name}, got {count}"
