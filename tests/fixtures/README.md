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