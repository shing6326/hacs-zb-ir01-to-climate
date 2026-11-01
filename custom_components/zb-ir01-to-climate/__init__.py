"""ZB-IR01 to climate — YAML setup and discovery for the climate platform."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, discovery
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol

DOMAIN = "zb-ir01-to-climate"

DEVICE_SCHEMA = vol.Schema(
    {
        vol.Required("ir01_entity_id"): cv.string,
        vol.Optional("climate_id"): cv.string,
        vol.Required("climate_name"): cv.string,
        # Optional brand-specific status-report quirk flags (see climate.py).
        # No default= here — mutable/callable defaults are unreliable across
        # voluptuous/HA versions; async_setup uses conf.get(...) or [].
        vol.Optional("status_quirks"): vol.All(cv.ensure_list, [cv.string]),
        # Optional vertical swing_mode list (ClimateEntityFeature.SWING_MODE).
        # Omitted → full protocol default set in climate.py.
        # Empty list [] → disable SWING_MODE.
        # Exactly [on, off] → map those labels to auto-sweep key 0x05.
        vol.Optional("swing_modes"): vol.All(cv.ensure_list, [cv.string]),
        # Optional independent horizontal swing list (HA 2024.12+).
        # Omitted or empty → no SWING_HORIZONTAL_MODE feature.
        # Non-empty → enable only the listed horizontal modes.
        vol.Optional("swing_horizontal_modes"): vol.All(cv.ensure_list, [cv.string]),
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.All(cv.ensure_list, [DEVICE_SCHEMA]),
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up zb-ir01-to-climate from configuration.yaml and load climate platforms."""
    configurations = config.get(DOMAIN) or []

    for conf in configurations:
        discovery_info = {
            "ir01_entity_id": conf["ir01_entity_id"],
            "climate_id": conf.get("climate_id"),
            "climate_name": conf["climate_name"],
            "status_quirks": list(conf.get("status_quirks") or []),
            # Preserve omitted vs [] for swing_modes (None = use climate default).
            "swing_modes": (
                list(conf["swing_modes"]) if "swing_modes" in conf else None
            ),
            # Omitted and [] both mean horizontal swing disabled.
            "swing_horizontal_modes": list(conf.get("swing_horizontal_modes") or []),
        }
        hass.async_create_task(
            discovery.async_load_platform(
                hass, "climate", DOMAIN, discovery_info, config
            )
        )
    return True
