"""Minimal async client for the AquaIllumination local REST API.

AquaIllumination has never published documentation for this API. What is
implemented here is the small subset of endpoints that the myAI mobile app
itself uses when talking to a light on the local network, as reverse
engineered by the reef-keeping/home-automation community (see the AquaIPy
project), plus a session-login step that newer firmware requires. Only
aiohttp is used, which Home Assistant already ships, so this integration
has no external pip dependency and nothing that can fail to install.

Known endpoints (plain HTTP, no port other than 80):
    POST /login                 -> form field "pwd"=<password>; sets a
                                    session cookie on success (confirmed
                                    directly from this firmware's actual
                                    /login.html form)
    GET  /api/identity          -> serial number, firmware, product name;
                                    does not require a logged-in session
    GET  /api/colors            -> {channel_name: value_0_to_1000, ...};
                                    requires a logged-in session. Confirmed
                                    against a real fixture: a channel sitting
                                    at 66% reads back as 664 - i.e. this is
                                    tenths of a percent (0-1000), not a plain
                                    0-100 percent as earlier reverse-engineering
                                    write-ups (and an earlier version of this
                                    file) assumed.
    POST /api/colors            -> body {channel_name: value_0_to_1000}, sets
                                    one or more channels at once, same scale
                                    as the GET response
    GET  /api/schedule/enable   -> {"enable": bool}
    PUT  /api/schedule/enable   -> body {"enable": bool}

A fixture with a device password set answers a protected endpoint with
HTTP 401 and a body like {"response_code": 6} until the session cookie
from /login is presented. This client logs in automatically the first
time it hits a 401, and again any time the session appears to have
expired, so the caller never has to think about it - it just needs a
password to be configured when the fixture has one.

Because none of this is documented by AquaIllumination, a firmware update
could change or break it at any time. Use at your own risk.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from .const import REQUEST_TIMEOUT_SECONDS

_LOGGER = logging.getLogger(__name__)


class AquaIlluminationError(Exception):
    """Base error for problems talking to an AquaIllumination light."""


class AquaIlluminationConnectionError(AquaIlluminationError):
    """Raised when the light can't be reached or returns a bad response."""


class AquaIlluminationAuthError(AquaIlluminationError):
    """Raised when the fixture requires a password we don't have, or rejects it."""


class AquaIlluminationClient:
    """Talks to one AquaIllumination fixture's local HTTP API.

    `session` must be a ClientSession dedicated to this fixture (or at
    least one whose cookie jar was created with `unsafe=True`) - aiohttp's
    default cookie jar silently refuses to store cookies for plain IP
    address hosts, which is exactly what these fixtures are addressed by.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        password: str | None = None,
    ) -> None:
        self._session = session
        self._host = host
        self._base = f"http://{host}/api"
        self._password = password

    async def _login(self) -> None:
        if not self._password:
            raise AquaIlluminationAuthError(
                f"AquaIllumination light at {self._host} requires a password, "
                "but none is configured for it."
            )
        url = f"http://{self._host}/login"
        try:
            async with self._session.post(
                url,
                data={"pwd": self._password},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
            ) as resp:
                # The login endpoint answers with a plain HTML page (not
                # JSON) either way; the thing that matters is the session
                # cookie it sets on success, which the ClientSession's
                # cookie jar picks up automatically. We just drain the
                # body so the connection can be reused.
                await resp.read()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise AquaIlluminationConnectionError(
                f"Error logging in to AquaIllumination light at {self._host}: {err}"
            ) from err

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        _retried: bool = False,
    ) -> dict[str, Any]:
        url = f"{self._base}{path}"
        try:
            async with self._session.request(
                method,
                url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
            ) as resp:
                if resp.status == 401:
                    if _retried:
                        raise AquaIlluminationAuthError(
                            f"AquaIllumination light at {self._host} rejected "
                            "the configured password."
                        )
                    await resp.read()
                    await self._login()
                    return await self._request(
                        method, path, payload, _retried=True
                    )
                resp.raise_for_status()
                # The light's web server doesn't always set a JSON
                # content-type header, so don't require one.
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise AquaIlluminationConnectionError(
                f"Error talking to AquaIllumination light at {self._base}: {err}"
            ) from err

        if not isinstance(data, dict):
            raise AquaIlluminationConnectionError(
                f"Unexpected response from {url}: {data!r}"
            )
        return data

    async def get_identity(self) -> dict[str, Any]:
        """Return the fixture's identity block (serial, firmware, product)."""
        return await self._request("GET", "/identity")

    async def get_colors(self) -> dict[str, float]:
        """Return {channel_name: percent_brightness} for this fixture.

        The device reports each channel as a 0-1000 value (tenths of a
        percent); this divides by 10 so everything above this client deals
        in plain 0-100 percent, matching set_color()'s input.
        """
        data = await self._request("GET", "/colors")
        return {
            key: float(value) / 10.0
            for key, value in data.items()
            if key != "response_code"
        }

    async def set_color(self, channel: str, percent: float) -> None:
        """Set a single channel's brightness, as a 0-100 percent value.

        Converted to the device's native 0-1000 scale (tenths of a percent)
        before sending - see get_colors().
        """
        percent = max(0.0, min(100.0, percent))
        raw_value = round(percent * 10)
        await self._request("POST", "/colors", {channel: raw_value})

    async def get_schedule_enabled(self) -> bool:
        """Return whether the fixture's own on-device schedule is running."""
        data = await self._request("GET", "/schedule/enable")
        return bool(data.get("enable", True))

    async def set_schedule_enabled(self, enabled: bool) -> None:
        """Enable or disable the fixture's own on-device schedule."""
        await self._request("PUT", "/schedule/enable", {"enable": enabled})
