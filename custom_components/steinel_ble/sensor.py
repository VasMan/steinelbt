"""Live sensor values (only while "live values" is enabled in the options)."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CONCENTRATION_PARTS_PER_MILLION,
    LIGHT_LUX,
    PERCENTAGE,
    UnitOfPressure,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import protocol as p
from .const import CLASS_MULTISENSOR, product_class
from .coordinator import SteinelConfigEntry
from .entity import SteinelEntity


@dataclass(frozen=True, kw_only=True)
class SteinelSensorDescription(SensorEntityDescription):
    live: int
    multisensor_only: bool = False


SENSORS = (
    SteinelSensorDescription(
        key="brightness",
        live=p.Live.BRIGHTNESS,
        device_class=SensorDeviceClass.ILLUMINANCE,
        native_unit_of_measurement=LIGHT_LUX,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SteinelSensorDescription(
        key="temperature",
        live=p.Live.TEMPERATURE,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        multisensor_only=True,
    ),
    SteinelSensorDescription(
        key="humidity",
        live=p.Live.HUMIDITY,
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        multisensor_only=True,
    ),
    SteinelSensorDescription(
        key="co2",
        live=p.Live.CO2,
        device_class=SensorDeviceClass.CO2,
        native_unit_of_measurement=CONCENTRATION_PARTS_PER_MILLION,
        state_class=SensorStateClass.MEASUREMENT,
        multisensor_only=True,
    ),
    SteinelSensorDescription(
        key="voc",
        live=p.Live.VOC,
        state_class=SensorStateClass.MEASUREMENT,
        multisensor_only=True,
    ),
    SteinelSensorDescription(
        key="air_pressure",
        live=p.Live.AIR_PRESSURE,
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        native_unit_of_measurement=UnitOfPressure.HPA,
        state_class=SensorStateClass.MEASUREMENT,
        multisensor_only=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SteinelConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    if not coordinator.live_enabled:
        return
    info = coordinator.data.info
    multi = bool(info) and product_class(info.product_number) == CLASS_MULTISENSOR
    async_add_entities(SteinelSensor(coordinator, d) for d in SENSORS if multi or not d.multisensor_only)


class SteinelSensor(SteinelEntity, SensorEntity):
    entity_description: SteinelSensorDescription

    def __init__(self, coordinator, description: SteinelSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.live.get(self.entity_description.live)
