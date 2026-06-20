"""Tests for the detection journal and notification dedup.

Each test class corresponds to one invariant from docs/design/journal.md (J1-J6)
plus the Worked Example. All file I/O uses tmp_path — no real data/ directory
is ever touched, exactly as respx keeps the real Odds API untouched.
"""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from arb_sentinel.arbitrage import find_arbitrage_opportunity
from arb_sentinel.journal import (
    append_journal_entry,
    dedup_key,
    is_notifiable,
    load_dedup_state,
    save_dedup_state,
    to_journal_entry,
)
from arb_sentinel.models import (
    Bookmaker,
    Event,
    JournalEntry,
    Outcome,
    PhantomFilterResult,
    Quote,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

OUTCOME_A = Outcome(name="Player A")
OUTCOME_B = Outcome(name="Player B")

_FIXED_TS = datetime(2026, 6, 20, 18, 24, 5, tzinfo=UTC)


def _arb_event() -> Event:
    """Minimal h2h event with a genuine arbitrage (both sides at 2.10)."""
    return Event(
        description="Player A vs Player B",
        outcomes=[OUTCOME_A, OUTCOME_B],
        quotes=[
            Quote(
                outcome=OUTCOME_A, bookmaker=Bookmaker(name="Book1"), decimal_odds=Decimal("2.10")
            ),
            Quote(
                outcome=OUTCOME_B, bookmaker=Bookmaker(name="Book2"), decimal_odds=Decimal("2.10")
            ),
        ],
    )


def _candidate_result() -> PhantomFilterResult:
    event = _arb_event()
    opportunity = find_arbitrage_opportunity(event, Decimal("100"))
    assert opportunity is not None
    return PhantomFilterResult(
        classification="candidate",
        reason="Clean arbitrage detected.",
        book_counts={OUTCOME_A: 5, OUTCOME_B: 5},
        raw_total_implied_probability=Decimal("0.9524"),
        clean_total_implied_probability=Decimal("0.9524"),
        opportunity=opportunity,
    )


def _no_arb_result() -> PhantomFilterResult:
    return PhantomFilterResult(
        classification="no_arbitrage",
        reason="Total implied probability above 1.",
        book_counts={OUTCOME_A: 10, OUTCOME_B: 10},
        raw_total_implied_probability=Decimal("1.0500"),
        clean_total_implied_probability=None,
        opportunity=None,
    )


def _phantom_result() -> PhantomFilterResult:
    return PhantomFilterResult(
        classification="phantom",
        reason="Arbitrage disappears after removing generous outlier.",
        book_counts={OUTCOME_A: 8, OUTCOME_B: 8},
        raw_total_implied_probability=Decimal("0.9800"),
        clean_total_implied_probability=Decimal("1.0100"),
        opportunity=None,
    )


def _low_confidence_result() -> PhantomFilterResult:
    return PhantomFilterResult(
        classification="low_confidence",
        reason="Fewer than 4 books per outcome after cleaning.",
        book_counts={OUTCOME_A: 3, OUTCOME_B: 3},
        raw_total_implied_probability=Decimal("0.9700"),
        clean_total_implied_probability=Decimal("0.9900"),
        opportunity=None,
    )


# ---------------------------------------------------------------------------
# J1 — Every detection is journaled exactly once per cycle
# ---------------------------------------------------------------------------


class TestJ1EveryDetectionJournaled:
    def test_all_four_classifications_produce_one_line_each(self, tmp_path: Path) -> None:
        journal = tmp_path / "journal.jsonl"
        results = [
            _candidate_result(),
            _no_arb_result(),
            _phantom_result(),
            _low_confidence_result(),
        ]
        for i, result in enumerate(results):
            entry = to_journal_entry(result, f"match_{i}", _FIXED_TS)
            append_journal_entry(entry, journal)

        lines = [ln for ln in journal.read_text().splitlines() if ln]
        assert len(lines) == 4

        classifications = [JournalEntry.model_validate_json(ln).classification for ln in lines]
        assert set(classifications) == {"candidate", "no_arbitrage", "phantom", "low_confidence"}

    def test_no_arbitrage_is_not_skipped(self, tmp_path: Path) -> None:
        journal = tmp_path / "journal.jsonl"
        entry = to_journal_entry(_no_arb_result(), "match_x", _FIXED_TS)
        append_journal_entry(entry, journal)

        lines = [ln for ln in journal.read_text().splitlines() if ln]
        assert len(lines) == 1
        assert JournalEntry.model_validate_json(lines[0]).classification == "no_arbitrage"


# ---------------------------------------------------------------------------
# J2 — The journal is append-only
# ---------------------------------------------------------------------------


class TestJ2AppendOnly:
    def test_earlier_lines_are_byte_identical_after_second_append(self, tmp_path: Path) -> None:
        journal = tmp_path / "journal.jsonl"

        entry1 = to_journal_entry(_no_arb_result(), "match_1", _FIXED_TS)
        append_journal_entry(entry1, journal)
        snapshot = journal.read_bytes()

        entry2 = to_journal_entry(_candidate_result(), "match_2", _FIXED_TS)
        append_journal_entry(entry2, journal)

        after = journal.read_bytes()
        assert after[: len(snapshot)] == snapshot
        assert len(after) > len(snapshot)


# ---------------------------------------------------------------------------
# J3 — Round-trip Decimal fidelity
# ---------------------------------------------------------------------------


class TestJ3DecimalRoundTrip:
    def test_candidate_with_opportunity_decimals_survive_round_trip(self, tmp_path: Path) -> None:
        journal = tmp_path / "journal.jsonl"
        result = _candidate_result()
        assert result.opportunity is not None
        original_entry = to_journal_entry(result, "match_rt", _FIXED_TS)
        append_journal_entry(original_entry, journal)

        line = journal.read_text().splitlines()[0]
        restored = JournalEntry.model_validate_json(line)

        assert restored.raw_total_implied_probability == (
            original_entry.raw_total_implied_probability
        )
        assert (
            restored.clean_total_implied_probability
            == original_entry.clean_total_implied_probability
        )
        assert restored.opportunity is not None
        assert restored.opportunity.guaranteed_profit_ratio == (
            result.opportunity.guaranteed_profit_ratio
        )
        assert restored.opportunity.guaranteed_profit == result.opportunity.guaranteed_profit
        assert restored.opportunity.total_stake == result.opportunity.total_stake
        for outcome, stake in result.opportunity.optimal_stakes.items():
            assert restored.opportunity.optimal_stakes[outcome] == stake
        for outcome, quote in result.opportunity.best_quotes.items():
            assert restored.opportunity.best_quotes[outcome].decimal_odds == quote.decimal_odds

    def test_no_arb_entry_round_trips_with_none_fields(self, tmp_path: Path) -> None:
        journal = tmp_path / "journal.jsonl"
        result = _no_arb_result()
        original_entry = to_journal_entry(result, "match_nrt", _FIXED_TS)
        append_journal_entry(original_entry, journal)

        line = journal.read_text().splitlines()[0]
        restored = JournalEntry.model_validate_json(line)

        assert restored.raw_total_implied_probability == (
            original_entry.raw_total_implied_probability
        )
        assert restored.clean_total_implied_probability is None
        assert restored.opportunity is None


# ---------------------------------------------------------------------------
# J4 — A dedup key is notified at most once
# ---------------------------------------------------------------------------


class TestJ4DedupAtMostOnce:
    def test_same_key_not_notifiable_on_second_cycle(self, tmp_path: Path) -> None:
        journal = tmp_path / "journal.jsonl"
        result = _candidate_result()
        key = dedup_key("match_arb")

        # Cycle 1
        notified: set[str] = set()
        assert is_notifiable(result, key, notified) is True
        notified.add(key)
        append_journal_entry(to_journal_entry(result, "match_arb", _FIXED_TS), journal)

        # Cycle 2 — same candidate, same key
        assert is_notifiable(result, key, notified) is False
        append_journal_entry(to_journal_entry(result, "match_arb", _FIXED_TS), journal)

        # Detection still journaled both times (J1)
        lines = [ln for ln in journal.read_text().splitlines() if ln]
        assert len(lines) == 2

    def test_different_key_remains_notifiable(self) -> None:
        result = _candidate_result()
        notified = {"match_a"}
        assert is_notifiable(result, "match_b", notified) is True


# ---------------------------------------------------------------------------
# J5 — Dedup state I/O is bounded per cycle
# ---------------------------------------------------------------------------


class TestJ5DedupStateIO:
    def test_load_returns_empty_set_when_file_absent(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.json"
        assert load_dedup_state(state_path) == set()

    def test_round_trip_load_mutate_save(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.json"

        keys = load_dedup_state(state_path)
        keys.add("key_one")
        keys.add("key_two")
        save_dedup_state(keys, state_path)

        reloaded = load_dedup_state(state_path)
        assert reloaded == {"key_one", "key_two"}

    def test_persisted_file_is_valid_json_list(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.json"
        save_dedup_state({"a", "b"}, state_path)
        parsed = json.loads(state_path.read_text())
        assert isinstance(parsed, list)
        assert set(parsed) == {"a", "b"}

    def test_save_creates_parent_directories(self, tmp_path: Path) -> None:
        state_path = tmp_path / "nested" / "dir" / "state.json"
        save_dedup_state({"k"}, state_path)
        assert state_path.exists()


# ---------------------------------------------------------------------------
# J6 — Journal and notification are independent
# ---------------------------------------------------------------------------


class TestJ6JournalAndNotificationIndependent:
    def test_non_candidate_is_journaled_but_not_notifiable(self, tmp_path: Path) -> None:
        journal = tmp_path / "journal.jsonl"
        result = _no_arb_result()
        key = dedup_key("match_na")

        append_journal_entry(to_journal_entry(result, "match_na", _FIXED_TS), journal)
        notifiable = is_notifiable(result, key, set())

        lines = [ln for ln in journal.read_text().splitlines() if ln]
        assert len(lines) == 1
        assert notifiable is False

    def test_candidate_journaled_even_when_dedup_suppresses_notification(
        self, tmp_path: Path
    ) -> None:
        journal = tmp_path / "journal.jsonl"
        result = _candidate_result()
        key = dedup_key("match_arb")
        already_notified = {key}

        append_journal_entry(to_journal_entry(result, "match_arb", _FIXED_TS), journal)
        notifiable = is_notifiable(result, key, already_notified)

        lines = [ln for ln in journal.read_text().splitlines() if ln]
        assert len(lines) == 1
        assert notifiable is False

    def test_is_notifiable_does_not_read_journal(self, tmp_path: Path) -> None:
        # is_notifiable must remain pure — it should work identically
        # whether the journal file exists or not.
        result = _candidate_result()
        key = dedup_key("match_pure")
        assert is_notifiable(result, key, set()) is True
        assert is_notifiable(result, key, {key}) is False


# ---------------------------------------------------------------------------
# Worked Example — two cycles, one candidate, one no_arbitrage
# ---------------------------------------------------------------------------


class TestWorkedExample:
    """
    Mirrors the worked example in docs/design/journal.md exactly:
    two cycles, 20 minutes apart, same two matches.
    """

    def test_two_cycles_journal_and_dedup(self, tmp_path: Path) -> None:
        journal_path = tmp_path / "journal.jsonl"
        state_path = tmp_path / "dedup_state.json"

        candidate = _candidate_result()
        no_arb = _no_arb_result()
        match_a_id = "Matteo Arnaldi vs Raphael Collignon"
        match_b_id = "Other Player vs Another Player"
        key_a = dedup_key(match_a_id)

        # --- Cycle 1 ---
        notified = load_dedup_state(state_path)
        assert notified == set()

        # Arnaldi vs Collignon → candidate
        append_journal_entry(to_journal_entry(candidate, match_a_id, _FIXED_TS), journal_path)
        cycle1_notifiable = is_notifiable(candidate, key_a, notified)
        assert cycle1_notifiable is True
        notified.add(key_a)

        # Other match → no_arbitrage
        append_journal_entry(to_journal_entry(no_arb, match_b_id, _FIXED_TS), journal_path)
        assert is_notifiable(no_arb, dedup_key(match_b_id), notified) is False

        save_dedup_state(notified, state_path)

        lines_after_cycle1 = [ln for ln in journal_path.read_text().splitlines() if ln]
        assert len(lines_after_cycle1) == 2
        assert load_dedup_state(state_path) == {key_a}

        # --- Cycle 2 (20 min later, same matches, same classifications) ---
        ts2 = datetime(2026, 6, 20, 18, 44, 5, tzinfo=UTC)
        notified = load_dedup_state(state_path)
        assert notified == {key_a}

        append_journal_entry(to_journal_entry(candidate, match_a_id, ts2), journal_path)
        cycle2_notifiable = is_notifiable(candidate, key_a, notified)
        assert cycle2_notifiable is False  # J4: already notified

        append_journal_entry(to_journal_entry(no_arb, match_b_id, ts2), journal_path)

        save_dedup_state(notified, state_path)

        lines_after_cycle2 = [ln for ln in journal_path.read_text().splitlines() if ln]
        assert len(lines_after_cycle2) == 4  # J1: 2 events x 2 cycles
        assert load_dedup_state(state_path) == {key_a}  # still just 1 key
