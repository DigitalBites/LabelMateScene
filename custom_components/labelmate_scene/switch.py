from __future__ import annotations

import asyncio
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from .const import CONF_GROUP_TYPE, DOMAIN, GROUP_TYPE_SCENE, GROUP_TYPE_SWITCH
from .group_base import LabelGroupBase
from .helpers import slugify_label

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up LabelGroupSwitch or scene-backed switches depending on type."""
    # Prefer explicit options, fall back to stored data, then default to switch
    gtype = entry.options.get(CONF_GROUP_TYPE) or entry.data.get(CONF_GROUP_TYPE) or GROUP_TYPE_SWITCH
    _LOGGER.debug(
        "async_setup_entry for switch platform: entry=%s group_type=%s options=%s",
        entry.entry_id,
        gtype,
        entry.options,
    )
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]

    if gtype == GROUP_TYPE_SWITCH:
        async_add_entities([LabelGroupSwitch(hass, coordinator, entry)])
        return

    # If this entry is configured as scene type, create one switch per matching scene
    if gtype == GROUP_TYPE_SCENE:
        scenes = coordinator.data.get("scenes", [])
        scene_names = coordinator.data.get("scene_names", {})
        entities: list[LabelGroupSwitch] = []
        for scene_eid in scenes:
            name = scene_names.get(scene_eid) or scene_eid
            entities.append(LabelSceneSwitch(hass, coordinator, entry, scene_eid, name))

        if entities:
            async_add_entities(entities)
        return


class LabelGroupSwitch(LabelGroupBase, SwitchEntity):
    """Switch variant of a LabelGroup."""

    def __init__(self, hass: HomeAssistant, coordinator, entry):
        super().__init__(hass, coordinator, entry.entry_id, entry.data)

        self._attr_unique_id = f"{entry.entry_id}_switch"
        self._attr_name = f"Label {entry.data.get('label_name')} Group"
        # Keep a slugified label for consistent internal usage
        self._label_slug = slugify_label(entry.data.get("label_name"))


class LabelSceneSwitch(LabelGroupBase, SwitchEntity):
    """Switch representing a scene that matched the configured label."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator,
        entry,
        scene_entity_id: str,
        scene_name: str,
    ):
        super().__init__(hass, coordinator, entry.entry_id, entry.data)

        self._scene_entity_id = scene_entity_id
        self._scene_name = scene_name
        # stable unique id derived from entry and scene id
        self._attr_unique_id = f"{entry.entry_id}:scene:{scene_entity_id}"
        label = entry.data.get("label_name")
        self._attr_name = f"{label} — {scene_name}"
        self._label_slug = slugify_label(label)

    async def async_added_to_hass(self) -> None:
        """When added, attach coordinator listener and schedule name-sync."""
        await super().async_added_to_hass()
        # Sync entity registry name to the auto-generated name if the user hasn't customized it.
        self.hass.async_create_task(self._sync_registry_name())

    async def _sync_registry_name(self) -> None:
        """Update the entity registry name to the auto-name unless user renamed it.

        Rule: if the registry name is empty/None or it follows the previous auto-name
        pattern ("{label} — ..."), update it to the current auto-name. If the user
        has already renamed the entity to something else, preserve their name.
        """
        try:
            reg = async_get_entity_registry(self.hass)
            entry = reg.entities.get(self.entity_id)
            if not entry:
                return

            current_name = entry.name
            desired = self._attr_name

            # If registry has no custom name or it looks like a prior auto-name, update it
            if current_name is None or (
                isinstance(current_name, str) and current_name.startswith(f"{self._label} ")
            ):
                # async_update_entity may be an awaitable
                try:
                    await reg.async_update_entity(self.entity_id, name=desired)
                    _LOGGER.debug(
                        "Synced entity registry name for %s -> %s",
                        self.entity_id,
                        desired,
                    )
                except Exception:
                    # Best-effort: don't fail setup if update isn't available
                    _LOGGER.debug("Entity registry update not supported for %s", self.entity_id)
        except Exception:
            _LOGGER.exception("Failed to sync registry name for %s", self.entity_id)

    @property
    def is_on(self):
        """LED: consider the scene ON if any of its referenced entities are ON."""
        scene_entities = self.coordinator.data.get("scene_entities", {}).get(self._scene_entity_id, [])
        for e in scene_entities:
            s = self.hass.states.get(e)
            if s is not None and s.state == "on":
                return True
        return False

    async def async_turn_on(self, **kwargs):
        """Activate the scene."""
        await self.hass.services.async_call(
            "scene",
            "turn_on",
            {"entity_id": self._scene_entity_id},
            blocking=True,
        )

        # Schedule a short delayed refresh of the coordinator to pick up
        # immediate state changes caused by the scene activation. This reduces
        # race windows where async_turn_off might run against stale data.
        async def _delayed_refresh():
            try:
                await asyncio.sleep(0.5)
                await self.coordinator.async_request_refresh()
                _LOGGER.debug(
                    "Requested delayed coordinator refresh after activating scene %s",
                    self._scene_entity_id,
                )
            except Exception:
                _LOGGER.exception("Failed delayed coordinator refresh for %s", self._scene_entity_id)

        # Fire-and-forget: we don't need to await this during the service call.
        self.hass.async_create_task(_delayed_refresh())

    async def async_turn_off(self, **kwargs):
        """Turn off entities referenced by the scene (best-effort)."""
        scene_entities = self.coordinator.data.get("scene_entities", {}).get(self._scene_entity_id, [])
        if not scene_entities:
            _LOGGER.warning(
                "%s: scene %s has no discovered entities to turn off",
                self.entity_id,
                self._scene_entity_id,
            )
            return

        _LOGGER.debug(
            "%s: turning off scene %s -> entities=%s",
            self.entity_id,
            self._scene_entity_id,
            scene_entities,
        )

        # Use the homeassistant.turn_off service to turn off all referenced entities
        await self.hass.services.async_call(
            "homeassistant",
            "turn_off",
            {"entity_id": list(scene_entities)},
            blocking=True,
        )

        # Immediately refresh coordinator to pick up the new states
        try:
            await self.coordinator.async_request_refresh()
            _LOGGER.debug(
                "Requested immediate coordinator refresh after turning off scene %s",
                self._scene_entity_id,
            )
        except Exception:
            _LOGGER.exception(
                "Failed to request coordinator refresh after turning off %s",
                self._scene_entity_id,
            )
