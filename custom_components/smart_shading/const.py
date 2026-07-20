from __future__ import annotations

import json
from pathlib import Path

DOMAIN = "smart_shading"
NAME = "Smart Shading"
VERSION = str(
    json.loads(
        (Path(__file__).with_name("manifest.json")).read_text(encoding="utf-8")
    )["version"]
)
STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.runtime"
CARD_RESOURCE = "/smart_shading/shading.js"

PLATFORMS = ["sensor", "binary_sensor", "switch", "select", "number", "button"]

CONF_HOUSE_NAME = "house_name"
CONF_SUN_ENTITY = "sun_entity"
CONF_EVALUATION_INTERVAL = "evaluation_interval"
CONF_TEST_MODE = "test_mode"  # legacy compatibility
CONF_DIAGNOSTIC_LEVEL = "diagnostic_level"
CONF_ADVANCED_MODE = "advanced_mode"
CONF_EXTERNAL_MOVEMENT_DETECTION = "external_movement_detection"
CONF_WEATHER_ENTITY = "weather_entity"
CONF_SUN_PRESENCE_ENTITY = "sun_presence_entity"
CONF_EASY_TEMPERATURE_GATE = "easy_temperature_gate"
CONF_ROOMS = "rooms"

DEFAULT_EVALUATION_INTERVAL = 1200
DEFAULT_POSITION_TOLERANCE = 2.0
DEFAULT_TILT_TOLERANCE = 3.0
DEFAULT_COMMAND_COOLDOWN = 90
DEFAULT_EXTERNAL_MOVEMENT_DETECTION = False
DEFAULT_EVENING_RELEASE_TIME = "18:00:00"
DEFAULT_SUNSET_OFFSET_MINUTES = -15

DIAGNOSTIC_OFF = "off"
DIAGNOSTIC_EVENTS = "events"
DIAGNOSTIC_FULL = "full"
DIAGNOSTIC_OPTIONS = [DIAGNOSTIC_OFF, DIAGNOSTIC_EVENTS, DIAGNOSTIC_FULL]

MODE_DISABLED = "disabled"
MODE_PAUSED = "paused"
MODE_SAFETY = "safety"
MODE_IDLE = "idle"
MODE_OPEN = "open"
MODE_COMFORT = "comfort"
MODE_SOLAR = "solar"
MODE_HEAT = "heat"
MODE_NIGHT = "night"
MODE_FINISHED = "finished"

PAUSE_AUTO = "auto"
PAUSE_NEXT_SUNRISE = "next_sunrise"
PAUSE_NEXT_SUNSET = "next_sunset"
PAUSE_NEXT_NIGHT_END = "next_night_end"
PAUSE_TIMED = "timed"
PAUSE_MANUAL = "manual"
PAUSE_OPTIONS = [
    PAUSE_AUTO,
    PAUSE_NEXT_SUNRISE,
    PAUSE_NEXT_SUNSET,
    PAUSE_NEXT_NIGHT_END,
    PAUSE_TIMED,
    PAUSE_MANUAL,
]


DIRECTION_NORTH = "north"
DIRECTION_NORTHEAST = "northeast"
DIRECTION_EAST = "east"
DIRECTION_SOUTHEAST = "southeast"
DIRECTION_SOUTH = "south"
DIRECTION_SOUTHWEST = "southwest"
DIRECTION_WEST = "west"
DIRECTION_NORTHWEST = "northwest"
DIRECTION_CUSTOM = "custom"
DIRECTION_OPTIONS = [
    DIRECTION_NORTH,
    DIRECTION_NORTHEAST,
    DIRECTION_EAST,
    DIRECTION_SOUTHEAST,
    DIRECTION_SOUTH,
    DIRECTION_SOUTHWEST,
    DIRECTION_WEST,
    DIRECTION_NORTHWEST,
    DIRECTION_CUSTOM,
]

# Broad facade sectors. Customers select a compass direction; experts may refine them.
DIRECTION_PRESETS = {
    DIRECTION_NORTH: {"azimuth_start": 300.0, "azimuth_end": 60.0, "elevation_min": 0.0},
    DIRECTION_NORTHEAST: {"azimuth_start": 330.0, "azimuth_end": 120.0, "elevation_min": 3.0},
    DIRECTION_EAST: {"azimuth_start": 30.0, "azimuth_end": 150.0, "elevation_min": 5.0},
    DIRECTION_SOUTHEAST: {"azimuth_start": 60.0, "azimuth_end": 210.0, "elevation_min": 8.0},
    DIRECTION_SOUTH: {"azimuth_start": 120.0, "azimuth_end": 240.0, "elevation_min": 10.0},
    DIRECTION_SOUTHWEST: {"azimuth_start": 150.0, "azimuth_end": 300.0, "elevation_min": 8.0},
    DIRECTION_WEST: {"azimuth_start": 210.0, "azimuth_end": 330.0, "elevation_min": 5.0},
    DIRECTION_NORTHWEST: {"azimuth_start": 240.0, "azimuth_end": 30.0, "elevation_min": 3.0},
    DIRECTION_CUSTOM: {"azimuth_start": 120.0, "azimuth_end": 240.0, "elevation_min": 10.0},
}

PRESET_LOW = "low"
PRESET_MEDIUM = "medium"
PRESET_HIGH = "high"
PRESET_CUSTOM = "custom"
SUN_PRESETS = {
    # Sensitive = lower thresholds (more likely to turn ON early).
    PRESET_LOW: {"sun_on_lux": 35000.0, "sun_off_lux": 18000.0, "sun_on_delay": 6.0, "sun_off_delay": 20.0},
    PRESET_MEDIUM: {"sun_on_lux": 18000.0, "sun_off_lux": 9000.0, "sun_on_delay": 3.0, "sun_off_delay": 12.0},
    PRESET_HIGH: {"sun_on_lux": 8000.0, "sun_off_lux": 4000.0, "sun_on_delay": 2.0, "sun_off_delay": 8.0},
}
SUN_PRESET_OPTIONS = [PRESET_LOW, PRESET_MEDIUM, PRESET_HIGH, PRESET_CUSTOM]

TILT_PRESET_GLARE = "glare"
TILT_PRESET_BALANCED = "balanced"
TILT_PRESET_DAYLIGHT = "daylight"
TILT_PRESET_CUSTOM = "custom"
TILT_PRESET_OPTIONS = [
    TILT_PRESET_GLARE,
    TILT_PRESET_BALANCED,
    TILT_PRESET_DAYLIGHT,
    TILT_PRESET_CUSTOM,
]
TILT_CURVE_PRESETS = {
    TILT_PRESET_GLARE: [
        {"elevation": 10.0, "tilt": 95.0},
        {"elevation": 20.0, "tilt": 80.0},
        {"elevation": 40.0, "tilt": 55.0},
        {"elevation": 60.0, "tilt": 35.0},
    ],
    TILT_PRESET_BALANCED: [
        {"elevation": 10.0, "tilt": 90.0},
        {"elevation": 20.0, "tilt": 65.0},
        {"elevation": 40.0, "tilt": 35.0},
        {"elevation": 60.0, "tilt": 15.0},
    ],
    TILT_PRESET_DAYLIGHT: [
        {"elevation": 10.0, "tilt": 80.0},
        {"elevation": 20.0, "tilt": 50.0},
        {"elevation": 40.0, "tilt": 20.0},
        {"elevation": 60.0, "tilt": 5.0},
    ],
}

DEVICE_VENETIAN = "venetian"
DEVICE_ROLLER = "roller_shutter"
DEVICE_SCREEN = "exterior_screen"
DEVICE_CURTAIN = "curtain"
DEVICE_VERTICAL = "vertical_blind"
DEVICE_AWNING = "awning"
DEVICE_BINARY = "binary_cover"
DEVICE_TYPES = [
    DEVICE_VENETIAN,
    DEVICE_ROLLER,
    DEVICE_SCREEN,
    DEVICE_CURTAIN,
    DEVICE_VERTICAL,
    DEVICE_AWNING,
    DEVICE_BINARY,
]

# Cover height keeps Home Assistant semantics: 0 = closed, 100 = open.
# Slat tilt uses the KNX convention confirmed by the pilot installation:
# 0 = fully open/light passes, 100 = fully closed/light blocked.
PROFILE_DEFAULTS = {
    DEVICE_VENETIAN: {
        "supports_position": True,
        "supports_tilt": True,
        "adaptive_tilt": True,
        "tilt_preset": TILT_PRESET_BALANCED,
        "open_position": 100.0,
        "open_tilt": 0.0,
        # Comfort and Solar intentionally use the same physical strategy:
        # blind fully down, slats guided by sun elevation.
        "comfort_position": 0.0,
        "comfort_tilt": 65.0,
        "solar_position": 0.0,
        "solar_tilt": 65.0,
        "heat_position": 0.0,
        "heat_tilt": 100.0,
        "night_position": 0.0,
        "night_tilt": 100.0,
        "safety_position": 100.0,
        "safety_tilt": 0.0,
        "tilt_curve": TILT_CURVE_PRESETS[TILT_PRESET_BALANCED],
    },
    DEVICE_ROLLER: {
        "supports_position": True,
        "supports_tilt": False,
        "adaptive_tilt": False,
        "open_position": 100.0,
        "comfort_position": 65.0,
        "solar_position": 25.0,
        "heat_position": 0.0,
        "night_position": 0.0,
        "safety_position": 100.0,
    },
    DEVICE_SCREEN: {
        "supports_position": True,
        "supports_tilt": False,
        "adaptive_tilt": False,
        "open_position": 100.0,
        "comfort_position": 60.0,
        "solar_position": 15.0,
        "heat_position": 0.0,
        "night_position": 0.0,
        "safety_position": 100.0,
    },
    DEVICE_CURTAIN: {
        "supports_position": True,
        "supports_tilt": False,
        "adaptive_tilt": False,
        "open_position": 100.0,
        "comfort_position": 60.0,
        "solar_position": 30.0,
        # Interior curtains default to the solar position in heat mode.
        # Full closure can be enabled in advanced settings.
        "heat_position": 30.0,
        "night_position": 0.0,
        "heat_close_enabled": False,
        "safety_position": 100.0,
    },
    DEVICE_VERTICAL: {
        "supports_position": True,
        "supports_tilt": True,
        "adaptive_tilt": True,
        "tilt_preset": TILT_PRESET_BALANCED,
        "open_position": 100.0,
        "open_tilt": 0.0,
        "comfort_position": 0.0,
        "comfort_tilt": 35.0,
        "solar_position": 0.0,
        "solar_tilt": 65.0,
        "heat_position": 0.0,
        "heat_tilt": 100.0,
        "night_position": 0.0,
        "night_tilt": 100.0,
        "safety_position": 100.0,
        "safety_tilt": 0.0,
        "tilt_curve": TILT_CURVE_PRESETS[TILT_PRESET_BALANCED],
    },
    DEVICE_AWNING: {
        "supports_position": True,
        "supports_tilt": False,
        "adaptive_tilt": False,
        # For an awning, closed/retracted is the neutral and safety position.
        "open_position": 0.0,
        "comfort_position": 60.0,
        "solar_position": 100.0,
        "heat_position": 100.0,
        "night_position": 0.0,
        "safety_position": 0.0,
    },
    DEVICE_BINARY: {
        "supports_position": False,
        "supports_tilt": False,
        "adaptive_tilt": False,
        "open_position": 100.0,
        "comfort_position": 0.0,
        "solar_position": 0.0,
        "heat_position": 0.0,
        "night_position": 0.0,
        "safety_position": 100.0,
    },
}

SCHEDULE_YEAR_ROUND = "year_round"
SCHEDULE_SUMMER = "summer"
SCHEDULE_CUSTOM = "custom"
SCHEDULE_OPTIONS = [SCHEDULE_YEAR_ROUND, SCHEDULE_SUMMER, SCHEDULE_CUSTOM]

DAY_WINDOW_SECTOR_SUN = "sector_sun"
DAY_WINDOW_FIXED = "fixed_time"
DAY_WINDOW_ALL_DAY = "all_day"
DAY_WINDOW_OPTIONS = [DAY_WINDOW_SECTOR_SUN, DAY_WINDOW_FIXED, DAY_WINDOW_ALL_DAY]

OUTSIDE_OPEN = "open"
OUTSIDE_HOLD = "hold"
OUTSIDE_OPTIONS = [OUTSIDE_OPEN, OUTSIDE_HOLD]

ROOM_DEFAULTS = {
    "enabled": True,
    "default_pause_mode": PAUSE_NEXT_SUNRISE,
    "pause_sun_offset_minutes": 0,
    "pause_duration_hours": 2.0,
    "heat_during_pause": False,
    "night_enabled": False,
    "night_source": "entity",
    "night_entity": "",
    "night_start_offset_minutes": 0,
    "night_end_offset_minutes": 0,
    "night_morning_transition_minutes": 0,
    "night_evening_transition_minutes": 0,
    "indoor_temperature_name": "",
    "display_name": "",
    "outdoor_temperature_name": "",
    "indoor_temperature": "",
    "outdoor_temperature": "",
    # Easy Mode remains fully functional without these optional refinements.
    # When enabled, the temperature gate first uses the configured outdoor
    # sensor and may fall back to the global weather entity temperature.
    CONF_EASY_TEMPERATURE_GATE: False,
    "irradiance_sensor": "",
    "cloud_cover_sensor": "",
    "weather_permission": "",
    "glare_sensor": "",
    "occupancy_sensor": "",
    "safety_blockers": [],
    "normal_shading_temperature": 23.5,
    "comfort_temperature": 23.5,
    "solar_temperature": 25.5,
    "heat_temperature": 27.0,
    "heat_release_temperature": 26.0,
    "reopen_temperature": 22.0,
    "outdoor_minimum": 18.0,
    "irradiance_minimum": 150.0,
    "cloud_cover_maximum": 85.0,
    "weather_logic": "all",
    "heat_ignores_weather": True,
    "heat_fail_safe": True,
    "heat_requires_sun": True,
    "comfort_requires_occupancy": False,
    "safety_behavior": "move_safe",
    "schedule_profile": SCHEDULE_YEAR_ROUND,
    "active_months": list(range(1, 13)),
    "active_weekdays": list(range(7)),
    "day_window": DAY_WINDOW_SECTOR_SUN,
    "start_time": "00:00:00",
    "end_time": "23:59:59",
    "outside_schedule_behavior": OUTSIDE_OPEN,
    "heat_outside_schedule": True,
    "sectors": [],
}

WINDOW_POLICY_BLOCK_ALL = "block_all"
WINDOW_POLICY_BLOCK_CLOSING = "block_closing"
WINDOW_POLICY_IGNORE = "ignore"
CONF_WINDOW_RETURNS_TO_AUTOMATION = "window_returns_to_automation"
DEFAULT_WINDOW_RETURNS_TO_AUTOMATION = True
WINDOW_POLICIES = [
    WINDOW_POLICY_BLOCK_ALL,
    WINDOW_POLICY_BLOCK_CLOSING,
    WINDOW_POLICY_IGNORE,
]
