"""Light platform for AquaIllumination.

Creates, per fixture:

- One light entity per color channel the fixture itself reports (e.g.
  Cool White, Royal Blue, Deep Red, Green, Violet, UV - whatever the
  device actually returns from /api/colors). This is what lets you
  control channels individually, and it's also what makes cross-fixture
  grouping easy: create a Home Assistant "Light Group" helper out of the
  same-named channel entity from each of your three fixtures (e.g. the
  three "Cool White" entities) to get one slider that drives all three at
  once. See the README for the group/scene walkthrough.

- One "<fixture> Overall" light entity: a single flat 0-100% control that
  sets every channel on that fixture to the same value in one move. Its
  brightness is its own independent, persisted value - it does NOT track
  live channel state, so if you later nudge one channel by hand, this
  entity keeps showing whatever you last set here rather than snapping to
  match. It's a plain light entity (not a separate "number" helper) so it
  shows up alongside the channel lights under the same device.

Every entity here only supports brightness (0-100% mapped to HA's 0-255
scale). These fixtures don't expose true on/off latching per channel -
"off" here just means 0%.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AquaIlluminationCoordinator
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AquaIlluminationCoordinator = hass.data[DOMAIN][
        entry.entry_id
    ].coordinator
    fixture_name = entry.data[CONF_NAME]

    channels = sorted(coordinator.data["colors"].keys())
    if not channels:
        _LOGGER.warning(
            "AquaIllumination fixture %s reported no color channels", fixture_name
        )

    entities: list[LightEntity] = [
        AquaIlluminationChannelLight(coordinator, entry, fixture_name, channel)
        for channel in channels
    ]
    entities.append(AquaIlluminationOverallLight(coordinator, entry, fixture_name))

    async_add_entities(entities)


def _device_info(entry: ConfigEntry, fixture_name: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=fixture_name,
        manufacturer="AquaIllumination",
        model="Hydra HD",
    )


class AquaIlluminationChannelLight(CoordinatorEntity[AquaIlluminationCoordinator], LightEntity):
    """One controllable color channel on one fixture."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: AquaIlluminationCoordinator,
        entry: ConfigEntry,
        fixture_name: str,
        channel: str,
    ) -> None:
        super().__init__(coordinator)
        self._channel = channel
        self._attr_name = f"{fixture_name} {channel.replace('_', ' ').title()}"
        self._attr_unique_id = f"{entry.entry_id}_{channel}"
        self._attr_device_info = _device_info(entry, fixture_name)

    @property
    def _percent(self) -> float:
        return float(self.coordinator.data["colors"].get(self._channel, 0.0))

    @property
    def available(self) -> bool:
        return super().available and self._channel in self.coordinator.data.get(
            "colors", {}
        )

    @property
    def is_on(self) -> bool:
        return self._percent > 0

    @property
    def brightness(self) -> int:
        return round(self._percent / 100 * 255)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"channel": self._channel, "percent": round(self._percent, 1)}

    async def async_turn_on(self, **kwargs: Any) -> None:
        if (brightness := kwargs.get("brightness")) is not None:
            percent = round((brightness / 255) * 100, 1)
        else:
            percent = 100.0
        await self.coordinator.client.set_color(self._channel, percent)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.client.set_color(self._channel, 0.0)
        await self.coordinator.async_request_refresh()


class AquaIlluminationOverallLight(
    CoordinatorEntity[AquaIlluminationCoordinator], RestoreEntity, LightEntity
):
    """A single flat-percentage control covering every channel on one fixture.

    This entity's on/off state and brightness are its own, restored across
    Home Assistant restarts, and are not derived from the live channel
    readings the way the per-channel lights are - it only ever changes
    when you (or an automation/scene) set it directly.
    """

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_icon = "mdi:brightness-percent"

    def __init__(
        self,
        coordinator: AquaIlluminationCoordinator,
        entry: ConfigEntry,
        fixture_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_name = f"{fixture_name} Overall"
        self._attr_unique_id = f"{entry.entry_id}_overall"
        self._attr_device_info = _device_info(entry, fixture_name)
        self._attr_is_on = False
        self._attr_brightness = 255

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._attr_is_on = last_state.state == "on"
            last_brightness = last_state.attributes.get("brightness")
            if last_brightness is not None:
                self._attr_brightness = int(last_brightness)

    async def async_turn_on(self, **kwargs: Any) -> None:
        if (brightness := kwargs.get("brightness")) is not None:
            self._attr_brightness = brightness
        percent = round((self._attr_brightness / 255) * 100, 1)
        for channel in self.coordinator.data.get("colors", {}):
            await self.coordinator.client.set_color(channel, percent)
        self._attr_is_on = True
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        for channel in self.coordinator.data.get("colors", {}):
            await self.coordinator.client.set_color(channel, 0.0)
        self._attr_is_on = False
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
