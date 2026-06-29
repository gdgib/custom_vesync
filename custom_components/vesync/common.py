"""Common utilities for VeSync Component."""

import logging

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.helpers.entity import Entity, ToggleEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    VS_BINARY_SENSORS,
    VS_BUTTON,
    VS_FANS,
    VS_HUMIDIFIERS,
    VS_LIGHTS,
    VS_NUMBERS,
    VS_SENSORS,
    VS_SWITCHES,
)

_LOGGER = logging.getLogger(__name__)


_CONFIG_DICT_ATTR_MAP = {
    "levels": "fan_levels",
    "mist_levels": "mist_levels",
    "warm_mist_levels": "warm_mist_levels",
    "modes": "modes",
}


def has_feature(device, dictionary, attribute):
    """Return the detail of the attribute."""
    if dictionary in ("details", "config"):
        return getattr(device.state, attribute, None) is not None
    elif dictionary == "_config_dict":
        device_attr = _CONFIG_DICT_ATTR_MAP.get(attribute)
        return device_attr is not None and len(getattr(device, device_attr, ())) > 0
    return getattr(device, dictionary, {}).get(attribute, None) is not None


async def async_process_devices(hass, manager):
    """Assign devices to proper component."""
    devices = {
        VS_SWITCHES: [],
        VS_FANS: [],
        VS_LIGHTS: [],
        VS_SENSORS: [],
        VS_HUMIDIFIERS: [],
        VS_NUMBERS: [],
        VS_BINARY_SENSORS: [],
        VS_BUTTON: [],
    }

    all_devices = list(manager.devices)
    redacted = async_redact_data(
        [d.to_dict() for d in all_devices],
        ["cid", "uuid", "mac_id"],
    )

    _LOGGER.debug("Found the following devices: %s", redacted)

    if len(manager.devices) == 0:
        _LOGGER.error("Could not find any device to add in %s", redacted)

    for purifier in manager.devices.air_purifiers:
        devices[VS_FANS].append(purifier)
        devices[VS_NUMBERS].append(purifier)
        devices[VS_SWITCHES].append(purifier)
        devices[VS_SENSORS].append(purifier)
        devices[VS_BINARY_SENSORS].append(purifier)
        devices[VS_LIGHTS].append(purifier)

    for fan in manager.devices.fans:
        devices[VS_FANS].append(fan)
        devices[VS_NUMBERS].append(fan)
        devices[VS_SWITCHES].append(fan)
        devices[VS_SENSORS].append(fan)
        devices[VS_BINARY_SENSORS].append(fan)
        devices[VS_LIGHTS].append(fan)

    for humidifier in manager.devices.humidifiers:
        devices[VS_HUMIDIFIERS].append(humidifier)
        devices[VS_NUMBERS].append(humidifier)
        devices[VS_SWITCHES].append(humidifier)
        devices[VS_SENSORS].append(humidifier)
        devices[VS_BINARY_SENSORS].append(humidifier)
        devices[VS_LIGHTS].append(humidifier)

    if manager.devices.bulbs:
        devices[VS_LIGHTS].extend(manager.devices.bulbs)

    if manager.devices.outlets:
        devices[VS_SWITCHES].extend(manager.devices.outlets)
        devices[VS_SENSORS].extend(manager.devices.outlets)

    for switch in manager.devices.switches:
        devices[VS_LIGHTS if switch.is_dimmable() else VS_SWITCHES].append(switch)

    for airfryer in manager.devices.air_fryers:
        _LOGGER.warning(
            "Found air fryer %s, support in progress.\n", airfryer.device_name
        )
        devices[VS_SENSORS].append(airfryer)
        devices[VS_BINARY_SENSORS].append(airfryer)
        devices[VS_SWITCHES].append(airfryer)
        devices[VS_BUTTON].append(airfryer)

    return devices


class VeSyncBaseEntity(CoordinatorEntity, Entity):
    """Base class for VeSync Entity Representations."""

    def __init__(self, device, coordinator) -> None:
        """Initialize the VeSync device."""
        self.device = device
        super().__init__(coordinator, context=device)

    @property
    def base_unique_id(self):
        """Return the ID of this device."""
        if isinstance(self.device.sub_device_no, int):
            return f"{self.device.cid}{str(self.device.sub_device_no)}"
        return self.device.cid

    @property
    def unique_id(self):
        """Return the ID of this device."""
        # The unique_id property may be overridden in subclasses, such as in sensors. Maintaining base_unique_id allows
        # us to group related entities under a single device.
        return self.base_unique_id

    @property
    def base_name(self):
        """Return the name of the device."""
        return self.device.device_name

    @property
    def name(self):
        """Return the name of the entity (may be overridden)."""
        return self.base_name

    @property
    def available(self) -> bool:
        """Return True if device is available."""
        return self.device.state.connection_status == "online"

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.base_unique_id)},
            "name": self.base_name,
            "model": self.device.device_type,
            "manufacturer": "VeSync",
            "sw_version": self.device.current_firm_version,
        }

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )


class VeSyncDevice(VeSyncBaseEntity, ToggleEntity):
    """Base class for VeSync Device Representations."""

    def __init__(self, device, coordinator) -> None:
        """Initialize the VeSync device."""
        super().__init__(device, coordinator)

    @property
    def is_on(self):
        """Return True if device is on."""
        return self.device.is_on

    async def async_turn_off(self, **kwargs):
        """Turn the device off."""
        await self.device.turn_off()
