"""Switch platform for AquaIllumination: one on-device-schedule toggle per fixture.

Turning this off hands full control of that fixture to whatever sets its
channel brightness next (Home Assistant, the myAI app, etc.) and stops the
fixture's own programmed ramp from overriding it. Turning it back on
resumes the fixture's own schedule/presets as normal.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AquaIlluminationCoordinator
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AquaIlluminationCoordinator = hass.data[DOMAIN][
        entry.entry_id
    ].coordinator
    async_add_entities([AquaIlluminationScheduleSwitch(coordinator, entry)])


class AquaIlluminationScheduleSwitch(
    CoordinatorEntity[AquaIlluminationCoordinator], SwitchEntity
):
    _attr_icon = "mdi:calendar-clock"

    def __init__(
        self, coordinator: AquaIlluminationCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        fixture_name = entry.data[CONF_NAME]
        self._attr_name = f"{fixture_name} Schedule"
        self._attr_unique_id = f"{entry.entry_id}_schedule"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=fixture_name,
            manufacturer="AquaIllumination",
            model="Hydra HD",
        )

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("schedule_enabled", True))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.client.set_schedule_enabled(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.client.set_schedule_enabled(False)
        await self.coordinator.async_request_refresh()
