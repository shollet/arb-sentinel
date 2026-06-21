"""Tests for Discord notification delivery.

Each test class corresponds to one invariant from docs/design/notification.md (N2-N6).
Property-based tests use Hypothesis with Decimal arithmetic throughout — no floats.
All HTTP traffic is intercepted by respx; the real Discord API is never called.
"""

import json
from decimal import Decimal

import httpx
import respx
from hypothesis import given
from hypothesis import strategies as st

from arb_sentinel.models import (
    ArbitrageOpportunity,
    Bookmaker,
    Event,
    Outcome,
    PhantomFilterResult,
    Quote,
)
from arb_sentinel.notification import (
    CANDIDATE_EMBED_COLOR,
    send_notification,
    to_discord_payload,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

ARNALDI = Outcome(name="Matteo Arnaldi")
COLLIGNON = Outcome(name="Raphael Collignon")

WEBHOOK = "https://discord.com/api/webhooks/123/token"

valid_odds = st.decimals(
    min_value=Decimal("1.01"),
    max_value=Decimal("100"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
valid_ratio = st.decimals(
    min_value=Decimal("0.001"),
    max_value=Decimal("0.099"),
    places=4,
    allow_nan=False,
    allow_infinity=False,
)


def _make_opportunity(
    outcome_a: Outcome,
    odds_a: Decimal,
    bm_a: str,
    outcome_b: Outcome,
    odds_b: Decimal,
    bm_b: str,
    ratio: Decimal,
) -> ArbitrageOpportunity:
    event = Event(
        description=f"{outcome_a.name} vs {outcome_b.name}",
        outcomes=[outcome_a, outcome_b],
        quotes=[
            Quote(outcome=outcome_a, bookmaker=Bookmaker(name=bm_a), decimal_odds=odds_a),
            Quote(outcome=outcome_b, bookmaker=Bookmaker(name=bm_b), decimal_odds=odds_b),
        ],
    )
    return ArbitrageOpportunity(
        event=event,
        best_quotes={
            outcome_a: Quote(
                outcome=outcome_a, bookmaker=Bookmaker(name=bm_a), decimal_odds=odds_a
            ),
            outcome_b: Quote(
                outcome=outcome_b, bookmaker=Bookmaker(name=bm_b), decimal_odds=odds_b
            ),
        },
        total_stake=Decimal("100"),
        optimal_stakes={outcome_a: Decimal("50"), outcome_b: Decimal("50")},
        guaranteed_profit_ratio=ratio,
        guaranteed_profit=ratio * Decimal("100"),
    )


def _candidate(opp: ArbitrageOpportunity, n: int = 5) -> PhantomFilterResult:
    return PhantomFilterResult(
        classification="candidate",
        reason="clean arbitrage detected",
        book_counts=dict.fromkeys(opp.best_quotes, n),
        raw_total_implied_probability=Decimal("0.98"),
        clean_total_implied_probability=Decimal("0.98"),
        opportunity=opp,
    )


def _has_no_floats(obj: object) -> bool:
    if isinstance(obj, float):
        return False
    if isinstance(obj, dict):
        return all(_has_no_floats(v) for v in obj.values())
    if isinstance(obj, list):
        return all(_has_no_floats(v) for v in obj)
    return True


# ---------------------------------------------------------------------------
# N3 (deterministic) and N4 (no float on wire)
# ---------------------------------------------------------------------------


class TestN3N4PureAndDecimal:
    @given(
        odds_a=valid_odds,
        odds_b=valid_odds,
        ratio=valid_ratio,
        n=st.integers(min_value=1, max_value=20),
    )
    def test_deterministic_and_no_float(
        self, odds_a: Decimal, odds_b: Decimal, ratio: Decimal, n: int
    ) -> None:
        """N3: same input always yields the same payload. N4: no Python float in the result."""
        opp = _make_opportunity(ARNALDI, odds_a, "BM_A", COLLIGNON, odds_b, "BM_B", ratio)
        result = _candidate(opp, n)
        p1 = to_discord_payload(result)
        p2 = to_discord_payload(result)
        assert p1 == p2  # N3
        assert _has_no_floats(p1)  # N4: no float in the dict tree
        embed = p1["embeds"][0]
        assert isinstance(embed["description"], str)
        for field in embed["fields"]:
            assert isinstance(field["value"], str)


# ---------------------------------------------------------------------------
# N5: webhook URL never appears in the serialized payload
# ---------------------------------------------------------------------------


class TestN5WebhookNotInPayload:
    def test_webhook_url_absent_from_payload(self) -> None:
        webhook_url = "https://discord.com/api/webhooks/123/super-secret-token"
        opp = _make_opportunity(
            ARNALDI,
            Decimal("2.04"),
            "Pinnacle",
            COLLIGNON,
            Decimal("2.04"),
            "Betfair",
            Decimal("0.02"),
        )
        result = _candidate(opp, 15)
        payload = to_discord_payload(result)
        assert webhook_url not in json.dumps(payload)


# ---------------------------------------------------------------------------
# N6: a candidate produces a valid embed; spec's Worked Example pinned exactly
# ---------------------------------------------------------------------------


class TestN6WorkedExample:
    def test_worked_example(self) -> None:
        """The Worked Example from notification.md rendered to an exact embed."""
        opp = _make_opportunity(
            ARNALDI,
            Decimal("2.04"),
            "Pinnacle",
            COLLIGNON,
            Decimal("2.04"),
            "Betfair",
            ratio=Decimal("0.0200"),  # -> "2.00" after *100, quantize(0.01)
        )
        result = _candidate(opp, n=15)

        expected = {
            "embeds": [
                {
                    "title": "Matteo Arnaldi vs Raphael Collignon",
                    "description": "Clean arbitrage — **2.00%** guaranteed margin",
                    "color": CANDIDATE_EMBED_COLOR,
                    "fields": [
                        {
                            "name": "Matteo Arnaldi",
                            "value": "2.04 @ Pinnacle · 15 books",
                            "inline": True,
                        },
                        {
                            "name": "Raphael Collignon",
                            "value": "2.04 @ Betfair · 15 books",
                            "inline": True,
                        },
                    ],
                    "footer": {"text": "arb-sentinel"},
                }
            ]
        }
        assert to_discord_payload(result) == expected


# ---------------------------------------------------------------------------
# N2: delivery failures never propagate; 204 returns True; wrong body never passes
# ---------------------------------------------------------------------------


class TestN2DeliveryFailure:
    def _result(self) -> PhantomFilterResult:
        opp = _make_opportunity(
            ARNALDI,
            Decimal("2.10"),
            "BM_A",
            COLLIGNON,
            Decimal("2.10"),
            "BM_B",
            Decimal("0.05"),
        )
        return _candidate(opp)

    @respx.mock
    def test_204_returns_true_with_correct_body(self) -> None:
        result = self._result()
        respx.post(WEBHOOK).mock(return_value=httpx.Response(204))
        assert send_notification(result, WEBHOOK) is True
        assert json.loads(respx.calls.last.request.content) == to_discord_payload(result)

    @respx.mock
    def test_500_returns_false(self) -> None:
        respx.post(WEBHOOK).mock(return_value=httpx.Response(500))
        assert send_notification(self._result(), WEBHOOK) is False

    @respx.mock
    def test_429_returns_false(self) -> None:
        respx.post(WEBHOOK).mock(return_value=httpx.Response(429))
        assert send_notification(self._result(), WEBHOOK) is False

    @respx.mock
    def test_timeout_returns_false(self) -> None:
        respx.post(WEBHOOK).mock(side_effect=httpx.TimeoutException("timed out"))
        assert send_notification(self._result(), WEBHOOK) is False
