"""Motion detection (only while "live values" is enabled in the options)."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import protocol as p
from .coordinator import SteinelConfigEntry
from .entity import SteinelEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: SteinelConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    if entry.runtime_data.live_enabled:
        async_add_entities([SteinelMotion(entry.runtime_data)])


class SteinelMotion(SteinelEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.MOTION

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "motion")

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.data.live.get(p.Live.MOTION)
        return None if value is None else bool(value)
