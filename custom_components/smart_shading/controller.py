from __future__ import annotations

from .engine import SmartShadingEngine as BaseSmartShadingEngine
from .ha_service_detection import HomeAssistantServiceDetectionMixin
from .manual_detection import ManualOverrideDetectionMixin


class SmartShadingEngine(
    HomeAssistantServiceDetectionMixin,
    ManualOverrideDetectionMixin,
    BaseSmartShadingEngine,
):
    """Runtime controller with reliable manual-override detection."""
