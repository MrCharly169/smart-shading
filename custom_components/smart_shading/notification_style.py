"""Stable notification presentation for Smart Shading."""

from __future__ import annotations


def notification_title(title: str) -> str:
    """Return one category-specific Apple-visible title prefix."""
    value = str(title).strip()
    return value if value.startswith("🪟") else f"🪟 {value}"

