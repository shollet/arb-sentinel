"""Discord notification delivery for arbitrage candidates.

Splits into a pure formatter (to_discord_payload) and a thin I/O sender
(send_notification), mirroring the Functional Core / Imperative Shell pattern
used throughout the codebase. See docs/design/notification.md for the full spec.
"""

from decimal import Decimal

import httpx

from arb_sentinel.models import PhantomFilterResult

WEBHOOK_TIMEOUT_SECONDS = 10.0  # bound a stalled POST so it cannot hang a cycle
CANDIDATE_EMBED_COLOR = 0x10B981  # project emerald: green = clean candidate

_TWOPLACES = Decimal("0.01")


def to_discord_payload(result: PhantomFilterResult) -> dict:
    """Render a notifiable candidate as the Discord webhook JSON body. Pure.

    Precondition (N6): result.classification == "candidate" and result.opportunity is not
    None — guaranteed by the caller, since only notifiable detections reach delivery.

    Returns a single Discord embed: match as title, guaranteed profit ratio as a quantized
    percentage, one inline field per outcome. All Decimal values are strings (N4); no clock
    is read (N3); the webhook URL is never present (N5).
    """
    opp = result.opportunity
    ratio_pct = str((opp.guaranteed_profit_ratio * 100).quantize(_TWOPLACES))
    fields = []
    for outcome, quote in opp.best_quotes.items():
        odds_str = str(quote.decimal_odds.quantize(_TWOPLACES))
        n = result.book_counts[outcome]
        fields.append(
            {
                "name": outcome.name,
                "value": f"{odds_str} @ {quote.bookmaker.name} · {n} books",
                "inline": True,
            }
        )
    return {
        "embeds": [
            {
                "title": opp.event.description,
                "description": f"Clean arbitrage — **{ratio_pct}%** guaranteed margin",
                "color": CANDIDATE_EMBED_COLOR,
                "fields": fields,
                "footer": {"text": "arb-sentinel"},
            }
        ]
    }


def send_notification(result: PhantomFilterResult, webhook_url: str) -> bool:
    """Deliver the notification for a candidate to Discord. I/O. Returns delivery success.

    Builds the payload via to_discord_payload and POSTs it with WEBHOOK_TIMEOUT_SECONDS.
    Returns True on a 2xx response (Discord returns 204). Returns False on any timeout,
    transport error, or non-2xx response — including 429 (rate limit) and 5xx — and never
    raises for a delivery failure (N2). The webhook URL is never logged (N5).
    """
    payload = to_discord_payload(result)
    try:
        response = httpx.post(webhook_url, json=payload, timeout=WEBHOOK_TIMEOUT_SECONDS)
        response.raise_for_status()
        return True
    except httpx.HTTPError:
        return False
