"""Replaceable narrow boundary for company-only supplier search."""

from __future__ import annotations

import datetime as dt
from typing import Protocol

from signals.supplier_discovery.contracts import SupplierSearchPage, SupplierSearchProfile


class SupplierDiscoveryProvider(Protocol):
    def search_page(
        self,
        profile: SupplierSearchProfile,
        *,
        page: int,
        observed_at: dt.datetime,
    ) -> SupplierSearchPage: ...
