"""Tests for the Odds API integration."""

import json
from decimal import Decimal
from pathlib import Path

from arb_sentinel.odds_api import (
    OddsApiBookmaker,
    OddsApiEvent,
    OddsApiMarket,
    OddsApiOutcome,
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
