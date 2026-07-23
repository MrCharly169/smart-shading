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
CONF_ADVANCED_FEATURES = "advanced_features"

# Advanced must describe customer-selected capabilities, not expose every
# engineering surface merely because an entry uses the Advanced setup route.
# The base solar automation is always present; these flags only add optional
# configuration, controls and explanatory UI for one room.
FEATURE_SCHEDULE = "schedule"
FEATURE_TEMPERATURE = "temperature"
FEATURE_NIGHT = "night"
FEATURE_SAFETY = "safety"
FEATURE_CONDITIONS = "conditions"
FEATURE_GLARE_PROTECTION = "glare_protection"
FEATURE_TEST_TOOLS = "test_tools"
FEATURE_EXPERT_EXECUTION = "expert_execution"
ADVANCED_FEATURES = (
    FEATURE_SCHEDULE,
    FEATURE_TEMPERATURE,
    FEATURE_NIGHT,
    FEATURE_SAFETY,
    FEATURE_CONDITIONS,
    FEATURE_GLARE_PROTECTION,
    FEATURE_TEST_TOOLS,
    FEATURE_EXPERT_EXECUTION,
)
CONF_EVALUATION_INTERVAL = "evaluation_interval"
CONF_TEST_MODE = "test_mode"  # legacy compatibility
CONF_DIAGNOSTIC_LEVEL = "diagnostic_level"
CONF_ADVANCED_MODE = "advanced_mode"
CONF_EXTERNAL_MOVEMENT_DETECTION = "external_movement_detection"
CONF_WEATHER_ENTITY = "weather_entity"
CONF_SUN_PRESENCE_ENTITY = "sun_presence_entity"
CONF_ROOMS = "rooms"

DEFAULT_EVALUATION_INTERVAL = 1200
# The interval above deliberately remains a slow recovery watchdog.  Normal
# decisions are triggered from entity events and coalesced by this short delay.
DEFAULT_EVALUATION_DEBOUNCE_SECONDS = 0.35
DEFAULT_POSITION_TOLERANCE = 5.0
DEFAULT_TILT_TOLERANCE = 5.0
DEFAULT_COMMAND_COOLDOWN = 90
DEFAULT_MOVEMENT_SECONDS = 45.0
DEFAULT_SETTLING_SECONDS = 5.0
DEFAULT_VERIFICATION_RETRIES = 1
DEFAULT_STAGGER_SECONDS = 0.0
# Normal cover commands are isolated per room unless an Advanced customer
# deliberately chooses a house-wide queue.  Safety remains independently
# configurable because an emergency movement can reasonably need to bypass a
# normal-command queue.
STAGGER_SCOPE_ROOM = "room"
STAGGER_SCOPE_HOUSE = "house"
STAGGER_SCOPE_OPTIONS = [STAGGER_SCOPE_ROOM, STAGGER_SCOPE_HOUSE]
DEFAULT_STAGGER_SCOPE = STAGGER_SCOPE_ROOM
DEFAULT_SAFETY_BYPASSES_STAGGER = True
# Once Home Assistant has confirmed an external/manual movement, retaining the
# person's chosen position is the safe default.  A customer can explicitly
# opt back into normal automation reclaiming the cover in Advanced Mode.
DEFAULT_ALLOW_AUTOMATIC_REVERSE = False
# Slatted covers normally move their height before opening the slats.  The
# alternate order remains an opt-in for a physical installation that requires
# it and is deliberately not exposed for Easy or non-slat profiles.
OPENING_ORDER_HEIGHT_THEN_TILT = "height_then_tilt"
OPENING_ORDER_TILT_THEN_HEIGHT = "tilt_then_height"
OPENING_ORDER_OPTIONS = [
    OPENING_ORDER_HEIGHT_THEN_TILT,
    OPENING_ORDER_TILT_THEN_HEIGHT,
]
DEFAULT_OPENING_ORDER = OPENING_ORDER_HEIGHT_THEN_TILT
# Freshness expiry is opt-in.  Stable Home Assistant states such as a closed
# window contact can legitimately remain unchanged for days, so treating the
# timestamp itself as a failed source must never be the default.
DEFAULT_SOURCE_STALE_SECONDS = 0.0
DEFAULT_EXTERNAL_MOVEMENT_DETECTION = False
DEFAULT_EVENING_RELEASE_TIME = "18:00:00"
DEFAULT_SUNSET_OFFSET_MINUTES = -15
PAUSE_DURATION_MIN_HOURS = 0.5
PAUSE_DURATION_MAX_HOURS = 72.0
PAUSE_DURATION_STEP_HOURS = 0.5
OUTDOOR_MINIMUM_MIN_C = -20.0
OUTDOOR_MINIMUM_MAX_C = 40.0
OUTDOOR_MINIMUM_STEP_C = 0.5
IRRADIANCE_MINIMUM_MIN = 0.0
IRRADIANCE_MINIMUM_MAX = 2000.0
IRRADIANCE_MINIMUM_STEP = 10.0

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
    # Facade-related outdoor Lux presets. Lower thresholds react earlier.
    PRESET_LOW: {"sun_on_lux": 50000.0, "sun_off_lux": 35000.0, "sun_on_delay": 10.0, "sun_off_delay": 30.0},
    PRESET_MEDIUM: {"sun_on_lux": 35000.0, "sun_off_lux": 30000.0, "sun_on_delay": 10.0, "sun_off_delay": 30.0},
    PRESET_HIGH: {"sun_on_lux": 25000.0, "sun_off_lux": 18000.0, "sun_on_delay": 5.0, "sun_off_delay": 15.0},
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
        "position_tolerance": DEFAULT_POSITION_TOLERANCE,
        "tilt_tolerance": DEFAULT_TILT_TOLERANCE,
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
        "position_tolerance": DEFAULT_POSITION_TOLERANCE,
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
        "position_tolerance": DEFAULT_POSITION_TOLERANCE,
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
        "position_tolerance": DEFAULT_POSITION_TOLERANCE,
        "open_position": 100.0,
        "comfort_position": 60.0,
        "solar_position": 30.0,
        # Interior curtains default to the solar position in heat mode. A
        # customer may choose a separate heat position directly.
        "heat_position": 30.0,
        "night_position": 0.0,
        "safety_position": 100.0,
    },
    DEVICE_VERTICAL: {
        "supports_position": True,
        "supports_tilt": True,
        "adaptive_tilt": True,
        "position_tolerance": DEFAULT_POSITION_TOLERANCE,
        "tilt_tolerance": DEFAULT_TILT_TOLERANCE,
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
        "position_tolerance": DEFAULT_POSITION_TOLERANCE,
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

# One physical profile owns every capability exposed by the setup wizard,
# runtime, entities and dashboard card.  Keep the editable target lists here
# instead of duplicating type checks across those surfaces.
TILT_PROFILES = frozenset({DEVICE_VENETIAN, DEVICE_VERTICAL})
POSITION_PROFILES = frozenset(set(DEVICE_TYPES) - {DEVICE_BINARY})
EXTERIOR_SAFETY_PROFILES = frozenset(
    {DEVICE_VENETIAN, DEVICE_ROLLER, DEVICE_SCREEN, DEVICE_AWNING}
)
PROFILE_TARGET_KEYS = {
    DEVICE_VENETIAN: (
        "open_position",
        "open_tilt",
        "heat_tilt",
        "night_position",
        "night_tilt",
        "safety_position",
        "safety_tilt",
    ),
    DEVICE_VERTICAL: (
        "open_position",
        "open_tilt",
        "comfort_tilt",
        "heat_tilt",
        "night_position",
        "night_tilt",
    ),
    DEVICE_ROLLER: (
        "open_position",
        "comfort_position",
        "solar_position",
        "heat_position",
        "night_position",
        "safety_position",
    ),
    DEVICE_SCREEN: (
        "open_position",
        "comfort_position",
        "solar_position",
        "heat_position",
        "night_position",
        "safety_position",
    ),
    DEVICE_CURTAIN: (
        "open_position",
        "comfort_position",
        "solar_position",
        "heat_position",
        "night_position",
    ),
    DEVICE_AWNING: (
        "open_position",
        "comfort_position",
        "solar_position",
        "heat_position",
        "night_position",
        "safety_position",
    ),
    DEVICE_BINARY: (),
}


def profile_supports_tilt(profile: str) -> bool:
    """Return whether this physical cover type accepts slat commands."""
    return profile in TILT_PROFILES


def profile_supports_position(profile: str) -> bool:
    """Return whether this physical cover type accepts numeric positions."""
    return profile in POSITION_PROFILES


def profile_uses_exterior_safety(profile: str) -> bool:
    """Return whether wind/frost protection is meaningful for this type."""
    return profile in EXTERIOR_SAFETY_PROFILES


def profile_target_keys(
    profile: str,
    *,
    indoor_temperature: bool = True,
    night: bool = True,
    safety: bool = True,
) -> tuple[str, ...]:
    """Return only target settings that can be reached in this room."""
    keys = PROFILE_TARGET_KEYS.get(profile, PROFILE_TARGET_KEYS[DEVICE_VENETIAN])
    return tuple(
        key
        for key in keys
        if (indoor_temperature or not key.startswith("heat_"))
        and (night or not key.startswith("night_"))
        and (safety or not key.startswith("safety_"))
    )

SCHEDULE_YEAR_ROUND = "year_round"
SCHEDULE_SUMMER = "summer"
SCHEDULE_CUSTOM = "custom"
SCHEDULE_OPTIONS = [SCHEDULE_YEAR_ROUND, SCHEDULE_SUMMER, SCHEDULE_CUSTOM]

DAY_WINDOW_FIXED = "fixed_time"
DAY_WINDOW_ALL_DAY = "all_day"
DAY_WINDOW_OPTIONS = [DAY_WINDOW_ALL_DAY, DAY_WINDOW_FIXED]

OUTSIDE_OPEN = "open"
OUTSIDE_HOLD = "hold"
OUTSIDE_OPTIONS = [OUTSIDE_OPEN, OUTSIDE_HOLD]

ADVANCED_EXECUTION_ROOM_DEFAULTS = {
    # These controls intentionally belong only to Advanced Mode.  Keeping
    # them outside ``ROOM_DEFAULTS`` prevents new Easy entries from carrying
    # hidden Advanced execution state in their persisted configuration.
    "command_stagger_seconds": DEFAULT_STAGGER_SECONDS,
    "stagger_scope": DEFAULT_STAGGER_SCOPE,
    "safety_bypasses_stagger": DEFAULT_SAFETY_BYPASSES_STAGGER,
    "target_verification_enabled": False,
    "verification_retries": DEFAULT_VERIFICATION_RETRIES,
    "movement_seconds": DEFAULT_MOVEMENT_SECONDS,
    "settling_seconds": DEFAULT_SETTLING_SECONDS,
    "source_stale_seconds": DEFAULT_SOURCE_STALE_SECONDS,
}


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
    "indoor_temperature": "",
    "outdoor_temperature": "",
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
    "reopen_temperature": 22.0,
    "outdoor_minimum": 18.0,
    "irradiance_minimum": 150.0,
    "cloud_cover_maximum": 85.0,
    "weather_logic": "all",
    "heat_ignores_weather": True,
    "heat_requires_sun": True,
    "evening_release_time": DEFAULT_EVENING_RELEASE_TIME,
    "sunset_offset_minutes": DEFAULT_SUNSET_OFFSET_MINUTES,
    "comfort_requires_occupancy": False,
    "safety_behavior": "move_safe",
    "schedule_enabled": False,
    "schedule_profile": SCHEDULE_YEAR_ROUND,
    "active_months": list(range(1, 13)),
    "active_weekdays": list(range(7)),
    "day_window": DAY_WINDOW_ALL_DAY,
    "start_time": "00:00:00",
    "end_time": "23:59:59",
    "outside_schedule_behavior": OUTSIDE_OPEN,
    "heat_outside_schedule": True,
    "sectors": [],
}

FEEDBACK_TRUSTED = "trusted"
FEEDBACK_INTERMEDIATE = "intermediate"
FEEDBACK_END_POSITIONS = "end_positions"
FEEDBACK_NONE = "none"
FEEDBACK_QUALITY_OPTIONS = [
    FEEDBACK_TRUSTED,
    FEEDBACK_INTERMEDIATE,
    FEEDBACK_END_POSITIONS,
    FEEDBACK_NONE,
]

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
