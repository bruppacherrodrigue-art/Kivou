"""Shared, client-safe boundaries for SaaS transactional email."""

from signals.transactional_email.links import preferences_url, reset_url, signal_url

__all__ = ("preferences_url", "reset_url", "signal_url")
