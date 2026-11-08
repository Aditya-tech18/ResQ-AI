"""Gnani outbound calling integration.

This adapter deliberately requires an explicit provider endpoint.
No undocumented Gnani URL or response format is assumed.
"""

from dataclasses import dataclass
from typing import Any

import httpx


class GnaniConfigurationError(RuntimeError):
    """Provider configuration is incomplete."""


class GnaniCallError(RuntimeError):
    """The provider rejected or failed the call request."""


@dataclass(frozen=True)
class GnaniOutboundConfig:
    endpoint: str
    api_key: str
    timeout_seconds: float = 15.0

    def validate(self) -> None:
        if not self.endpoint.startswith("https://"):
            raise GnaniConfigurationError("Gnani outbound endpoint must use HTTPS")

        if not self.api_key.strip():
            raise GnaniConfigurationError("Gnani API key is missing")

        if self.timeout_seconds <= 0:
            raise GnaniConfigurationError("Timeout must be positive")


class GnaniOutboundClient:
    """Send provider-specific outbound requests.

    Request schema and authentication must be configured
    according to official provider documentation.
    """

    def __init__(
        self,
        config: GnaniOutboundConfig,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        config.validate()
        self.config = config
        self._client = client

    def initiate_call(
        self,
        *,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        if not payload:
            raise ValueError("Call payload cannot be empty")

        if not headers:
            raise ValueError("Provider authentication headers are required")

        client = self._client or httpx.Client(
            timeout=self.config.timeout_seconds,
            follow_redirects=False,
        )

        owns_client = self._client is None

        try:
            response = client.post(
                self.config.endpoint,
                json=payload,
                headers=headers,
            )
            response.raise_for_status()

            result = response.json()

            if not isinstance(result, dict):
                raise GnaniCallError("Provider response must be a JSON object")

            return result

        except httpx.HTTPError as exc:
            raise GnaniCallError("Outbound provider request failed") from exc

        except ValueError as exc:
            raise GnaniCallError("Provider returned invalid JSON") from exc

        finally:
            if owns_client:
                client.close()
