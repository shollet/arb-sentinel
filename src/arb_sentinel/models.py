"""Domain models for the arbitrage detection system.

These models define the vocabulary of the business domain: bookmakers offer
quotes on the outcomes of an event. The models intentionally carry no
business logic — that lives in the arbitrage module as pure functions.

Iteration 0 scope: only the moneyline / head-to-head (h2h) market type is
modeled. An Event therefore directly contains its outcomes and quotes.
When additional market types are introduced (spreads, totals, etc.), a
Market entity will be inserted between Event and Outcomes to align with
the standard sports betting taxonomy used by APIs like The Odds API.
"""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class Bookmaker(BaseModel):
    """A source that offers quotes on event outcomes."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, description="Display name of the bookmaker.")


class Outcome(BaseModel):
    """A possible result of an event.

    Outcomes within an event must be mutually exclusive and collectively
    exhaustive: exactly one outcome will occur.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, description="Display name of the outcome.")


class Quote(BaseModel):
    """A bookmaker's offered price on a specific outcome.

    Decimal odds represent the total payout multiplier: a stake of 1 returns
    `decimal_odds` if the outcome wins, including the stake itself.
    """

    model_config = ConfigDict(frozen=True)

    outcome: Outcome
    bookmaker: Bookmaker
    decimal_odds: Decimal = Field(
        gt=Decimal(1),
        description="Decimal odds offered by the bookmaker. Must be strictly greater than 1.",
    )


class Event(BaseModel):
    """A sporting event with mutually exclusive outcomes and quotes from one or more bookmakers.

    For Iteration 0, an Event represents a single match restricted to the
    moneyline / h2h market. A future Market entity will mediate between
    Event and Outcomes when additional bet types are needed.
    """

    model_config = ConfigDict(frozen=True)

    description: str = Field(min_length=1, description="Human-readable description of the event.")
    outcomes: list[Outcome] = Field(min_length=2, description="At least two outcomes are required.")
    quotes: list[Quote] = Field(
        min_length=1, description="At least one quote is required to reason about the event."
    )
