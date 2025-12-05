from __future__ import annotations

import asyncio
import logging
import time

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from .const import CONF_GROUP_TYPE, DOMAIN, GROUP_TYPE_SCENE, GROUP_TYPE_SWITCH
from .group_base import LabelGroupBase
from .helpers import slugify_label

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up LabelGroupSwitch for both standard and scene-based label groups."""
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

    # Create a single switch for all group types (switch, light, scene)
    # Scene groups now aggregate all entities from all scenes with the label
    async_add_entities([LabelGroupSwitch(hass, coordinator, entry)])
    return


class LabelGroupSwitch(LabelGroupBase, SwitchEntity):
    """Switch variant of a LabelGroup."""

    def __init__(self, hass: HomeAssistant, coordinator, entry):
        super().__init__(hass, coordinator, entry.entry_id, entry.data)

        self._attr_unique_id = f"{entry.entry_id}_switch"
        self._attr_name = f"Label {entry.data.get('label_name')} Group"
        # Keep a slugified label for consistent internal usage
        self._label_slug = slugify_label(entry.data.get("label_name"))
        # Store group type for scene-specific logic
        self._group_type = entry.options.get(CONF_GROUP_TYPE) or entry.data.get(CONF_GROUP_TYPE) or GROUP_TYPE_SWITCH

    async def async_turn_on(self, **kwargs):
        """Turn on logic: activate first scene alphabetically for scene groups."""
        # For scene groups, activate the first alphabetically sorted scene
        if self._group_type == GROUP_TYPE_SCENE:
            scenes = self.coordinator.data.get("scenes", [])
            if scenes:
                # Sort scenes alphabetically
                sorted_scenes = sorted(scenes)
                first_scene = sorted_scenes[0]
                
                _LOGGER.debug(
                    "[%s] Scene group activating first scene (alphabetically): %s",
                    self._entry_id,
                    first_scene,
                )
                
                # Begin suppression window
                self._forced_state = True
                self._suppress_updates_until = time.time() + 1.0
                
                # Optimistic UI
                self._attr_is_on = True
                self.async_write_ha_state()
                
                # Activate the scene
                await self.hass.services.async_call(
                    "scene",
                    "turn_on",
                    {"entity_id": first_scene},
                    blocking=True,
                )
                
                # Schedule a delayed refresh
                async def _delayed_refresh():
                    try:
                        await asyncio.sleep(0.5)
                        await self.coordinator.async_request_refresh()
                    except Exception:
                        pass
                
                self.hass.async_create_task(_delayed_refresh())
                return
        
        # For non-scene groups, use base class logic
        await super().async_turn_on(**kwargs)

    async def async_turn_off(self, **kwargs):
        """Turn off logic: turn off all entities from all scenes for scene groups."""
        # For scene groups, turn off all aggregated entities
        if self._group_type == GROUP_TYPE_SCENE:
            data = self.coordinator.data or {}
            targets = data.get("targets") or []
            
            if not targets:
                _LOGGER.debug(
                    "[%s] Scene group turn off: no aggregated entities found",
                    self._entry_id,
                )
                return
            
            _LOGGER.debug(
                "[%s] Scene group turning off %d aggregated entities",
                self._entry_id,
                len(targets),
            )
            
            # Begin suppression window
            self._forced_state = False
            self._suppress_updates_until = time.time() + 1.0
            
            # Optimistic UI
            self._attr_is_on = False
            self.async_write_ha_state()
            
            # Turn off all aggregated entities
            await self.hass.services.async_call(
                "homeassistant",
                "turn_off",
                {"entity_id": list(targets)},
                blocking=True,
            )
            
            # Immediately refresh coordinator
            try:
                await self.coordinator.async_request_refresh()
            except Exception:
                pass
            
            return
        
        # For non-scene groups, use base class logic
        await super().async_turn_off(**kwargs)
