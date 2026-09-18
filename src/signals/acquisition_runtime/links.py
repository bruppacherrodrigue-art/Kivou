"""Provider-independent configuration for signed public attribution links."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from signals.acquisition_runtime.contracts import RuntimeExecutionConfigurationError

_PUBLIC_APP_URL = "KIVOU_PUBLIC_APP_URL"
_ATTRIBUTION_KEY = "KIVOU_ATTRIBUTION_HMAC_KEY"
_ATTRIBUTION_KEY_VERSION = "KIVOU_ATTRIBUTION_HMAC_KEY_VERSION"


@dataclass(frozen=True)
class RuntimeLinkConfiguration:
    public_app_url: str
    attribution_hmac_key: bytes = field(repr=False)
    attribution_key_version: str

    def __post_init__(self) -> None:
        allowed = {"https://staging.kivou.eu", "https://kivou.eu"}
        parsed = urlsplit(self.public_app_url)
        if (
            parsed.scheme != "https"
            or parsed.port is not None
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or self.public_app_url.rstrip("/") not in allowed
            or len(self.attribution_hmac_key) < 16
            or not self.attribution_key_version
            or len(self.attribution_key_version) > 100
        ):
            raise RuntimeExecutionConfigurationError("LINKS_NOT_CONFIGURED")
        object.__setattr__(self, "public_app_url", self.public_app_url.rstrip("/"))


def _required(source: Mapping[str, str], name: str) -> str:
    value = source.get(name)
    if value is None or not value.strip():
        raise RuntimeExecutionConfigurationError("LINKS_NOT_CONFIGURED")
    return value.strip()


def load_runtime_link_config(
    environ: Mapping[str, str] | None = None,
) -> RuntimeLinkConfiguration:
    source = os.environ if environ is None else environ
    try:
        return RuntimeLinkConfiguration(
            public_app_url=_required(source, _PUBLIC_APP_URL),
            attribution_hmac_key=_required(source, _ATTRIBUTION_KEY).encode("utf-8"),
            attribution_key_version=_required(source, _ATTRIBUTION_KEY_VERSION),
        )
    except RuntimeExecutionConfigurationError:
        raise
    except (TypeError, ValueError):
        raise RuntimeExecutionConfigurationError("LINKS_NOT_CONFIGURED") from None


__all__ = ["RuntimeLinkConfiguration", "load_runtime_link_config"]
