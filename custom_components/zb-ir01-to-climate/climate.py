from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    HVAC_MODE_OFF, HVAC_MODE_HEAT, HVAC_MODE_COOL, HVAC_MODE_AUTO, HVAC_MODE_DRY, HVAC_MODE_FAN_ONLY,
    SUPPORT_TARGET_TEMPERATURE, SUPPORT_FAN_MODE
)
from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.const import TEMP_CELSIUS
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change

import logging

_LOGGER = logging.getLogger(__name__)

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    if discovery_info is None:
        return
    sensor_entity_id = discovery_info.get("sensor_entity_id")
    async_add_entities([MyACClimateEntity(hass, sensor_entity_id)])

class MyACClimateEntity(ClimateEntity):
    def __init__(self, hass, sensor_entity_id):
        self.hass = hass
        self._sensor_entity_id = sensor_entity_id
        self._attr_temperature_unit = TEMP_CELSIUS
        self._state = {}

        # Subscribe to changes in the sensor
        self._sensor_unsub = async_track_state_change(
            self.hass, self._sensor_entity_id, self.async_sensor_state_listener
        )

    async def async_sensor_state_listener(self, entity_id, old_state, new_state):
        if new_state is None:
            return
        self._state = self.parse_sensor_data(new_state.state)
        self.async_write_ha_state()  # Update the state in Home Assistant

    @property
    def name(self):
        return "My AC Controller"

    @property
    def hvac_mode(self):
        if self._state.get('switch', '') == '01':
            return HVAC_MODE_OFF
        elif self._state.get('mode', '') == '00':
            return HVAC_MODE_AUTO
        elif self._state.get('mode', '') == '01':
            return HVAC_MODE_COOL
        elif self._state.get('mode', '') == '02':
            return HVAC_MODE_DRY
        elif self._state.get('mode', '') == '03':
            return HVAC_MODE_FAN_ONLY
        elif self._state.get('mode', '') == '04':
            return HVAC_MODE_HEAT

    @property
    def hvac_modes(self):
        return [HVAC_MODE_OFF, HVAC_MODE_COOL, HVAC_MODE_HEAT, HVAC_MODE_AUTO, HVAC_MODE_DRY, HVAC_MODE_FAN_ONLY]

    @property
    def current_temperature(self):
        return self._state.get('temperature', 0)

    @property
    def target_temperature(self):
        return self._state.get('temperature', 0)

    @property
    def fan_mode(self):
        return self._state.get('air_volume', 'auto')

    @property
    def fan_modes(self):
        return ["auto", "low", "medium", "high"]

    @property
    def supported_features(self):
        return SUPPORT_TARGET_TEMPERATURE | SUPPORT_FAN_MODE


    def verify_checksum(self, data):
        try:
            # Convert the string into a list of integers, excluding the last two characters (checksum)
            input_data = [int(data[i:i + 2], 16) for i in range(0, len(data) - 2, 2)]
            # Extract the checksum from the last two characters of the data string
            received_checksum = int(data[-2:], 16)
            # Calculate the XOR of all bytes
            calculated_checksum = 0
            for byte in input_data:
                calculated_checksum ^= byte
            # Compare the received checksum with the calculated checksum
            return received_checksum == calculated_checksum
        except ValueError:
            # Handle invalid data format
            return False

    def parse_sensor_data(self, data):
        if data[0:2] != "08":
            return {}
        if not self.verify_checksum(data):
            _LOGGER.error(f"Invalid checksum of data '{data}'")
            return {}
        try:
            switch = data[2:4]
            mode = data[4:6]
            # Check if the temperature data slice is correct
            temp_hex = data[6:8]
            temperature = int(temp_hex, 16) + 16
            air_volume = ["auto", "low", "medium", "high"][int(data[8:10], 16)]
            return {"switch": switch, "mode": mode, "temperature": temperature, "air_volume": air_volume}
        except ValueError as e:
            _LOGGER.error(f"Error parsing sensor data '{data}': {e}")
            return {}

    async def async_will_remove_from_hass(self):
        # Unsubscribe from sensor's state changes when entity is removed
        if self._sensor_unsub:
            self._sensor_unsub()
