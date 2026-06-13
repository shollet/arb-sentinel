"""Tests for tournament discovery and selection."""

import json
from pathlib import Path

import httpx
import pytest
import respx
from hypothesis import given
from hypothesis import strategies as st

from arb_sentinel.odds_api import (
    GRAND_SLAM_PRIORITY,
    ODDS_API_BASE_URL,
    OddsApiSport,
    fetch_active_sports,
    select_tournament,
)

SPORTS_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "odds_api_sports_sample.json"


def _sport(key: str, active: bool, group: str = "Tennis") -> OddsApiSport:
    return OddsApiSport(
        key=key,
        group=group,
        title=key,
        description=key,
        active=active,
        has_outrights=False,
    )


# Hypothesis strategies for building OddsApiSport objects
_tennis_key_st = st.from_regex(r"tennis_[a-z][a-z0-9_]*", fullmatch=True)
_non_tennis_key_st = st.from_regex(r"[a-z][a-z0-9_]*", fullmatch=True).filter(
    lambda k: not k.startswith("tennis_")
)
_priority_st = st.lists(_tennis_key_st)
_sport_st = st.builds(
    OddsApiSport,
    key=_tennis_key_st,
    group=st.just("Tennis"),
    title=st.just("T"),
    description=st.just("T"),
    active=st.booleans(),
    has_outrights=st.just(False),
)
_non_tennis_sport_st = st.builds(
    OddsApiSport,
    key=_non_tennis_key_st,
    group=st.just("Other"),
    title=st.just("T"),
    description=st.just("T"),
    active=st.booleans(),
    has_outrights=st.just(False),
)
_mixed_sport_st = st.one_of(_sport_st, _non_tennis_sport_st)


class TestINV1Deterministic:
    """INV1: select_tournament is deterministic — same inputs always yield the same result."""

    @given(sports=st.lists(_sport_st), priority=_priority_st)
    def test_same_inputs_produce_same_output(
        self, sports: list[OddsApiSport], priority: list[str]
    ) -> None:
        result1 = select_tournament(sports, priority)
        result2 = select_tournament(sports, priority)
        assert result1 == result2


class TestINV2TennisOnlyAndActive:
    """INV2: a non-None result is always an active tennis key present in the input."""

    @given(sports=st.lists(_sport_st), priority=_priority_st)
    def test_result_is_active_tennis_or_none(
        self, sports: list[OddsApiSport], priority: list[str]
    ) -> None:
        result = select_tournament(sports, priority)
        if result is None:
            return
        assert result.startswith("tennis_")
        matching = [s for s in sports if s.key == result]
        assert len(matching) >= 1
        assert any(s.active for s in matching)

    @given(sports=st.lists(_mixed_sport_st, min_size=1), priority=_priority_st)
    def test_non_tennis_sport_never_returned(
        self, sports: list[OddsApiSport], priority: list[str]
    ) -> None:
        result = select_tournament(sports, priority)
        if result is not None:
            assert result.startswith("tennis_")

    def test_inactive_tennis_never_returned(self) -> None:
        sports = [_sport("tennis_atp_french_open", active=False)]
        assert select_tournament(sports, GRAND_SLAM_PRIORITY) is None


class TestINV3PriorityRespected:
    """INV3: the first active priority key is always returned when one exists."""

    def test_first_active_priority_key_wins(self) -> None:
        sports = [
            _sport("tennis_atp_wimbledon", active=True),
            _sport("tennis_atp_french_open", active=True),
            _sport("tennis_atp_us_open", active=True),
        ]
        priority = ["tennis_atp_french_open", "tennis_atp_wimbledon"]
        assert select_tournament(sports, priority) == "tennis_atp_french_open"

    def test_second_priority_key_wins_when_first_inactive(self) -> None:
        sports = [
            _sport("tennis_atp_wimbledon", active=True),
            _sport("tennis_atp_french_open", active=False),
        ]
        priority = ["tennis_atp_french_open", "tennis_atp_wimbledon"]
        assert select_tournament(sports, priority) == "tennis_atp_wimbledon"

    @given(sports=st.lists(_sport_st, min_size=1), priority=_priority_st)
    def test_no_earlier_priority_key_is_active(
        self, sports: list[OddsApiSport], priority: list[str]
    ) -> None:
        result = select_tournament(sports, priority)
        if result is None or result not in priority:
            return
        result_idx = priority.index(result)
        active_keys = {s.key for s in sports if s.active and s.key.startswith("tennis_")}
        for earlier_key in priority[:result_idx]:
            assert earlier_key not in active_keys


class TestINV4DeterministicFallback:
    """INV4: when no priority key matches, fallback selects the first active tennis key by sort."""

    def test_fallback_returns_alphabetically_first_key(self) -> None:
        sports = [
            _sport("tennis_atp_z_event", active=True),
            _sport("tennis_atp_a_event", active=True),
            _sport("tennis_atp_m_event", active=True),
        ]
        assert select_tournament(sports, priority=[]) == "tennis_atp_a_event"

    def test_fallback_ignores_priority_keys_not_in_input(self) -> None:
        sports = [_sport("tennis_atp_500_queens", active=True)]
        # Grand Slams are in priority but not active → falls through to sorted fallback
        assert select_tournament(sports, GRAND_SLAM_PRIORITY) == "tennis_atp_500_queens"

    @given(sports=st.lists(_sport_st, min_size=1))
    def test_fallback_is_stable(self, sports: list[OddsApiSport]) -> None:
        active_tennis = sorted(
            [s for s in sports if s.active and s.key.startswith("tennis_")],
            key=lambda s: s.key,
        )
        result = select_tournament(sports, priority=[])
        if active_tennis:
            assert result == active_tennis[0].key
        else:
            assert result is None


class TestINV5EmptyReturnsNone:
    """INV5: when no active tennis tournament exists, select_tournament returns None."""

    def test_empty_sports_list(self) -> None:
        assert select_tournament([], GRAND_SLAM_PRIORITY) is None

    def test_all_tennis_inactive(self) -> None:
        sports = [
            _sport("tennis_atp_french_open", active=False),
            _sport("tennis_wta_french_open", active=False),
        ]
        assert select_tournament(sports, GRAND_SLAM_PRIORITY) is None

    def test_only_non_tennis_active(self) -> None:
        sports = [
            _sport("soccer_epl", active=True, group="Soccer"),
            _sport("tennis_atp_french_open", active=False),
        ]
        assert select_tournament(sports, GRAND_SLAM_PRIORITY) is None

    @given(
        sports=st.lists(
            st.builds(
                OddsApiSport,
                key=st.sampled_from(["soccer_epl", "basketball_nba", "americanfootball_nfl"]),
                group=st.just("Other"),
                title=st.just("Other Sport"),
                description=st.just("Non-tennis"),
                active=st.booleans(),
                has_outrights=st.just(False),
            )
        )
    )
    def test_no_tennis_sports_always_returns_none(self, sports: list[OddsApiSport]) -> None:
        assert select_tournament(sports, GRAND_SLAM_PRIORITY) is None


class TestFetchActiveSports:
    """Verify that fetch_active_sports makes the correct HTTP call and parses the response."""

    @respx.mock
    def test_targets_correct_url_with_api_key(self) -> None:
        sports_url = f"{ODDS_API_BASE_URL}/sports"
        route = respx.get(sports_url).mock(return_value=httpx.Response(200, json=[]))

        fetch_active_sports(api_key="fake_key")

        assert route.called
        request = route.calls.last.request
        assert request.url.params["apiKey"] == "fake_key"

    @respx.mock
    def test_parses_fixture_into_odds_api_sport_objects(self) -> None:
        sports_url = f"{ODDS_API_BASE_URL}/sports"
        fixture = json.loads(SPORTS_FIXTURE_PATH.read_text())
        respx.get(sports_url).mock(return_value=httpx.Response(200, json=fixture))

        sports = fetch_active_sports(api_key="fake_key")

        assert len(sports) == 5
        keys = {s.key for s in sports}
        assert "tennis_atp_french_open" in keys
        assert "tennis_atp_500_queens" in keys
        assert "soccer_epl" in keys

    @respx.mock
    def test_returns_empty_list_for_empty_response(self) -> None:
        respx.get(f"{ODDS_API_BASE_URL}/sports").mock(return_value=httpx.Response(200, json=[]))
        assert fetch_active_sports(api_key="fake_key") == []

    @respx.mock
    def test_raises_on_unauthorized(self) -> None:
        respx.get(f"{ODDS_API_BASE_URL}/sports").mock(
            return_value=httpx.Response(401, json={"message": "Invalid API key"})
        )
        with pytest.raises(httpx.HTTPStatusError):
            fetch_active_sports(api_key="invalid_key")
