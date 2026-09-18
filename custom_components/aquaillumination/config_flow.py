"""Config flow for the AquaIllumination integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult

from .aqua_client import (
    AquaIlluminationAuthError,
    AquaIlluminationClient,
    AquaIlluminationConnectionError,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_NAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class AquaIlluminationConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for a single AquaIllumination fixture.

    Add this integration once per physical light (run it 3 times for 3
    Hydra 52 HDs), each with that light's own IP address on the local
    network, a name you choose for it, and the password you set for it in
    the myAI app (the same one the fixture's own web page asks for).
    """

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            password = user_input[CONF_PASSWORD]

            # A throwaway session just for this validation step. It needs
            # its own cookie jar with unsafe=True because aiohttp's default
            # jar refuses to store cookies for plain IP-address hosts,
            # which is exactly what these fixtures are addressed by.
            async with aiohttp.ClientSession(
                cookie_jar=aiohttp.CookieJar(unsafe=True)
            ) as session:
                client = AquaIlluminationClient(session, host, password)

                try:
                    identity = await client.get_identity()
                except AquaIlluminationConnectionError:
                    _LOGGER.debug(
                        "Could not reach AquaIllumination light at %s", host
                    )
                    errors["base"] = "cannot_connect"
                else:
                    try:
                        await client.get_colors()
                    except AquaIlluminationAuthError:
                        errors["base"] = "invalid_auth"
                    except AquaIlluminationConnectionError:
                        errors["base"] = "cannot_connect"

            if not errors:
                unique_id = str(
                    identity.get("serial_number")
                    or identity.get("serial")
                    or host
                )
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={
                        CONF_HOST: host,
                        CONF_NAME: user_input[CONF_NAME],
                        CONF_PASSWORD: password,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
