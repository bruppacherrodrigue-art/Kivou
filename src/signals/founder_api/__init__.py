"""Private Founder Console surface, isolated from the customer SaaS."""

from signals.founder_api.app import create_founder_app
from signals.founder_api.config import FounderApiConfig

__all__ = ["FounderApiConfig", "create_founder_app"]
