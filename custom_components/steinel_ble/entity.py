"""Base entity for Steinel Bluetooth devices."""
from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, product_name
from .coordinator import SteinelCoordinator


class SteinelEntity(CoordinatorEntity[SteinelCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: SteinelCoordinator, key: str) -> None:
        super().__init__(coordinator)
        info = coordinator.data.info
        self._attr_unique_id = f"{coordinator.address}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            connections={(CONNECTION_BLUETOOTH, coordinator.address)},
            manufacturer="Steinel",
            name=coordinator.config_entry.title,
            model=product_name(info.product_number) if info else None,
            model_id=str(info.product_number) if info else None,
            sw_version=info.software_version if info else None,
            hw_version=str(info.hardware_version) if info else None,
        )
