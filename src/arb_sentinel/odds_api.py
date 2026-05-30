"""Integration with The Odds API.

Provides Pydantic schemas mirroring the JSON response structure of
The Odds API v4, a mapper function from API schemas to domain models,
and an HTTP client wrapper.

See docs/design/odds-api-integration.md for the complete specification.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from arb_sentinel.models import Bookmaker, Event, Outcome, Quote


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

    Raises ValueError if the resulting event has fewer than 2 quotes,
    which is insufficient for arbitrage analysis.
    """
    description = f"{api_event.home_team} vs {api_event.away_team}"

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
