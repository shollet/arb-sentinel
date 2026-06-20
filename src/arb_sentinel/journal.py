"""Detection journal and notification dedup for the continuous poller.

Functional Core (pure): dedup_key, to_journal_entry, is_notifiable.
Imperative Shell (I/O): append_journal_entry, load_dedup_state, save_dedup_state.

See docs/design/journal.md for the full specification and invariants J1-J6.
"""

import json
from datetime import datetime
from pathlib import Path

from arb_sentinel.models import JournalEntry, PhantomFilterResult


def dedup_key(match_id: str) -> str:
    """The dedup key for a detection. For IT1, the match identity itself.

    Isolated so the IT2 refinement (key that folds in a price fingerprint)
    is a one-place change without touching call sites.
    """
    return match_id


def to_journal_entry(
    result: PhantomFilterResult,
    match_id: str,
    detected_at: datetime,
) -> JournalEntry:
    """Project a classification result into a journal entry. Pure.

    Converts book_counts from {Outcome: int} to {str: int} (outcome name keys)
    so it serializes cleanly to JSON. detected_at is injected by the caller.
    """
    return JournalEntry(
        detected_at=detected_at,
        match_id=match_id,
        classification=result.classification,
        reason=result.reason,
        book_counts={outcome.name: count for outcome, count in result.book_counts.items()},
        raw_total_implied_probability=result.raw_total_implied_probability,
        clean_total_implied_probability=result.clean_total_implied_probability,
        opportunity=result.opportunity,
    )


def is_notifiable(result: PhantomFilterResult, key: str, already_notified: set[str]) -> bool:
    """Whether this detection should fire a notification. Pure.

    True iff the result is classified "candidate" AND key is not in already_notified.
    Reads only the in-memory set — never the journal, never the disk.
    """
    return result.classification == "candidate" and key not in already_notified


def append_journal_entry(entry: JournalEntry, journal_path: Path) -> None:
    """Append one entry as a single line to the journal file. I/O.

    Opens in append mode. Never reads or rewrites existing content.
    Creates the file and parents if absent.
    """
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    with journal_path.open("a") as f:
        f.write(entry.model_dump_json() + "\n")


def load_dedup_state(state_path: Path) -> set[str]:
    """Load the set of already-notified dedup keys. I/O.

    Returns an empty set if the file does not exist (first run).
    """
    if not state_path.exists():
        return set()
    return set(json.loads(state_path.read_text()))


def save_dedup_state(keys: set[str], state_path: Path) -> None:
    """Persist the set of notified dedup keys. I/O.

    Creates the file and parents if absent. Keys are sorted for deterministic output.
    """
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(sorted(keys)))
