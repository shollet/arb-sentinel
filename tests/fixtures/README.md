# Test Fixtures

Captured responses from external services, used as input to unit tests.

## `odds_api_event_sample.json`

A real response from The Odds API for an ATP French Open match (Arnaldi
vs Collignon), captured on 2026-05-30. Used to test the mapper in
`tests/test_odds_api.py` without consuming API quota.

Includes 15 bookmakers, of which 2 (Betfair, Matchbook) provide both
`h2h` and `h2h_lay` markets — useful for verifying the `h2h_lay` filter.

If the API response format changes, this fixture will need to be
regenerated. The relevant endpoint is:

```
GET /v4/sports/tennis_atp_french_open/odds?regions=eu&markets=h2h&oddsFormat=decimal
```

## `odds_api_sports_sample.json`

A hand-authored representative response from The Odds API `/sports` endpoint.
Used to test `fetch_active_sports` in `tests/test_tournament_selection.py` without
consuming API quota (the `/sports` endpoint is free, but tests must remain offline).

Contains 5 entries covering the key filtering scenarios:

- 2 active tennis tournaments (`tennis_atp_french_open`, `tennis_atp_500_queens`)
- 1 inactive tennis tournament (`tennis_wta_french_open`)
- 1 active non-tennis sport (`soccer_epl`)
- 1 inactive non-tennis sport (`basketball_nba`)

The relevant endpoint is:

```
GET /v4/sports?apiKey=...
```