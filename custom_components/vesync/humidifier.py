"""Support for VeSync humidifiers."""

import logging
from collections.abc import Mapping
from typing import Any

from homeassistant.components.humidifier import HumidifierEntity
from homeassistant.components.humidifier.const import (
    MODE_AUTO,
    MODE_NORMAL,
    MODE_SLEEP,
    HumidifierEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from pyvesync.base_devices.humidifier_base import VeSyncHumidifier

from .common import VeSyncDevice
from .const import (
    DOMAIN,
    VS_DISCOVERY,
    VS_HUMIDIFIERS,
    VS_MODE_AUTO,
    VS_MODE_HUMIDITY,
    VS_MODE_MANUAL,
    VS_MODE_SLEEP,
    VS_TO_HA_ATTRIBUTES,
)

_LOGGER = logging.getLogger(__name__)


MAX_HUMIDITY = 80
MIN_HUMIDITY = 30


VS_TO_HA_MODE_MAP = {
    VS_MODE_AUTO: MODE_AUTO,
    VS_MODE_HUMIDITY: MODE_AUTO,
    VS_MODE_MANUAL: MODE_NORMAL,
    VS_MODE_SLEEP: MODE_SLEEP,
}

HA_TO_VS_MODE_MAP = {v: k for k, v in VS_TO_HA_MODE_MAP.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the VeSync humidifier platform."""

    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]

    @callback
    def discover(devices):
        """Add new devices to platform."""
        _setup_entities(devices, async_add_entities, coordinator)

    config_entry.async_on_unload(
        async_dispatcher_connect(hass, VS_DISCOVERY.format(VS_HUMIDIFIERS), discover)
    )

    _setup_entities(
        hass.data[DOMAIN][config_entry.entry_id][VS_HUMIDIFIERS],
        async_add_entities,
        coordinator,
    )


@callback
def _setup_entities(devices, async_add_entities, coordinator):
    """Check if device is online and add entity."""
    async_add_entities(
        [VeSyncHumidifierHA(dev, coordinator) for dev in devices],
        update_before_add=True,
    )


def _get_ha_mode(vs_mode: str) -> str | None:
    ha_mode = VS_TO_HA_MODE_MAP.get(vs_mode)
    if ha_mode is None:
        _LOGGER.warning("Unknown mode '%s'", vs_mode)
    return ha_mode


def _get_vs_mode(ha_mode: str) -> str | None:
    vs_mode = HA_TO_VS_MODE_MAP.get(ha_mode)
    if vs_mode is None:
        _LOGGER.warning("Unknown mode '%s'", ha_mode)
    return vs_mode


class VeSyncHumidifierHA(VeSyncDevice, HumidifierEntity):
    """Representation of a VeSync humidifier."""

    _attr_max_humidity = MAX_HUMIDITY
    _attr_min_humidity = MIN_HUMIDITY

    def __init__(self, humidifier: VeSyncHumidifier, coordinator) -> None:
        """Initialize the VeSync humidifier device."""
        super().__init__(humidifier, coordinator)
        self.smarthumidifier = humidifier

    @property
    def available_modes(self) -> list[str]:
        """Return the available mist modes."""
        modes = []
        for vs_mode in self.smarthumidifier.mist_modes:
            ha_mode = _get_ha_mode(vs_mode)

            if ha_mode is None:
                continue

            modes.append(ha_mode)

        return modes

    @property
    def supported_features(self):
        """Flag supported features."""
        return HumidifierEntityFeature.MODES

    @property
    def target_humidity(self) -> int:
        """Return the humidity we try to reach."""
        return self.smarthumidifier.state.auto_target_humidity

    @property
    def mode(self) -> str | None:
        """Get the current preset mode."""
        return _get_ha_mode(self.smarthumidifier.state.mode)

    @property
    def is_on(self) -> bool:
        """Return True if humidifier is on."""
        return self.smarthumidifier.is_on  # device_status is always on

    @property
    def unique_info(self) -> str:
        """Return the ID of this humidifier."""
        return self.smarthumidifier.uuid

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        """Return the state attributes of the humidifier."""
        attr = {}
        for k, v in self.smarthumidifier.state.to_dict().items():
            if k in VS_TO_HA_ATTRIBUTES:
                attr[VS_TO_HA_ATTRIBUTES[k]] = v
            elif k in self.state_attributes:
                attr[f"vs_{k}"] = v
            else:
                attr[k] = v
        return attr

    async def async_set_humidity(self, humidity: int) -> None:
        """Set the target humidity of the device."""
        if humidity not in range(self.min_humidity, self.max_humidity + 1):
            raise ValueError(
                "{humidity} is not between {self.min_humidity} and {self.max_humidity} (inclusive)"
            )
        if not await self.smarthumidifier.set_humidity(humidity):
            raise ValueError("An error occurred while setting humidity.")

    async def async_set_mode(self, mode: str) -> None:
        """Set the mode of the device."""
        if mode not in self.available_modes:
            raise ValueError(
                "{mode} is not one of the valid available modes: {self.available_modes}"
            )
        vs_mode = _get_vs_mode(mode)
        if not await self.smarthumidifier.set_mode(vs_mode):
            raise ValueError("An error occurred while setting mode.")

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the device on."""
        if not await self.smarthumidifier.turn_on():
            raise ValueError("An error occurred while turning on.")

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the device off."""
        if not await self.smarthumidifier.turn_off():
            raise ValueError("An error occurred while turning off.")
