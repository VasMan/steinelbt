"""Light override for Steinel sensor lights.

Steinel lights are sensor driven; Bluetooth can only override the sensor for a limited time
("on for n seconds" / "off for n seconds"). The device does not report which mode is active,
so the state shown here is the last command sent.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import protocol as p
from .const import CONF_OFF_DURATION, CONF_ON_DURATION, DEFAULT_DURATION, LIGHT_TYPES, product_type
from .coordinator import SteinelConfigEntry
from .entity import SteinelEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: SteinelConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    info = coordinator.data.info
    if info and product_type(info.product_number) in LIGHT_TYPES:
        async_add_entities([SteinelLight(coordinator)])


class SteinelLight(SteinelEntity, LightEntity):
    _attr_name = None
    _attr_assumed_state = True
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "light")

    @property
    def is_on(self) -> bool | None:
        mode = self.coordinator.data.mode
        return None if mode in (None, p.Mode.SENSOR) else mode == p.Mode.ON

    async def async_turn_on(self, **kwargs: Any) -> None:
        seconds = self.coordinator.config_entry.options.get(CONF_ON_DURATION, DEFAULT_DURATION)
        await self.coordinator.async_set_mode(p.Mode.ON, seconds)

    async def async_turn_off(self, **kwargs: Any) -> None:
        seconds = self.coordinator.config_entry.options.get(CONF_OFF_DURATION, DEFAULT_DURATION)
        await self.coordinator.async_set_mode(p.Mode.OFF, seconds)
