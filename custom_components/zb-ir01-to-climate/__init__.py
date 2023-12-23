from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, discovery
import voluptuous as vol

DOMAIN = "zb-ir01-to-climate"

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required("ir01_entity_id"): cv.string,
        vol.Optional("climate_id"): cv.string,  # climate_id is optional
        vol.Required("climate_name"): cv.string,
    }),
}, extra=vol.ALLOW_EXTRA)

async def async_setup(hass: HomeAssistant, config: dict):
    # Retrieve configuration
    conf = config[DOMAIN]
    ir01_entity_id = conf.get("ir01_entity_id")
    climate_id = conf.get("climate_id")
    climate_name = conf.get("climate_name")

    # Pass the retrieved configuration to the climate platform
    hass.async_create_task(
        discovery.async_load_platform(
            hass, "climate", DOMAIN,
            {
                "ir01_entity_id": ir01_entity_id,
                "climate_id": climate_id,
                "climate_name": climate_name
            }, config
        )
    )
    return True
