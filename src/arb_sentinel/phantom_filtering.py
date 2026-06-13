"""Phantom filter: separates real arbitrage candidates from outlier-driven phantoms.

Pure functions, layered bottom-up. See docs/design/phantom-filtering.md for the
complete specification, invariants, and worked example.
"""

from collections.abc import Iterable
from decimal import Decimal

from arb_sentinel.arbitrage import (
    best_quote_per_outcome,
    find_arbitrage_opportunity,
    implied_probability,
    total_implied_probability,
)
from arb_sentinel.models import CleanedEvent, Event, Outcome, PhantomFilterResult, Quote

# Initial knobs — validated on the IT0 fixture, to be refined from observation.
DEFAULT_RELATIVE_THRESHOLD = Decimal("0.20")
DEFAULT_MIN_BOOKS_PER_OUTCOME = 4
DEFAULT_MAX_PROFIT_RATIO = Decimal("0.10")


def consensus_implied_probability(quotes_for_outcome: Iterable[Quote]) -> Decimal:
    """The market consensus implied probability for a single outcome: the median
    of the implied probabilities across all bookmakers quoting that outcome.

    Median (not mean) so a single outlier cannot move the consensus.
    """
    probs = sorted(implied_probability(q.decimal_odds) for q in quotes_for_outcome)
    if not probs:
        raise ValueError("Cannot compute consensus: no quotes provided.")
    n = len(probs)
    mid = n // 2
    if n % 2 == 1:
        return probs[mid]
    return (probs[mid - 1] + probs[mid]) / Decimal(2)


def is_generous_outlier(
    implied_probability: Decimal,
    consensus: Decimal,
    relative_threshold: Decimal,
) -> bool:
    """Whether a quote is too generous relative to the market consensus.

    True when implied_probability < consensus * (1 - relative_threshold):
    the quote prices the outcome far more generously (higher odds) than the
    market median. Only the generous side is rejected — an abnormally
    pessimistic quote (low odds) is never selected as the best quote and so
    cannot create a false arbitrage.
    """
    return implied_probability < consensus * (1 - relative_threshold)


def clean_quotes(
    event: Event,
    relative_threshold: Decimal,
    min_books_per_outcome: int,
) -> CleanedEvent:
    """Remove generous outliers per outcome against the fixed consensus.

    The consensus is computed once per outcome over all quotes; each quote is
    then tested against it in a single pass. Returns a CleanedEvent that carries
    the filtered Event, the per-outcome book counts (before/after), and whether
    any outcome fell below min_books_per_outcome (low confidence).
    """
    counts_before: dict[Outcome, int] = {
        o: sum(1 for q in event.quotes if q.outcome == o) for o in event.outcomes
    }

    # Consensus computed ONCE per outcome over the full quote set — not recomputed
    # on survivors. This single-pass approach is what makes idempotence (P2) hold
    # for the domain where the filter operates.
    consensus: dict[Outcome, Decimal] = {
        o: consensus_implied_probability([q for q in event.quotes if q.outcome == o])
        for o in event.outcomes
    }

    kept = [
        q
        for q in event.quotes
        if not is_generous_outlier(
            implied_probability(q.decimal_odds), consensus[q.outcome], relative_threshold
        )
    ]

    counts_after: dict[Outcome, int] = {
        o: sum(1 for q in kept if q.outcome == o) for o in event.outcomes
    }

    # Low-confidence is checked on raw counts: the question is whether the market
    # had enough data to trust the consensus, not whether enough quotes survived.
    low_confidence = any(counts_before[o] < min_books_per_outcome for o in event.outcomes)

    return CleanedEvent(
        event=Event(description=event.description, outcomes=event.outcomes, quotes=kept),
        counts_before=counts_before,
        counts_after=counts_after,
        low_confidence=low_confidence,
    )


def classify_event(
    event: Event,
    total_stake: Decimal,
    relative_threshold: Decimal,
    min_books_per_outcome: int,
    max_profit_ratio: Decimal,
) -> PhantomFilterResult:
    """Classify an event as candidate / phantom / no_arbitrage / low_confidence.

    1. If any outcome has < min_books_per_outcome quotes -> low_confidence.
    2. Clean the quotes, then run find_arbitrage_opportunity on the cleaned event.
    3. If a clean arbitrage exists and its profit ratio <= max_profit_ratio
       -> candidate (carry the ArbitrageOpportunity).
    4. If a clean arbitrage exists but its ratio > max_profit_ratio -> phantom.
    5. If the raw event looked like an arbitrage but the clean one does not
       -> phantom (outlier-driven).
    6. Otherwise -> no_arbitrage.

    Only `candidate` results are notified. Every result is journaled.
    """
    # Count quotes per outcome BEFORE any computation that requires >= 1 quote per outcome.
    # best_quote_per_outcome raises ValueError on a zero-quote outcome, so the low-confidence
    # guard must fire first to satisfy the spec's guarantee (P4).
    counts_before: dict[Outcome, int] = {
        o: sum(1 for q in event.quotes if q.outcome == o) for o in event.outcomes
    }

    if any(counts_before[o] < min_books_per_outcome for o in event.outcomes):
        # raw_tip requires at least 1 quote per outcome; use 0 as sentinel when that
        # constraint is not met (a non-optional field that is semantically undefined here).
        can_compute_tip = all(counts_before[o] >= 1 for o in event.outcomes)
        raw_tip = (
            total_implied_probability(best_quote_per_outcome(event).values())
            if can_compute_tip
            else Decimal(0)
        )
        return PhantomFilterResult(
            classification="low_confidence",
            reason=f"Fewer than {min_books_per_outcome} books on at least one outcome.",
            book_counts=counts_before,
            raw_total_implied_probability=raw_tip,
            clean_total_implied_probability=None,
            opportunity=None,
        )

    # From here all outcomes have >= min_books_per_outcome >= 1 quotes.
    raw_tip = total_implied_probability(best_quote_per_outcome(event).values())
    cleaned = clean_quotes(event, relative_threshold, min_books_per_outcome)
    book_counts = counts_before  # counts_before from clean_quotes matches — reuse ours

    clean_tip = total_implied_probability(best_quote_per_outcome(cleaned.event).values())
    clean_opp = find_arbitrage_opportunity(cleaned.event, total_stake)

    if clean_opp is not None and clean_opp.guaranteed_profit_ratio <= max_profit_ratio:
        return PhantomFilterResult(
            classification="candidate",
            reason=f"Clean arbitrage at {clean_opp.guaranteed_profit_ratio:.4f} profit ratio.",
            book_counts=book_counts,
            raw_total_implied_probability=raw_tip,
            clean_total_implied_probability=clean_tip,
            opportunity=clean_opp,
        )

    if clean_opp is not None and clean_opp.guaranteed_profit_ratio > max_profit_ratio:
        return PhantomFilterResult(
            classification="phantom",
            reason=(
                f"Clean ratio {clean_opp.guaranteed_profit_ratio:.4f} "
                f"exceeds plausibility cap {max_profit_ratio}."
            ),
            book_counts=book_counts,
            raw_total_implied_probability=raw_tip,
            clean_total_implied_probability=clean_tip,
            opportunity=None,
        )

    if clean_opp is None and raw_tip < Decimal(1):
        return PhantomFilterResult(
            classification="phantom",
            reason="Apparent arbitrage disappears after removing generous outliers.",
            book_counts=book_counts,
            raw_total_implied_probability=raw_tip,
            clean_total_implied_probability=clean_tip,
            opportunity=None,
        )

    # clean_opp is None and raw_tip >= 1: no arbitrage before or after cleaning.
    return PhantomFilterResult(
        classification="no_arbitrage",
        reason="No arbitrage in the clean quote set.",
        book_counts=book_counts,
        raw_total_implied_probability=raw_tip,
        clean_total_implied_probability=clean_tip,
        opportunity=None,
    )
