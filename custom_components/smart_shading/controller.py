from __future__ import annotations

from .engine import SmartShadingEngine as BaseSmartShadingEngine
from .manual_detection import ManualOverrideDetectionMixin


class SmartShadingEngine(ManualOverrideDetectionMixin, BaseSmartShadingEngine):
    """Runtime controller with confirmed manual-override detection."""
