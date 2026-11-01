# The HA climate object created by easyiot ZB-IR01 with status feedback

This is a Home Assistant integration providing a sensor value to sync to a climate object.

### Installation

Copy this folder to `<config_dir>/custom_components/zb-ir01-to-climate/`.

The folder name must match the domain in `manifest.json` (`zb-ir01-to-climate`). Ensure `__init__.py`, `climate.py`, and `manifest.json` are present.

### Configuration

Add the following to your `configuration.yaml` file:

```yaml
# Example configuration.yaml entry
zb-ir01-to-climate:
  - ir01_entity_id: "0xf4b3b1fffe132df2"
    climate_id: "climate.my_ac"
    climate_name: "My AC"
    # Optional — brand-specific status-report quirks (off by default)
    # status_quirks:
    #   - remap_ff_power_as_on   # Panasonic: power=0xFF → ON (required; default only accepts 00/01)
    #   - remap_ff_power_mode    # Toshiba-style: power=ff,mode=00 → on + fan_only
    #   - clamp_ff_fan_to_low    # MHI-style: fan=ff → low
    #
    # Optional — vertical swing_mode list (ClimateEntityFeature.SWING_MODE)
    # Omitted → full protocol default (on/off, directions, auto_sweep, manual, …).
    # Exactly [on, off] → those labels send auto-sweep key 0x05 (simple remotes).
    # Empty list [] → disable SWING_MODE entirely.
    # swing_modes:
    #   - on
    #   - off
    #
    # Optional — independent horizontal swing (HA Core 2024.12+)
    # Omitted or [] → no SWING_HORIZONTAL_MODE feature.
    # Non-empty → enable only the listed modes (e.g. on/off/auto/left/right/…).
    # swing_horizontal_modes: []
```

Simple auto-sweep only (maps `on`/`off` to protocol key `0x05`), no horizontal swing:

```yaml
zb-ir01-to-climate:
  - ir01_entity_id: "0xf4b3b1fffe132df2"
    climate_name: "Living Room AC"
    swing_modes:
      - on
      - off
    swing_horizontal_modes: []
```

Directional vertical vanes plus horizontal on/off:

```yaml
zb-ir01-to-climate:
  - ir01_entity_id: "0xf4b3b1fffe132df2"
    climate_name: "Bedroom AC"
    swing_modes:
      - off
      - on
      - auto
      - up
      - middle
      - down
    swing_horizontal_modes:
      - off
      - on
```

Required fields per device: `ir01_entity_id`, `climate_name`. Optional: `climate_id`, `status_quirks` (list of strings), `swing_modes`, `swing_horizontal_modes`.

Fan UI modes are always `auto` and numbered `1`…`5` (protocol strong/hurricane/super collapse into `4`/`5`). Legacy aliases such as `low`/`medium`/`high` still work when calling `set_fan_mode`.

After editing YAML, restart Home Assistant (or reload custom integrations if your version supports it).

### Invalid config troubleshooting

- **Missing `__init__.py`**: HA cannot load / validate the integration → "Setup failed … Invalid config".
- **Unknown YAML keys**: `DEVICE_SCHEMA` only allows the fields above; typos or extra keys fail validation. `status_quirks`, `swing_modes`, and `swing_horizontal_modes` must be listed in the schema (this package includes them).
- **Domain / folder mismatch**: domain in `manifest.json`, folder name under `custom_components/`, and the YAML top-level key must all be `zb-ir01-to-climate`. Hyphens are historically fine for custom components when they match.
