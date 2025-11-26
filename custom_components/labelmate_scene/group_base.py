from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.components.scene import DOMAIN as SCENE_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from .const import (
    CONF_LABEL_NAME,
    DOMAIN,
)
from .helpers import slugify_label

_LOGGER = logging.getLogger(__name__)


class LabelGroupBase(Entity):
    """Base implementation for both switch and light label-groups."""

    def __init__(self, hass: HomeAssistant, coordinator, entry_id: str, entry_data: dict):
        self.hass = hass
        self.coordinator = coordinator
        self._entry_id = entry_id
        self._entry_data = entry_data  # REQUIRED for device_info
        self._label = entry_data.get(CONF_LABEL_NAME)

        # Attributes storing last-used scenes
        self._last_on_scene: str | None = None
        self._last_off_scene: str | None = None

        self._attr_should_poll = False
        self._attr_available = True

        #
        # Suppression + forced_state variables
        #
        self._suppress_updates_until: float = 0.0
        self._forced_state: bool | None = None

    # ---------------------------------------------------------------
    #                       ENTITY METADATA
    # ---------------------------------------------------------------

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def device_info(self):
        label = self._entry_data.get("label_name", "Label Group")

        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": f"Label Group: {label}",
            "manufacturer": "Label Group Integration",
            "model": "Label Group",
            "entry_type": "service",
        }

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return custom attributes including last-used scenes."""
        data = self.coordinator.data or {}

        return {
            "entity_id": data.get("targets", []),
            "last_on_scene": self._last_on_scene or "none",
            "last_off_scene": self._last_off_scene or "none",
        }

    async def async_added_to_hass(self) -> None:
        """Attach coordinator listener."""
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_coordinator_update))

    def _handle_coordinator_update(self) -> None:
        """Apply coordinator updates unless suppression is active."""

        now = time.time()

        # Suppression active - ignore coordinator events
        if now < self._suppress_updates_until:
            _LOGGER.debug(
                "[%s] Coordinator update suppressed (%.2f sec left)",
                self._entry_id,
                self._suppress_updates_until - now,
            )
            return

        # Suppression ended -> let real state take over
        if self._forced_state is not None:
            _LOGGER.debug(
                "[%s] Suppression ended; clearing forced state",
                self._entry_id,
            )
        self._forced_state = None

        # Update switch state from coordinator
        self._attr_is_on = self.is_on

        self.async_write_ha_state()

    # ---------------------------------------------------------------
    #                          TURN ON / OFF
    # ---------------------------------------------------------------

    @property
    def is_on(self) -> bool:
        """Return the on/off state with suppression applied."""
        now = time.time()

        # During transition: honor the forced state
        if now < self._suppress_updates_until and self._forced_state is not None:
            return self._forced_state

        # Normal operation: rely on coordinator data
        data = self.coordinator.data or {}
        total = data.get("total", 0)
        on_count = data.get("on_count", 0)

        return total > 0 and on_count > 0

    async def async_turn_on(self, **kwargs):
        """Scene-first turn_on logic."""
        if await self._maybe_activate_scene(turn_off=False):
            self.async_write_ha_state()
            return

        # No scene → normal fallback
        self._last_on_scene = None
        self.async_write_ha_state()

        data = self.coordinator.data or {}
        targets = data.get("targets") or []

        if not targets:
            _LOGGER.debug(
                "[%s] Turn ON: No targets for '%s'",
                self._entry_id,
                self._label_name,
            )
            return

        # Begin suppression window
        self._forced_state = True
        self._suppress_updates_until = time.time() + 1.0

        # Optimistic UI
        self._attr_is_on = True
        self.async_write_ha_state()

        _LOGGER.debug(
            "[%s] Turning ON (serial) %d entities: %s",
            self._entry_id,
            len(targets),
            targets,
        )

        await self.hass.services.async_call(
            "homeassistant",
            "turn_on",
            {"entity_id": targets},
            blocking=False,
        )

    async def async_turn_off(self, **kwargs):
        """Scene-first turn_off logic."""
        if await self._maybe_activate_scene(turn_off=True):
            self.async_write_ha_state()
            return

        # No scene → standard fallback
        self._last_off_scene = None
        self.async_write_ha_state()

        # await self.coordinator.async_turn_off_targets()

        data = self.coordinator.data or {}
        targets = data.get("targets") or []

        if not targets:
            _LOGGER.debug(
                "[%s] Turn OFF: No targets for '%s'",
                self._entry_id,
                self._label_name,
            )
            return

        # Begin suppression window
        self._forced_state = False
        self._suppress_updates_until = time.time() + 1.0

        # Optimistic UI
        self._attr_is_on = False
        self.async_write_ha_state()

        _LOGGER.debug(
            "[%s] Turning OFF (serial) %d entities: %s",
            self._entry_id,
            len(targets),
            targets,
        )

        await self.hass.services.async_call(
            "homeassistant",
            "turn_off",
            {"entity_id": targets},
            blocking=False,
        )

    # ---------------------------------------------------------------
    #                     SCENE MATCHING LOGIC
    # ---------------------------------------------------------------
    def _normalize_label(self, value: str) -> str:
        """Return a slugified version of the label for matching.

        Uses the centralized `slugify_label` helper to ensure consistent
        behavior across the integration.
        """
        return slugify_label(value)

    async def _get_scenes_with_label(self, hass, label: str):
        reg = async_get_entity_registry(hass)

        target = self._normalize_label(label)

        scenes: list[str] = []
        for entry in reg.entities.values():
            if not entry.entity_id.startswith("scene."):
                continue

            for lab in entry.labels or set():
                if self._normalize_label(lab) == target:
                    scenes.append(entry.entity_id)
                    break

        return scenes

    async def _maybe_activate_scene(self, turn_off: bool) -> bool:
        """
        Try to activate a matching scene for ON or OFF.

        Matching rules:
        - Scene must have the same label (via HA's label system)
        - ON → scene name must NOT contain "off"
        - OFF → scene name MUST contain "off"
        - If multiple matches → choose alphabetical first
        """
        candidates: list[str] = []

        # All scenes in HA
        for scene_entity_id in await self._get_scenes_with_label(self.hass, self._label):
            state = self.hass.states.get(scene_entity_id)
            name_lower = state.name.lower()

            _LOGGER.debug(f"Found scene {scene_entity_id} for {self._label} with name {state.name}")

            # ON: exclude scenes with “off”
            if not turn_off:
                if "off" in name_lower:
                    continue
                candidates.append(scene_entity_id)

            # OFF: include only scenes with "off"
            else:
                if "off" not in name_lower:
                    continue
                candidates.append(scene_entity_id)

            _LOGGER.debug(
                f"Added scene {scene_entity_id} for {self._label} with name {state.name} as candidate"
            )

        if not candidates:
            return False

        candidates.sort()
        chosen = candidates[0]

        _LOGGER.debug(
            "LabelGroup[%s] using scene %s for turn_%s",
            self._label,
            chosen,
            "off" if turn_off else "on",
        )

        # Update tracking attributes
        if turn_off:
            self._last_off_scene = chosen
            self._last_on_scene = None
        else:
            self._last_on_scene = chosen
            self._last_off_scene = None

        # Activate the chosen scene
        await self.hass.services.async_call(
            SCENE_DOMAIN,
            "turn_on",
            {"entity_id": chosen},
            blocking=False,
        )

        return True
