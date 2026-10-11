"""Steinel Bluetooth lights and sensors."""
from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import SteinelConfigEntry, SteinelCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.LIGHT, Platform.NUMBER, Platform.SELECT, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: SteinelConfigEntry) -> bool:
    coordinator = SteinelCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SteinelConfigEntry) -> bool:
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_disconnect()
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: SteinelConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
