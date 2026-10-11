"""Configuration parameters of Steinel devices."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import LIGHT_LUX, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import protocol as p
from .coordinator import SteinelConfigEntry
from .entity import SteinelEntity


@dataclass(frozen=True, kw_only=True)
class SteinelNumberDescription(NumberEntityDescription):
    param: int
    size: int = 2


NUMBERS = (
    SteinelNumberDescription(
        key="stay_on_time",
        param=p.Param.STAY_ON_TIME,
        native_min_value=5,
        native_max_value=15300,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=NumberDeviceClass.DURATION,
    ),
    SteinelNumberDescription(
        key="light_level",
        param=p.Param.LIGHT_LEVEL,
        native_min_value=2,
        native_max_value=2000,
        native_step=1,
        native_unit_of_measurement=LIGHT_LUX,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SteinelConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(SteinelNumber(coordinator, d) for d in NUMBERS if d.param in coordinator.data.config)


class SteinelNumber(SteinelEntity, NumberEntity):
    entity_description: SteinelNumberDescription
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, description: SteinelNumberDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.config.get(self.entity_description.param)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_write_param(
            self.entity_description.param, int(value), self.entity_description.size
        )
