from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory

from .entity import SmartShadingEntity, localized


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    engine = entry.runtime_data
    if not engine.advanced_mode:
        # Easy Mode intentionally exposes only the room Manual Override switch.
        # Evaluation remains automatic and is not a customer-facing control.
        async_add_entities([])
        return
    # Customer controls stay intentionally small.  Test and support controls
    # are opt-in per room; an Advanced installation is not consent to expose
    # a row of engineering buttons in every existing dashboard.
    entities = [EvaluateHouseButton(engine)] if any(
        engine.room_test_tools_enabled(room_id) for room_id in engine.rooms
    ) else []
    if entities:
        entities.append(ExportDiagnosticsButton(engine))
    for room_id in engine.rooms:
        entities.extend([PauseRoomButton(engine, room_id), ResumeRoomButton(engine, room_id)])
        if engine.room_test_tools_enabled(room_id):
            entities.extend(
                [
                    EvaluateRoomButton(engine, room_id),
                    SimulateRoomButton(engine, room_id),
                    PreviewRoomDayButton(engine, room_id),
                    ResetFinishedButton(engine, room_id),
                    ExportRoomDiagnosticsButton(engine, room_id),
                ]
            )
    for room in engine.config.get("rooms", []):
        if not engine.room_test_tools_enabled(room["id"]):
            continue
        for sector in room.get("sectors", []):
            if sector.get("lux_sensor"):
                entities.append(
                    ResetSunPresenceButton(
                        engine, room["id"], sector["id"]
                    )
                )
    async_add_entities(entities)


class EvaluateHouseButton(SmartShadingEntity, ButtonEntity):
    _attr_name = "Evaluate all rooms now"
    _attr_icon = "mdi:calculator-variant"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, engine) -> None:
        super().__init__(engine)
        self._attr_name = localized(engine, "Evaluate all rooms now", "Alle Räume jetzt auswerten")
        self._attr_unique_id = f"{self.entry.entry_id}_evaluate_all"

    async def async_press(self):
        await self.engine.async_evaluate_all("manual_house_evaluate")


class PauseRoomButton(SmartShadingEntity, ButtonEntity):
    _attr_name = "Pause automation"
    _attr_icon = "mdi:pause-circle"

    def __init__(self, engine, room_id: str) -> None:
        super().__init__(engine, room_id=room_id)
        self._attr_name = localized(engine, "Pause automation", "Automatik pausieren")
        self._attr_unique_id = f"{self.entry.entry_id}_{room_id}_pause_default"

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        attrs["smart_shading_control_key"] = "pause_default"
        return attrs

    async def async_press(self):
        await self.engine.async_pause_default(self.room_id)


class ResumeRoomButton(SmartShadingEntity, ButtonEntity):
    _attr_name = "Resume automation"
    _attr_icon = "mdi:play-circle"

    def __init__(self, engine, room_id: str) -> None:
        super().__init__(engine, room_id=room_id)
        self._attr_name = localized(engine, "Resume automation", "Automatik fortsetzen")
        self._attr_unique_id = f"{self.entry.entry_id}_{room_id}_resume"

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        attrs["smart_shading_control_key"] = "resume"
        return attrs

    async def async_press(self):
        await self.engine.async_resume_room(self.room_id)


class EvaluateRoomButton(SmartShadingEntity, ButtonEntity):
    _attr_name = "Evaluate now"
    _attr_icon = "mdi:calculator-variant"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, engine, room_id: str) -> None:
        super().__init__(engine, room_id=room_id)
        self._attr_name = localized(engine, "Evaluate now", "Jetzt auswerten")
        self._attr_unique_id = f"{self.entry.entry_id}_{room_id}_evaluate"

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        attrs["smart_shading_control_key"] = "evaluate"
        return attrs

    async def async_press(self):
        await self.engine.async_evaluate_all(f"manual_room:{self.room_id}")


class SimulateRoomButton(SmartShadingEntity, ButtonEntity):
    """Run the non-executing production decision simulation for one room."""

    _attr_name = "Run decision simulation"
    _attr_icon = "mdi:flask-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, engine, room_id: str) -> None:
        super().__init__(engine, room_id=room_id)
        self._attr_name = localized(
            engine,
            "Test evaluation (does not move covers)",
            "Testauswertung (bewegt keine Behänge)",
        )
        self._attr_unique_id = f"{self.entry.entry_id}_{room_id}_simulate"

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        attrs["smart_shading_control_key"] = "simulate"
        return attrs

    async def async_press(self):
        # Keep the button safe while a stored configuration is upgraded from a
        # pre-Issue-79 runtime: a missing simulation adapter must never fall
        # back to a live evaluation or cover service call.
        simulate = getattr(self.engine, "async_simulate_room", None)
        if not callable(simulate):
            raise HomeAssistantError("Smart Shading simulation is unavailable after this update")
        await simulate(self.room_id)


class PreviewRoomDayButton(SmartShadingEntity, ButtonEntity):
    """Calculate a non-executing day preview through the same pipeline."""

    _attr_name = "Preview today"
    _attr_icon = "mdi:calendar-search-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, engine, room_id: str) -> None:
        super().__init__(engine, room_id=room_id)
        self._attr_name = localized(
            engine,
            "Preview today (does not move covers)",
            "Tagvorschau (bewegt keine Behänge)",
        )
        self._attr_unique_id = f"{self.entry.entry_id}_{room_id}_preview_day"

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        attrs["smart_shading_control_key"] = "preview_day"
        return attrs

    async def async_press(self):
        # As with simulation, preserve the non-actuating contract if an older
        # runtime does not yet provide the preview adapter.
        preview = getattr(self.engine, "async_preview_room_day", None)
        if not callable(preview):
            raise HomeAssistantError("Smart Shading day preview is unavailable after this update")
        await preview(self.room_id)


class ResetFinishedButton(SmartShadingEntity, ButtonEntity):
    _attr_name = "Reset finished-today state"
    _attr_icon = "mdi:calendar-refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, engine, room_id: str) -> None:
        super().__init__(engine, room_id=room_id)
        self._attr_name = localized(engine, "Reset finished-today state", "Heute-abgeschlossen zurücksetzen")
        self._attr_unique_id = (
            f"{self.entry.entry_id}_{room_id}_reset_finished"
        )

    async def async_press(self):
        await self.engine.async_reset_finished(self.room_id)


class ResetSunPresenceButton(SmartShadingEntity, ButtonEntity):
    _attr_name = "Reset sun detection"
    _attr_icon = "mdi:weather-sunny-off"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, engine, room_id: str, sector_id: str) -> None:
        super().__init__(engine, room_id=room_id, sector_id=sector_id)
        sector = engine.sector_config(sector_id)
        self._attr_name = f"{sector['name']} · {localized(engine, 'Reset sun detection', 'Sonnenerkennung zurücksetzen')}"
        self._attr_unique_id = (
            f"{self.entry.entry_id}_{sector_id}_reset_sun_presence"
        )

    async def async_press(self):
        await self.engine.async_reset_sun_presence(self.sector_id)


class ExportDiagnosticsButton(SmartShadingEntity, ButtonEntity):
    _attr_name = "Export diagnostic log"
    _attr_icon = "mdi:file-download-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, engine) -> None:
        super().__init__(engine)
        self._attr_name = localized(engine, "Export diagnostic log", "Diagnoselog exportieren")
        self._attr_unique_id = f"{self.entry.entry_id}_export_diagnostics"

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        attrs["smart_shading_control_key"] = "export_diagnostics"
        return attrs

    async def async_press(self):
        url = await self.engine.async_export_diagnostics()
        await self.engine.hass.services.async_call("persistent_notification", "create", {
            "title": localized(self.engine, "Smart Shading log exported", "Smart Shading Log exportiert"),
            "message": f"[Diagnoselog herunterladen]({url})\n\n`{url}`",
            "notification_id": f"smart_shading_export_{self.entry.entry_id}",
        }, blocking=False)


class ExportRoomDiagnosticsButton(SmartShadingEntity, ButtonEntity):
    _attr_name = "Export room diagnostic log"
    _attr_icon = "mdi:file-download-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, engine, room_id: str) -> None:
        super().__init__(engine, room_id=room_id)
        self._attr_name = localized(engine, "Export room diagnostic log", "Raum-Diagnoselog exportieren")
        self._attr_unique_id = f"{self.entry.entry_id}_{room_id}_export_diagnostics"

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        attrs["smart_shading_control_key"] = "export_room_diagnostics"
        return attrs

    async def async_press(self):
        url = await self.engine.async_export_diagnostics(self.room_id)
        await self.engine.hass.services.async_call("persistent_notification", "create", {
            "title": localized(self.engine, "Smart Shading room log exported", "Smart Shading Raum-Log exportiert"),
            "message": f"[Raum-Diagnoselog herunterladen]({url})\n\n`{url}`",
            "notification_id": f"smart_shading_export_{self.entry.entry_id}_{self.room_id}",
        }, blocking=False)
