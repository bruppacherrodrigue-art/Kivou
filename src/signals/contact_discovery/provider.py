"""Replaceable narrow contact-discovery provider boundary."""

from __future__ import annotations

import datetime as dt
from typing import Protocol

from signals.contact_discovery.contracts import (
    ApolloEnrichedPerson,
    DecisionMakerSearchProfile,
    PeopleSearchPage,
)


class ContactDiscoveryProvider(Protocol):
    def search_people(
        self, profile: DecisionMakerSearchProfile, *, observed_at: dt.datetime
    ) -> PeopleSearchPage: ...

    def enrich_person(
        self, provider_person_id: str, *, observed_at: dt.datetime
    ) -> ApolloEnrichedPerson | None: ...
