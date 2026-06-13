"""Integration with The Odds API.

Provides Pydantic schemas mirroring the JSON response structure of
The Odds API v4, a mapper function from API schemas to domain models,
and an HTTP client wrapper.

See docs/design/odds-api-integration.md for the complete specification.
"""

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from decimal import Decimal

import httpx
from pydantic import BaseModel, ConfigDict

from arb_sentinel.models import Bookmaker, Event, Outcome, Quote

ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4"

# Grand Slams first — best bookmaker coverage and most simultaneous matches.
# The selection logic does not depend on these exact spellings; they are a
# configurable preference. Only tennis_atp_french_open is verified from the
# IT0 fixture; others are confirmed against the live /sports response.
GRAND_SLAM_PRIORITY: list[str] = [
    "tennis_atp_aus_open",
    "tennis_wta_aus_open",
    "tennis_atp_french_open",
    "tennis_wta_french_open",
    "tennis_atp_wimbledon",
    "tennis_wta_wimbledon",
    "tennis_atp_us_open",
    "tennis_wta_us_open",
]


class OddsApiSport(BaseModel):
    """A competition entry from the /sports endpoint. Frozen, mirrors the API shape."""

    model_config = ConfigDict(frozen=True)

    key: str
    group: str
    title: str
    description: str
    active: bool
    has_outrights: bool


class OddsApiOutcome(BaseModel):
    """A single outcome (name, price) within a market on a bookmaker.

    Mirrors the API field-by-field. The `price` is decimal odds, coerced
    from the JSON float to Decimal at parse time.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    price: Decimal


class OddsApiMarket(BaseModel):
    """A market offered by a bookmaker on an event.

    The `key` field identifies the market type (e.g., `h2h` for moneyline,
    `h2h_lay` for exchange lay markets). The mapper filters on this field.
    """

    model_config = ConfigDict(frozen=True)

    key: str
    last_update: datetime
    outcomes: list[OddsApiOutcome]


class OddsApiBookmaker(BaseModel):
    """A bookmaker offering markets on an event.

    The `title` is the display name (e.g., `"Pinnacle"`); the `key` is a
    slug (e.g., `"pinnacle"`). Our domain uses the title.
    """

    model_config = ConfigDict(frozen=True)

    key: str
    title: str
    last_update: datetime
    markets: list[OddsApiMarket]


class OddsApiEvent(BaseModel):
    """A single event (match) with quotes from one or more bookmakers.

    Mirrors the top-level structure of an entry in The Odds API's
    /v4/sports/{sport_key}/odds endpoint response.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    sport_key: str
    sport_title: str
    commence_time: datetime
    home_team: str
    away_team: str
    bookmakers: list[OddsApiBookmaker]


def to_domain_event(api_event: OddsApiEvent) -> Event:
    """Map a single API event to a domain Event.

    Keeps only `h2h` markets; silently drops `h2h_lay` and any future
    non-h2h market type. Bookmakers offering no h2h market are excluded
    entirely.

    Raises ValueError if:
    - The event has already started (in-play). In-play odds change
      constantly and bookmakers update at different speeds, producing
      apparent arbitrages that are not actually exploitable. Only
      pre-match events are supported.
    - The resulting event has fewer than 2 quotes (insufficient for
      arbitrage analysis).
    """
    description = f"{api_event.home_team} vs {api_event.away_team}"

    if api_event.commence_time <= datetime.now(UTC):
        raise ValueError(
            f"Event '{description}' has already started "
            f"(commence_time={api_event.commence_time.isoformat()}); "
            f"in-play events are not supported."
        )

    outcomes_by_name: dict[str, Outcome] = {}
    quotes: list[Quote] = []

    for api_bookmaker in api_event.bookmakers:
        h2h_markets = [m for m in api_bookmaker.markets if m.key == "h2h"]
        if not h2h_markets:
            continue

        bookmaker = Bookmaker(name=api_bookmaker.title)

        for market in h2h_markets:
            for api_outcome in market.outcomes:
                if api_outcome.name not in outcomes_by_name:
                    outcomes_by_name[api_outcome.name] = Outcome(name=api_outcome.name)
                outcome = outcomes_by_name[api_outcome.name]

                quotes.append(
                    Quote(
                        outcome=outcome,
                        bookmaker=bookmaker,
                        decimal_odds=api_outcome.price,
                    )
                )

    if len(quotes) < 2:
        raise ValueError(
            f"Event '{description}' has insufficient quotes for arbitrage "
            f"analysis (got {len(quotes)}, need at least 2)."
        )

    return Event(
        description=description,
        outcomes=list(outcomes_by_name.values()),
        quotes=quotes,
    )


def fetch_events(sport_key: str, api_key: str) -> list[Event]:
    """Fetch all events for the given tournament from The Odds API.

    Returns domain Event objects ready for arbitrage detection. Events
    that cannot be mapped (in-play, insufficient quotes) are silently
    skipped so a single unusable event does not prevent the others from
    being returned.

    Raises httpx.HTTPStatusError on non-2xx responses (rate limit,
    invalid key, network errors, etc.). The caller decides how to react.
    """
    url = f"{ODDS_API_BASE_URL}/sports/{sport_key}/odds"
    params = {
        "apiKey": api_key,
        "regions": "eu",
        "markets": "h2h",
        "oddsFormat": "decimal",
    }

    response = httpx.get(url, params=params)
    response.raise_for_status()

    domain_events: list[Event] = []
    for raw_event in response.json():
        api_event = OddsApiEvent.model_validate(raw_event)
        try:
            domain_events.append(to_domain_event(api_event))
        except ValueError:
            continue

    return domain_events


def fetch_active_sports(api_key: str) -> list[OddsApiSport]:
    """Fetch the competitions list from The Odds API /sports endpoint.

    Does not count against the usage quota. Raises httpx.HTTPStatusError
    on non-2xx responses; the caller decides how to react.
    """
    response = httpx.get(f"{ODDS_API_BASE_URL}/sports", params={"apiKey": api_key})
    response.raise_for_status()
    return [OddsApiSport.model_validate(item) for item in response.json()]


def select_tournament(
    active_sports: Iterable[OddsApiSport],
    priority: Sequence[str],
) -> str | None:
    """The single tennis tournament sport_key to observe, or None. Pure and deterministic.

    Filters to active tennis tournaments (key starts with 'tennis_'), then:
    - returns the first key in priority order that is active; else
    - returns the first active tennis key in stable (sorted) order; else
    - returns None (no tennis tournament active, cycle spends 0 credits).
    """
    active_tennis = sorted(
        (s for s in active_sports if s.active and s.key.startswith("tennis_")),
        key=lambda s: s.key,
    )
    if not active_tennis:
        return None
    active_keys = {s.key for s in active_tennis}
    for key in priority:
        if key in active_keys:
            return key
    return active_tennis[0].key
