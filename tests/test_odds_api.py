"""Tests for the Odds API integration."""

import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx

from arb_sentinel.odds_api import (
    ODDS_API_BASE_URL,
    OddsApiBookmaker,
    OddsApiEvent,
    OddsApiMarket,
    OddsApiOutcome,
    fetch_events,
    to_domain_event,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "odds_api_event_sample.json"


def _load_fixture() -> dict:
    """Load the captured API event response from disk."""
    return json.loads(FIXTURE_PATH.read_text())


class TestOddsApiSchemas:
    """Verify that Pydantic schemas correctly parse a real API response."""

    def test_event_parses_without_error(self) -> None:
        """A real API event response is parsed by OddsApiEvent without raising."""
        event = OddsApiEvent.model_validate(_load_fixture())

        assert event.home_team == "Matteo Arnaldi"
        assert event.away_team == "Raphael Collignon"
        assert event.sport_key == "tennis_atp_french_open"

    def test_event_has_expected_bookmakers(self) -> None:
        """The fixture event has 15 bookmakers including Pinnacle and Betfair."""
        event = OddsApiEvent.model_validate(_load_fixture())

        bookmaker_titles = {b.title for b in event.bookmakers}
        assert "Pinnacle" in bookmaker_titles
        assert "Betfair" in bookmaker_titles
        assert len(event.bookmakers) == 15

    def test_betfair_offers_both_h2h_and_h2h_lay(self) -> None:
        """Betfair (an exchange) is captured as offering both market types."""
        event = OddsApiEvent.model_validate(_load_fixture())

        betfair = next(b for b in event.bookmakers if b.title == "Betfair")
        market_keys = {m.key for m in betfair.markets}
        assert market_keys == {"h2h", "h2h_lay"}

    def test_prices_are_coerced_to_decimal(self) -> None:
        """JSON float prices are parsed as Decimal at validation time."""
        event = OddsApiEvent.model_validate(_load_fixture())

        first_bookmaker = event.bookmakers[0]
        first_market = first_bookmaker.markets[0]
        first_outcome = first_market.outcomes[0]

        assert isinstance(first_outcome.price, Decimal)

    def test_outcome_name_matches_player_name(self) -> None:
        """Outcome names match the player names exactly."""
        event = OddsApiEvent.model_validate(_load_fixture())

        pinnacle = next(b for b in event.bookmakers if b.title == "Pinnacle")
        h2h_market = next(m for m in pinnacle.markets if m.key == "h2h")
        outcome_names = {o.name for o in h2h_market.outcomes}

        assert outcome_names == {"Matteo Arnaldi", "Raphael Collignon"}

    def test_individual_schemas_can_be_constructed(self) -> None:
        """Each schema class can be constructed independently for unit testing."""
        outcome = OddsApiOutcome(name="Federer", price=Decimal("2.10"))
        assert outcome.name == "Federer"
        assert outcome.price == Decimal("2.10")

        market = OddsApiMarket(
            key="h2h",
            last_update="2026-05-30T18:00:00Z",
            outcomes=[outcome],
        )
        assert market.key == "h2h"
        assert len(market.outcomes) == 1

        bookmaker = OddsApiBookmaker(
            key="pinnacle",
            title="Pinnacle",
            last_update="2026-05-30T18:00:00Z",
            markets=[market],
        )
        assert bookmaker.title == "Pinnacle"
        assert len(bookmaker.markets) == 1


def _build_api_event(
    bookmakers: list[OddsApiBookmaker],
    home_team: str = "Player A",
    away_team: str = "Player B",
    commence_time: str = "2099-01-01T00:00:00Z",
) -> OddsApiEvent:
    """Build a minimal API event for mapper tests.

    Defaults to commence_time far in the future so the in-play filter
    does not reject the event during testing.
    """
    return OddsApiEvent(
        id="test_event_id",
        sport_key="tennis_atp_french_open",
        sport_title="ATP French Open",
        commence_time=commence_time,
        home_team=home_team,
        away_team=away_team,
        bookmakers=bookmakers,
    )


def _build_api_bookmaker(
    title: str,
    h2h_prices: dict[str, str] | None = None,
    h2h_lay_prices: dict[str, str] | None = None,
) -> OddsApiBookmaker:
    """Build a minimal API bookmaker with optional h2h and h2h_lay markets."""
    markets = []
    if h2h_prices:
        markets.append(
            OddsApiMarket(
                key="h2h",
                last_update="2026-05-30T18:00:00Z",
                outcomes=[
                    OddsApiOutcome(name=name, price=Decimal(price))
                    for name, price in h2h_prices.items()
                ],
            )
        )
    if h2h_lay_prices:
        markets.append(
            OddsApiMarket(
                key="h2h_lay",
                last_update="2026-05-30T18:00:00Z",
                outcomes=[
                    OddsApiOutcome(name=name, price=Decimal(price))
                    for name, price in h2h_lay_prices.items()
                ],
            )
        )
    return OddsApiBookmaker(
        key=title.lower().replace(" ", "_"),
        title=title,
        last_update="2026-05-30T18:00:00Z",
        markets=markets,
    )


class TestMapper:
    """Verify that to_domain_event correctly maps API events to domain events."""

    def test_real_fixture_maps_to_valid_event(self) -> None:
        """The captured fixture maps to a valid domain Event."""
        api_event = OddsApiEvent.model_validate(_load_fixture())

        event = to_domain_event(api_event)

        assert event.description == "Matteo Arnaldi vs Raphael Collignon"
        assert len(event.outcomes) == 2
        outcome_names = {o.name for o in event.outcomes}
        assert outcome_names == {"Matteo Arnaldi", "Raphael Collignon"}

    def test_h2h_lay_markets_are_filtered_out(self) -> None:
        """Bookmakers offering both h2h and h2h_lay contribute only h2h quotes."""
        api_event = OddsApiEvent.model_validate(_load_fixture())

        event = to_domain_event(api_event)

        betfair_quotes = [q for q in event.quotes if q.bookmaker.name == "Betfair"]
        assert len(betfair_quotes) == 2

    def test_description_composes_from_home_and_away_team(self) -> None:
        """Event description follows the 'home vs away' convention."""
        api_event = _build_api_event(
            home_team="Federer",
            away_team="Nadal",
            bookmakers=[
                _build_api_bookmaker("Pinnacle", h2h_prices={"Federer": "2.10", "Nadal": "1.85"})
            ],
        )

        event = to_domain_event(api_event)

        assert event.description == "Federer vs Nadal"

    def test_bookmaker_with_only_h2h_lay_is_excluded(self) -> None:
        """A bookmaker offering only h2h_lay is excluded entirely."""
        api_event = _build_api_event(
            bookmakers=[
                _build_api_bookmaker(
                    "Pinnacle",
                    h2h_prices={"Player A": "2.10", "Player B": "1.85"},
                ),
                _build_api_bookmaker(
                    "ExchangeOnly",
                    h2h_lay_prices={"Player A": "2.20", "Player B": "1.80"},
                ),
            ]
        )

        event = to_domain_event(api_event)

        bookmaker_names = {q.bookmaker.name for q in event.quotes}
        assert bookmaker_names == {"Pinnacle"}

    def test_outcome_objects_are_shared_across_quotes(self) -> None:
        """The same outcome name produces the same Outcome object across bookmakers."""
        api_event = _build_api_event(
            bookmakers=[
                _build_api_bookmaker("Pinnacle", h2h_prices={"A": "2.10", "B": "1.85"}),
                _build_api_bookmaker("Bet365", h2h_prices={"A": "2.05", "B": "1.90"}),
            ]
        )

        event = to_domain_event(api_event)

        outcomes_for_a = {q.outcome for q in event.quotes if q.outcome.name == "A"}
        assert len(outcomes_for_a) == 1

    def test_prices_propagate_as_decimal(self) -> None:
        """Decimal prices from API schemas reach domain Quote unchanged."""
        api_event = _build_api_event(
            bookmakers=[_build_api_bookmaker("Pinnacle", h2h_prices={"A": "2.10", "B": "1.85"})]
        )

        event = to_domain_event(api_event)

        for quote in event.quotes:
            assert isinstance(quote.decimal_odds, Decimal)

    def test_event_with_insufficient_quotes_raises(self) -> None:
        """An event with zero h2h quotes raises ValueError."""
        api_event = _build_api_event(
            bookmakers=[
                _build_api_bookmaker(
                    "ExchangeOnly",
                    h2h_lay_prices={"A": "2.20", "B": "1.80"},
                ),
            ]
        )

        with pytest.raises(ValueError, match="insufficient quotes"):
            to_domain_event(api_event)

    def test_in_play_event_raises(self) -> None:
        """An event that has already started raises ValueError.

        In-play odds change constantly and bookmakers update at different
        speeds, creating apparent arbitrages that are not exploitable.
        Only pre-match events are supported.
        """
        api_event = _build_api_event(
            commence_time="2020-01-01T00:00:00Z",  # in the past
            bookmakers=[_build_api_bookmaker("Pinnacle", h2h_prices={"A": "2.10", "B": "2.00"})],
        )

        with pytest.raises(ValueError, match="already started"):
            to_domain_event(api_event)

    def test_mapped_event_is_consumable_by_arbitrage_module(self) -> None:
        """The Event produced by the mapper works with arbitrage detection."""
        from arb_sentinel.arbitrage import find_arbitrage_opportunity

        api_event = _build_api_event(
            bookmakers=[
                _build_api_bookmaker("Pinnacle", h2h_prices={"A": "2.10", "B": "2.00"}),
            ]
        )

        event = to_domain_event(api_event)
        opportunity = find_arbitrage_opportunity(event, total_stake=Decimal("1000"))

        # T = 1/2.10 + 1/2.00 = 0.976 -> arbitrage exists
        assert opportunity is not None
        assert opportunity.guaranteed_profit > Decimal(0)


def _expected_url(sport_key: str) -> str:
    """The URL pattern fetch_events targets for a given sport_key."""
    return f"{ODDS_API_BASE_URL}/sports/{sport_key}/odds"


class TestHttpClient:
    """Verify that fetch_events makes the right HTTP call and processes responses correctly.

    All HTTP traffic is intercepted by respx; no real API call is made.
    """

    @respx.mock
    def test_fetch_events_targets_correct_url_and_params(self) -> None:
        """fetch_events sends a GET to the expected URL with required params."""
        sport_key = "tennis_atp_french_open"
        route = respx.get(_expected_url(sport_key)).mock(return_value=httpx.Response(200, json=[]))

        fetch_events(sport_key=sport_key, api_key="fake_key")

        assert route.called
        request = route.calls.last.request
        assert request.url.params["apiKey"] == "fake_key"
        assert request.url.params["regions"] == "eu"
        assert request.url.params["markets"] == "h2h"
        assert request.url.params["oddsFormat"] == "decimal"

    @respx.mock
    def test_fetch_events_returns_mapped_domain_events(self) -> None:
        """A successful API response is parsed and mapped to domain Events."""
        sport_key = "tennis_atp_french_open"
        respx.get(_expected_url(sport_key)).mock(
            return_value=httpx.Response(200, json=[_load_fixture()])
        )

        events = fetch_events(sport_key=sport_key, api_key="fake_key")

        assert len(events) == 1
        assert events[0].description == "Matteo Arnaldi vs Raphael Collignon"

    @respx.mock
    def test_fetch_events_returns_empty_list_when_api_returns_empty(self) -> None:
        """An empty API response produces an empty list, not an error."""
        sport_key = "tennis_atp_french_open"
        respx.get(_expected_url(sport_key)).mock(return_value=httpx.Response(200, json=[]))

        events = fetch_events(sport_key=sport_key, api_key="fake_key")

        assert events == []

    @respx.mock
    def test_fetch_events_skips_unmappable_events(self) -> None:
        """Events that cannot be mapped are silently skipped."""
        sport_key = "tennis_atp_french_open"
        valid_event = _load_fixture()
        unmappable_event = {
            "id": "broken_event",
            "sport_key": "tennis_atp_french_open",
            "sport_title": "ATP French Open",
            "commence_time": "2099-01-01T00:00:00Z",
            "home_team": "Player X",
            "away_team": "Player Y",
            "bookmakers": [],
        }
        respx.get(_expected_url(sport_key)).mock(
            return_value=httpx.Response(200, json=[valid_event, unmappable_event])
        )

        events = fetch_events(sport_key=sport_key, api_key="fake_key")

        assert len(events) == 1
        assert events[0].description == "Matteo Arnaldi vs Raphael Collignon"

    @respx.mock
    def test_fetch_events_skips_in_play_events(self) -> None:
        """Events that have already started are skipped silently."""
        sport_key = "tennis_atp_french_open"
        in_play_event = {
            **_load_fixture(),
            "commence_time": "2020-01-01T00:00:00Z",  # in the past
        }
        respx.get(_expected_url(sport_key)).mock(
            return_value=httpx.Response(200, json=[in_play_event])
        )

        events = fetch_events(sport_key=sport_key, api_key="fake_key")

        assert events == []

    @respx.mock
    def test_fetch_events_raises_on_unauthorized(self) -> None:
        """A 401 response raises httpx.HTTPStatusError for the caller to handle."""
        sport_key = "tennis_atp_french_open"
        respx.get(_expected_url(sport_key)).mock(
            return_value=httpx.Response(401, json={"message": "Invalid API key"})
        )

        with pytest.raises(httpx.HTTPStatusError):
            fetch_events(sport_key=sport_key, api_key="invalid_key")

    @respx.mock
    def test_fetch_events_raises_on_rate_limit(self) -> None:
        """A 429 response raises httpx.HTTPStatusError."""
        sport_key = "tennis_atp_french_open"
        respx.get(_expected_url(sport_key)).mock(
            return_value=httpx.Response(429, json={"message": "Rate limit exceeded"})
        )

        with pytest.raises(httpx.HTTPStatusError):
            fetch_events(sport_key=sport_key, api_key="fake_key")
