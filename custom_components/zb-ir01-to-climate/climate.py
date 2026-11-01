"""ZB-IR01 climate entity — Zigbee IR AC protocol mapped to Home Assistant ClimateEntity.

Command codes follow Zhiyi Tech Zigbee IR remote protocol (device type 0x01 = AC):
  frame: 86 01 <key_id> <value> 00 <xor>

Exposes HVAC / fan / vertical+horizontal swing / manual swing (key 0x06) /
preset modes (sleep, eco, boost). See HA_LIMITS.md for protocol keys that ClimateEntity
cannot represent and for status-report gaps.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ATTR_HVAC_MODE,
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    FAN_TOP,
    HVACMode,
    PRESET_BOOST,
    PRESET_ECO,
    PRESET_NONE,
    PRESET_SLEEP,
    SWING_HORIZONTAL,
    SWING_OFF,
    SWING_ON,
    SWING_VERTICAL,
    ClimateEntityFeature,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity

# Optional HA 2024.12+ independent horizontal swing
try:
    from homeassistant.components.climate.const import (  # type: ignore
        SWING_HORIZONTAL_OFF,
        SWING_HORIZONTAL_ON,
    )
except ImportError:  # pragma: no cover - older Core
    SWING_HORIZONTAL_ON = SWING_ON
    SWING_HORIZONTAL_OFF = SWING_OFF

try:
    _SWING_HORIZONTAL_FEATURE = ClimateEntityFeature.SWING_HORIZONTAL_MODE
except AttributeError:  # pragma: no cover - older Core
    _SWING_HORIZONTAL_FEATURE = 0

_LOGGER = logging.getLogger(__name__)

# Custom fan labels for protocol levels beyond HA's built-in constants.
# Protocol key 4: auto, low, mid, high, strong, hurricane, super
FAN_STRONG = "strong"
FAN_HURRICANE = "hurricane"
FAN_SUPER = "super"  # also accept FAN_TOP as alias

# Vertical swing (protocol key 7) — used as ClimateEntity.swing_mode
SWING_VERT_UP = "up"
SWING_VERT_MIDDLE = "middle"
SWING_VERT_DOWN = "down"
SWING_VERT_UP_MIDDLE = "up_middle"
SWING_VERT_MIDDLE_MIDDLE = "middle_middle"
SWING_VERT_MIDDLE_DOWN = "middle_down"
SWING_VERT_AUTO = "auto"
SWING_VERT_POS = tuple(f"position_{i}" for i in range(1, 6))  # 1..5

# Horizontal swing (protocol key 8) — used as swing_horizontal_mode when available
SWING_HORIZ_LEFT = "left"
SWING_HORIZ_MIDDLE = "middle"
SWING_HORIZ_RIGHT = "right"
SWING_HORIZ_LEFT_MIDDLE = "left_middle"
SWING_HORIZ_MIDDLE_RIGHT = "middle_right"
SWING_HORIZ_MIDDLE_MIDDLE = "middle_middle"
SWING_HORIZ_AUTO = "auto"
SWING_HORIZ_POS = tuple(f"position_{i}" for i in range(1, 8))  # 1..7

# Combined / legacy auto-sweep (protocol key 5) exposed as vertical modes for brands
# that only implement auto-sweep rather than directional vanes.
SWING_AUTO_SWEEP_ON = "auto_sweep"
SWING_AUTO_SWEEP_OFF = "auto_sweep_off"

# Manual swing (protocol key 6) — generic step swing used by some code libraries
# that do not expose directional vertical/horizontal vanes. Mapped into swing_mode.
SWING_MANUAL_ON = "manual"
SWING_MANUAL_OFF = "manual_off"
SWING_MANUAL_POS = tuple(f"manual_{i}" for i in range(1, 5))  # 1..4

# Custom preset labels beyond HA built-ins (protocol sleep levels 1–3).
PRESET_SLEEP_1 = "sleep_1"
PRESET_SLEEP_2 = "sleep_2"
PRESET_SLEEP_3 = "sleep_3"


def _xor_frame(key_id: int, value: int, cmd: int = 0x86, device_type: int = 0x01) -> str:
    """Build a 6-byte IR command hex string with XOR checksum (no spaces)."""
    reserved = 0x00
    parts = [cmd, device_type, key_id, value, reserved]
    checksum = 0
    for b in parts:
        checksum ^= b
    return "".join(f"{b:02x}" for b in (*parts, checksum))


# Protocol key IDs (Table 7)
_KEY_POWER = 0x00
_KEY_MODE = 0x01
_KEY_TEMP = 0x02
_KEY_FAN = 0x04
_KEY_AUTO_SWING = 0x05
_KEY_MANUAL_SWING = 0x06
_KEY_SWING_VERT = 0x07
_KEY_SWING_HORIZ = 0x08
_KEY_BOOST = 0x09  # 强劲
_KEY_AUX_HEAT = 0x0A  # 辅热 — documented, not mapped to HA climate (see HA_LIMITS.md)
_KEY_SLEEP = 0x0B  # 睡眠
_KEY_ECO = 0x0E  # 节能

# HVAC modes — protocol key 1 values (0=auto,1=cool,2=dry,3=fan,4=heat)
# OFF is power key value 1; power-on is sent separately when leaving OFF.
HVAC_MODE_CODES: dict[str, str] = {
    HVACMode.AUTO: _xor_frame(_KEY_MODE, 0),
    HVACMode.COOL: _xor_frame(_KEY_MODE, 1),
    HVACMode.DRY: _xor_frame(_KEY_MODE, 2),
    HVACMode.FAN_ONLY: _xor_frame(_KEY_MODE, 3),
    HVACMode.HEAT: _xor_frame(_KEY_MODE, 4),
    HVACMode.OFF: _xor_frame(_KEY_POWER, 1),
}

# Index order matches status-report mode nibble (section 3.10)
HVAC_MODE_BY_STATUS_INDEX: list[HVACMode] = [
    HVACMode.AUTO,
    HVACMode.COOL,
    HVACMode.DRY,
    HVACMode.FAN_ONLY,
    HVACMode.HEAT,
]

POWER_ON_CODE = _xor_frame(_KEY_POWER, 0)

TEMPERATURE_CODES: dict[str, str] = {
    str(temp): _xor_frame(_KEY_TEMP, temp - 16) for temp in range(16, 33)
}

# Fan — protocol key 4 (Table 7 / Appendix 7.1). Status report only feeds back 0..3.
FAN_MODE_CODES: dict[str, str] = {
    FAN_AUTO: _xor_frame(_KEY_FAN, 0),
    FAN_LOW: _xor_frame(_KEY_FAN, 1),
    FAN_MEDIUM: _xor_frame(_KEY_FAN, 2),
    FAN_HIGH: _xor_frame(_KEY_FAN, 3),
    FAN_STRONG: _xor_frame(_KEY_FAN, 4),
    FAN_HURRICANE: _xor_frame(_KEY_FAN, 5),
    FAN_SUPER: _xor_frame(_KEY_FAN, 6),
    # HA built-in alias for the top documented speed
    FAN_TOP: _xor_frame(_KEY_FAN, 6),
}

FAN_MODE_BY_STATUS_INDEX: list[str] = [
    FAN_AUTO,
    FAN_LOW,
    FAN_MEDIUM,
    FAN_HIGH,
    FAN_STRONG,
    FAN_HURRICANE,
    FAN_SUPER,
]

# Vertical swing — protocol key 7 (Appendix values; authoritative over the prose list)
SWING_MODE_CODES: dict[str, str] = {
    SWING_ON: _xor_frame(_KEY_SWING_VERT, 0),  # on
    SWING_OFF: _xor_frame(_KEY_SWING_VERT, 1),  # off
    SWING_VERT_UP: _xor_frame(_KEY_SWING_VERT, 2),
    SWING_VERT_MIDDLE: _xor_frame(_KEY_SWING_VERT, 3),
    SWING_VERT_DOWN: _xor_frame(_KEY_SWING_VERT, 4),
    SWING_VERT_UP_MIDDLE: _xor_frame(_KEY_SWING_VERT, 5),
    SWING_VERT_MIDDLE_MIDDLE: _xor_frame(_KEY_SWING_VERT, 6),
    SWING_VERT_MIDDLE_DOWN: _xor_frame(_KEY_SWING_VERT, 7),
    SWING_VERT_AUTO: _xor_frame(_KEY_SWING_VERT, 8),
    # Legacy HA constant used by earlier builds of this integration
    SWING_VERTICAL: _xor_frame(_KEY_SWING_VERT, 8),
    **{name: _xor_frame(_KEY_SWING_VERT, 8 + i) for i, name in enumerate(SWING_VERT_POS, start=1)},
    # Protocol key 5 (auto-sweep) — optional for remotes without directional vanes
    SWING_AUTO_SWEEP_ON: _xor_frame(_KEY_AUTO_SWING, 0),
    SWING_AUTO_SWEEP_OFF: _xor_frame(_KEY_AUTO_SWING, 1),
    # Protocol key 6 (manual swing) — on/off + fixed positions 1..4
    SWING_MANUAL_ON: _xor_frame(_KEY_MANUAL_SWING, 0),
    SWING_MANUAL_OFF: _xor_frame(_KEY_MANUAL_SWING, 1),
    **{
        name: _xor_frame(_KEY_MANUAL_SWING, 1 + i)
        for i, name in enumerate(SWING_MANUAL_POS, start=1)
    },
}

# Horizontal swing — protocol key 8
SWING_HORIZONTAL_MODE_CODES: dict[str, str] = {
    SWING_HORIZONTAL_ON: _xor_frame(_KEY_SWING_HORIZ, 0),
    SWING_HORIZONTAL_OFF: _xor_frame(_KEY_SWING_HORIZ, 1),
    SWING_HORIZ_LEFT: _xor_frame(_KEY_SWING_HORIZ, 2),
    SWING_HORIZ_MIDDLE: _xor_frame(_KEY_SWING_HORIZ, 3),
    SWING_HORIZ_RIGHT: _xor_frame(_KEY_SWING_HORIZ, 4),
    SWING_HORIZ_LEFT_MIDDLE: _xor_frame(_KEY_SWING_HORIZ, 5),
    SWING_HORIZ_MIDDLE_RIGHT: _xor_frame(_KEY_SWING_HORIZ, 6),
    SWING_HORIZ_MIDDLE_MIDDLE: _xor_frame(_KEY_SWING_HORIZ, 7),
    SWING_HORIZ_AUTO: _xor_frame(_KEY_SWING_HORIZ, 8),
    # Legacy constant (previously stuffed into swing_modes)
    SWING_HORIZONTAL: _xor_frame(_KEY_SWING_HORIZ, 8),
    **{
        name: _xor_frame(_KEY_SWING_HORIZ, 8 + i)
        for i, name in enumerate(SWING_HORIZ_POS, start=1)
    },
}

# Presets — protocol keys 0x09 (boost), 0x0B (sleep), 0x0E (eco).
# HA ClimateEntity allows only one active preset_mode at a time. Selecting a preset
# sends that key's "on" (or sleep level) frame; selecting none / switching presets
# also sends the previous preset's "off" frame when known.
# Frames use computed XOR (appendix 7.1 has OCR typos for eco-off / mute / light-off).
PRESET_MODE_CODES: dict[str, str] = {
    PRESET_NONE: _xor_frame(_KEY_SLEEP, 1),  # default "clear" uses sleep-off; see set_preset_mode
    PRESET_SLEEP: _xor_frame(_KEY_SLEEP, 0),
    PRESET_SLEEP_1: _xor_frame(_KEY_SLEEP, 2),
    PRESET_SLEEP_2: _xor_frame(_KEY_SLEEP, 3),
    PRESET_SLEEP_3: _xor_frame(_KEY_SLEEP, 4),
    PRESET_ECO: _xor_frame(_KEY_ECO, 0),
    PRESET_BOOST: _xor_frame(_KEY_BOOST, 0),
}

# Off frames used when leaving a preset (or selecting none).
PRESET_OFF_CODES: dict[str, str] = {
    PRESET_SLEEP: _xor_frame(_KEY_SLEEP, 1),
    PRESET_SLEEP_1: _xor_frame(_KEY_SLEEP, 1),
    PRESET_SLEEP_2: _xor_frame(_KEY_SLEEP, 1),
    PRESET_SLEEP_3: _xor_frame(_KEY_SLEEP, 1),
    PRESET_ECO: _xor_frame(_KEY_ECO, 1),
    PRESET_BOOST: _xor_frame(_KEY_BOOST, 1),
}


# Modes shown in the UI (exclude FAN_TOP duplicate alias from the list)
FAN_MODES_UI: list[str] = [
    FAN_AUTO,
    FAN_LOW,
    FAN_MEDIUM,
    FAN_HIGH,
    FAN_STRONG,
    FAN_HURRICANE,
    FAN_SUPER,
]

SWING_MODES_UI: list[str] = [
    SWING_OFF,
    SWING_ON,
    SWING_VERT_AUTO,
    SWING_VERT_UP,
    SWING_VERT_MIDDLE,
    SWING_VERT_DOWN,
    SWING_VERT_UP_MIDDLE,
    SWING_VERT_MIDDLE_MIDDLE,
    SWING_VERT_MIDDLE_DOWN,
    *SWING_VERT_POS,
    SWING_AUTO_SWEEP_ON,
    SWING_AUTO_SWEEP_OFF,
    SWING_MANUAL_ON,
    SWING_MANUAL_OFF,
    *SWING_MANUAL_POS,
]

PRESET_MODES_UI: list[str] = [
    PRESET_NONE,
    PRESET_SLEEP,
    PRESET_SLEEP_1,
    PRESET_SLEEP_2,
    PRESET_SLEEP_3,
    PRESET_ECO,
    PRESET_BOOST,
]

SWING_HORIZONTAL_MODES_UI: list[str] = [
    SWING_HORIZONTAL_OFF,
    SWING_HORIZONTAL_ON,
    SWING_HORIZ_AUTO,
    SWING_HORIZ_LEFT,
    SWING_HORIZ_MIDDLE,
    SWING_HORIZ_RIGHT,
    SWING_HORIZ_LEFT_MIDDLE,
    SWING_HORIZ_MIDDLE_RIGHT,
    SWING_HORIZ_MIDDLE_MIDDLE,
    *SWING_HORIZ_POS,
]

# ---------------------------------------------------------------------------
# Optional status-report quirks (brand-specific malformed 0x08 frames).
# NOT applied by default. Enable via discovery_info / config:
#   status_quirks:
#     - remap_ff_power_as_on   # needed when power must be 00/01 only (e.g. Panasonic
#                             # 0xFF → 0x00/ON before the strict power check)
#     - remap_ff_power_mode    # Toshiba-style: power=0xFF + mode=0x00 → ON + fan_only
#     - clamp_ff_fan_to_low    # MHI-style: fan=0xFF → low
# ---------------------------------------------------------------------------
STATUS_QUIRK_REMAP_FF_POWER_AS_ON = "remap_ff_power_as_on"
STATUS_QUIRK_REMAP_FF_POWER_MODE = "remap_ff_power_mode"
STATUS_QUIRK_CLAMP_FF_FAN_TO_LOW = "clamp_ff_fan_to_low"
KNOWN_STATUS_QUIRKS = {
    STATUS_QUIRK_REMAP_FF_POWER_AS_ON,
    STATUS_QUIRK_REMAP_FF_POWER_MODE,
    STATUS_QUIRK_CLAMP_FF_FAN_TO_LOW,
}


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    if discovery_info is None:
        return
    ir01_entity_id = discovery_info.get("ir01_entity_id")
    climate_name = discovery_info.get("climate_name")
    climate_id = discovery_info.get("climate_id")
    status_quirks = discovery_info.get("status_quirks") or config.get("status_quirks") or []
    async_add_entities(
        [
            ZBACClimateEntity(
                hass,
                ir01_entity_id,
                climate_name,
                climate_id,
                status_quirks=status_quirks,
            )
        ]
    )


class ZBACClimateEntity(ClimateEntity, RestoreEntity):
    """Climate entity driven by ZB-IR01 IR command frames."""

    _enable_turn_on_off_backwards_compatibility = False

    def __init__(
        self,
        hass,
        ir01_entity_id,
        climate_name,
        climate_id,
        status_quirks: list[str] | None = None,
    ):
        self.hass = hass
        self._ir01_entity_id = ir01_entity_id
        self._name = climate_name
        self.entity_id = climate_id or None
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_min_temp = 16
        self._attr_max_temp = 32
        self._attr_target_temperature_step = 1.0

        self._hvac_mode: HVACMode | str = HVACMode.OFF
        self._target_temperature: float | None = 26
        self._fan_mode: str | None = FAN_AUTO
        self._swing_mode: str | None = SWING_OFF
        self._swing_horizontal_mode: str | None = SWING_HORIZONTAL_OFF
        self._preset_mode: str | None = PRESET_NONE
        self._last_command = ""
        self._last_received_command = ""

        quirks = status_quirks or []
        unknown = set(quirks) - KNOWN_STATUS_QUIRKS
        if unknown:
            _LOGGER.warning("Ignoring unknown status_quirks: %s", sorted(unknown))
        self._status_quirks = set(quirks) & KNOWN_STATUS_QUIRKS

        self._sensor_unsub = async_track_state_change_event(
            self.hass,
            "sensor." + self._ir01_entity_id + "_last_received_command",
            self.async_sensor_state_listener,
        )

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if not last_state:
            return
        self._hvac_mode = last_state.state
        if last_state.attributes.get("temperature") is not None:
            self._target_temperature = last_state.attributes.get("temperature")
        if last_state.attributes.get("fan_mode") is not None:
            self._fan_mode = last_state.attributes.get("fan_mode")
        if last_state.attributes.get("swing_mode") is not None:
            self._swing_mode = last_state.attributes.get("swing_mode")
        if last_state.attributes.get("swing_horizontal_mode") is not None:
            self._swing_horizontal_mode = last_state.attributes.get(
                "swing_horizontal_mode"
            )
        if last_state.attributes.get("preset_mode") is not None:
            self._preset_mode = last_state.attributes.get("preset_mode")

    async def async_sensor_state_listener(self, event):
        new_state = event.data["new_state"]
        if new_state is None:
            return
        self._last_received_command = new_state.state
        if self.parse_sensor_data(new_state.state):
            self.async_write_ha_state()

    @property
    def name(self):
        return self._name

    @property
    def hvac_mode(self):
        return self._hvac_mode

    @property
    def hvac_modes(self):
        return list(HVAC_MODE_CODES.keys())

    @property
    def target_temperature(self):
        return self._target_temperature

    @property
    def target_temperature_step(self):
        return 1.0

    @property
    def min_temp(self):
        return 16

    @property
    def max_temp(self):
        return 32

    @property
    def fan_mode(self):
        return self._fan_mode

    @property
    def fan_modes(self):
        return list(FAN_MODES_UI)

    @property
    def swing_mode(self):
        return self._swing_mode

    @property
    def swing_modes(self):
        return list(SWING_MODES_UI)

    @property
    def swing_horizontal_mode(self):
        return self._swing_horizontal_mode

    @property
    def swing_horizontal_modes(self):
        return list(SWING_HORIZONTAL_MODES_UI)

    @property
    def preset_mode(self):
        return self._preset_mode

    @property
    def preset_modes(self):
        return list(PRESET_MODES_UI)

    @property
    def supported_features(self):
        features = (
            ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.SWING_MODE
            | ClimateEntityFeature.PRESET_MODE
        )
        if _SWING_HORIZONTAL_FEATURE:
            features |= _SWING_HORIZONTAL_FEATURE
        return features

    def is_hex(self, val: str) -> bool:
        try:
            int(val, 16)
            return True
        except ValueError:
            return False

    def verify_checksum(self, data: str) -> bool:
        try:
            input_data = [int(data[i : i + 2], 16) for i in range(0, len(data) - 2, 2)]
            received_checksum = int(data[-2:], 16)
            calculated_checksum = 0
            for byte in input_data:
                calculated_checksum ^= byte
            return received_checksum == calculated_checksum
        except Exception:
            return False

    def _apply_status_quirks(self, power: str, mode: str, fan: str) -> tuple[str, str, str]:
        """Optional brand workarounds for non-standard 0x08 status frames.

        Disabled unless listed in discovery_info['status_quirks'].
        """
        # Toshiba-style (narrow): apply before the broader FF→ON remap so both can
        # coexist when enabled together without losing the fan_only rewrite.
        if STATUS_QUIRK_REMAP_FF_POWER_MODE in self._status_quirks:
            # Some remotes report power=0xff with mode=0x00 for fan-only-like state.
            if power == "ff" and mode == "00":
                power, mode = "00", "03"
        if STATUS_QUIRK_REMAP_FF_POWER_AS_ON in self._status_quirks:
            # Needed when power must be 00/01 only: remaps 0xFF→0x00 (ON) before the
            # strict check (e.g. Panasonic 08ff020800fd).
            if power == "ff":
                power = "00"
        if STATUS_QUIRK_CLAMP_FF_FAN_TO_LOW in self._status_quirks:
            # Some remotes report fan=0xff for the minimum fan step.
            if fan == "ff":
                fan = "01"
        return power, mode, fan

    def parse_sensor_data(self, data: str) -> bool:
        """Parse AC status report 0x08 (section 3.10).

        Layout: 08 <power> <mode> <temp> <fan> <xor>
          power: 0=ON, 1=OFF
          mode:  0=auto,1=cool,2=dry,3=fan,4=heat
          temp:  0=16°C … (protocol documents through 30°C; accept 0..16 for 16..32)
          fan:   0=auto,1=low,2=mid,3=high  (extended speeds are not in status feedback)

        Swing (keys 5–8), presets (boost/sleep/eco), and fan levels above high are
        never present in this report — local optimistic state is kept after set_* calls.
        """
        if not data or data[0:2] != "08":
            return False
        try:
            if not self.verify_checksum(data):
                raise ValueError("Invalid checksum.")
            power = data[2:4]
            mode = data[4:6]
            temp = data[6:8]
            fan = data[8:10]

            power, mode, fan = self._apply_status_quirks(power, mode, fan)

            if power not in ("00", "01"):
                raise ValueError(f"Invalid power value: {power}")
            if not self.is_hex(temp) or not 0 <= int(temp, 16) <= 16:
                raise ValueError(f"Invalid temperature value: {temp}")
            if not self.is_hex(mode) or not 0 <= int(mode, 16) <= 4:
                raise ValueError(f"Invalid hvac mode value: {mode}")
            if not self.is_hex(fan) or not 0 <= int(fan, 16) <= 6:
                raise ValueError(f"Invalid fan mode value: {fan}")

            self._target_temperature = int(temp, 16) + 16
            fan_idx = int(fan, 16)
            self._fan_mode = FAN_MODE_BY_STATUS_INDEX[fan_idx]

            if power == "01":
                self._hvac_mode = HVACMode.OFF
            else:
                self._hvac_mode = HVAC_MODE_BY_STATUS_INDEX[int(mode, 16)]
            return True
        except Exception as err:
            _LOGGER.warning("Error parsing sensor data '%s': %s", data, err)
            return False

    async def send_command(self, command: str) -> None:
        await self.hass.services.async_call(
            "text",
            "set_value",
            {
                "entity_id": "text." + self._ir01_entity_id + "_send_command",
                "value": '"' + command + '"',
            },
        )
        self._last_command = command
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        hvac_mode = kwargs.get(ATTR_HVAC_MODE)
        if temperature is not None:
            hex_code = TEMPERATURE_CODES.get(str(int(temperature)))
            if hex_code:
                self._target_temperature = temperature
                await self.send_command(hex_code)
            else:
                _LOGGER.warning("Error locating code with temperature '%s'.", temperature)
        if hvac_mode is not None:
            await self.async_set_hvac_mode(hvac_mode)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode | str) -> None:
        hex_code = HVAC_MODE_CODES.get(hvac_mode)
        if not hex_code:
            # Tolerate raw string vs enum
            hex_code = HVAC_MODE_CODES.get(str(hvac_mode))
        if not hex_code:
            _LOGGER.warning("Error locating code with hvac mode '%s'.", hvac_mode)
            return
        if self._hvac_mode == HVACMode.OFF and hvac_mode != HVACMode.OFF:
            await self.send_command(POWER_ON_CODE)
            await asyncio.sleep(1)
        self._hvac_mode = hvac_mode
        await self.send_command(hex_code)

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.AUTO)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        hex_code = FAN_MODE_CODES.get(fan_mode)
        if hex_code:
            self._fan_mode = fan_mode
            await self.send_command(hex_code)
        else:
            _LOGGER.warning("Error locating code with fan mode '%s'.", fan_mode)

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        hex_code = SWING_MODE_CODES.get(swing_mode)
        if hex_code:
            self._swing_mode = swing_mode
            await self.send_command(hex_code)
        else:
            _LOGGER.warning("Error locating code with swing mode '%s'.", swing_mode)

    async def async_set_swing_horizontal_mode(self, swing_horizontal_mode: str) -> None:
        hex_code = SWING_HORIZONTAL_MODE_CODES.get(swing_horizontal_mode)
        if hex_code:
            self._swing_horizontal_mode = swing_horizontal_mode
            await self.send_command(hex_code)
        else:
            _LOGGER.warning(
                "Error locating code with horizontal swing mode '%s'.",
                swing_horizontal_mode,
            )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Apply a protocol preset (sleep / eco / boost).

        Status report 0x08 never echoes preset state, so HA state is optimistic.
        Protocol toggles are independent on the wire; HA exposes a single preset_mode,
        so leaving a preset (or selecting none) sends that preset's off frame first.
        """
        if preset_mode not in PRESET_MODES_UI and preset_mode != PRESET_NONE:
            _LOGGER.warning("Unsupported preset mode '%s'.", preset_mode)
            return

        previous = self._preset_mode
        if previous and previous != PRESET_NONE and previous != preset_mode:
            off_code = PRESET_OFF_CODES.get(previous)
            if off_code:
                await self.send_command(off_code)
                await asyncio.sleep(0.3)

        if preset_mode == PRESET_NONE:
            # Previous preset's off frame (if any) was already sent above.
            self._preset_mode = PRESET_NONE
            self.async_write_ha_state()
            return

        hex_code = PRESET_MODE_CODES.get(preset_mode)
        if not hex_code:
            _LOGGER.warning("Error locating code with preset mode '%s'.", preset_mode)
            return
        self._preset_mode = preset_mode
        await self.send_command(hex_code)

    async def async_will_remove_from_hass(self) -> None:
        if self._sensor_unsub:
            self._sensor_unsub()
