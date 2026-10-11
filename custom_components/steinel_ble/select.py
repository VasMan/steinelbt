"""Operating mode of a Steinel sensor light."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import protocol as p
from .const import CONF_OFF_DURATION, CONF_ON_DURATION, DEFAULT_DURATION, LIGHT_TYPES, product_type
from .coordinator import SteinelConfigEntry
from .entity import SteinelEntity

OPTIONS = {"sensor": p.Mode.SENSOR, "on": p.Mode.ON, "off": p.Mode.OFF}


async def async_setup_entry(
    hass: HomeAssistant, entry: SteinelConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    info = coordinator.data.info
    if info and product_type(info.product_number) in LIGHT_TYPES:
        async_add_entities([SteinelModeSelect(coordinator)])


class SteinelModeSelect(SteinelEntity, SelectEntity):
    _attr_assumed_state = True
    _attr_options = list(OPTIONS)

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "mode")

    @property
    def current_option(self) -> str | None:
        return next((k for k, v in OPTIONS.items() if v == self.coordinator.data.mode), None)

    async def async_select_option(self, option: str) -> None:
        options = self.coordinator.config_entry.options
        seconds = {
            "on": options.get(CONF_ON_DURATION, DEFAULT_DURATION),
            "off": options.get(CONF_OFF_DURATION, DEFAULT_DURATION),
        }.get(option)
        await self.coordinator.async_set_mode(OPTIONS[option], seconds)
