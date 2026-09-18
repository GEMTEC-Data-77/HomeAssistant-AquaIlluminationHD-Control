"""The AquaIllumination integration.

Talks directly to one or more AquaIllumination Hydra / Prime HD fixtures
over their local, undocumented HTTP API (see aqua_client.py). Add the
integration once per physical fixture from Settings > Devices & Services.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .aqua_client import AquaIlluminationClient, AquaIlluminationConnectionError
from .const import DOMAIN, SCAN_INTERVAL_SECONDS

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.LIGHT, Platform.SWITCH]


class AquaIlluminationCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls one fixture for its current channel levels and schedule state."""

    def __init__(
        self, hass: HomeAssistant, client: AquaIlluminationClient, fixture_name: str
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"AquaIllumination ({fixture_name})",
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            colors = await self.client.get_colors()
            schedule_enabled = await self.client.get_schedule_enabled()
        except AquaIlluminationConnectionError as err:
            raise UpdateFailed(str(err)) from err
        return {"colors": colors, "schedule_enabled": schedule_enabled}


@dataclass
class AquaIlluminationRuntimeData:
    """Everything set up for one config entry, so it can be torn down cleanly."""

    session: aiohttp.ClientSession
    coordinator: AquaIlluminationCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one AquaIllumination fixture from a config entry."""
    # A session dedicated to this one fixture, with a cookie jar that
    # allows cookies for plain IP-address hosts (aiohttp's default jar
    # silently drops them, which would break the login-session flow these
    # fixtures use). Using Home Assistant's shared clientsession here
    # would also risk cookies for this fixture never actually persisting
    # between calls, since that shared session isn't guaranteed to keep a
    # cookie jar at all. Owning our own session means we're also in charge
    # of closing it below.
    session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))

    client = AquaIlluminationClient(
        session, entry.data[CONF_HOST], entry.data.get(CONF_PASSWORD)
    )
    coordinator = AquaIlluminationCoordinator(hass, client, entry.data[CONF_NAME])

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await session.close()
        raise

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = AquaIlluminationRuntimeData(
        session=session, coordinator=coordinator
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        runtime_data: AquaIlluminationRuntimeData = hass.data[DOMAIN].pop(
            entry.entry_id
        )
        await runtime_data.session.close()
    return unload_ok
