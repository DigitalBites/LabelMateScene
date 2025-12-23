from __future__ import annotations

import logging
from typing import Any

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import callback
from homeassistant.helpers.device_registry import (
    EVENT_DEVICE_REGISTRY_UPDATED,
)
from homeassistant.helpers.device_registry import (
    async_get as async_get_device_registry,
)
from homeassistant.helpers.entity_registry import (
    EVENT_ENTITY_REGISTRY_UPDATED,
)
from homeassistant.helpers.entity_registry import (
    async_get as async_get_entity_registry,
)
from homeassistant.helpers.label_registry import EVENT_LABEL_REGISTRY_UPDATED
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    ALLOWED_DOMAINS,
    CONF_GROUP_TYPE,
    CONF_LABEL_NAME,
    GROUP_TYPE_SCENE,
)
from .helpers import slugify_label

_LOGGER = logging.getLogger(__name__)


class LabelGroupCoordinator(DataUpdateCoordinator):
    """Tracks and manages all entities with a given label."""

    def __init__(self, hass, entry_id, entry):
        self.hass = hass
        self._entry_id = entry_id
        self._label_name = entry.data[CONF_LABEL_NAME]
        # Group type controls coordinator behavior (scene groups do not scan targets)
        # Prefer options (set by config flow), fall back to entry data, then default to switch
        from .const import GROUP_TYPE_SWITCH

        self._group_type = (
            entry.options.get(CONF_GROUP_TYPE) or entry.data.get(CONF_GROUP_TYPE) or GROUP_TYPE_SWITCH
        )
        self._targets: list[str] = []
        # Latest discovered scene -> [entities]
        self._scene_entities: dict[str, list[str]] = {}
        self._unsub: list = []

        # No template-based lookup: we'll compute membership directly from
        # the entity and device registries. This is more robust and testable.

        super().__init__(
            hass,
            _LOGGER,
            name=f"LabelGroup[{self._label_name}]",
            update_interval=None,
        )

    @property
    def targets(self) -> list[str]:
        """Current list of entities in this label group."""
        return self._targets

    async def async_setup_listeners(self):
        """Listen for registry + state updates to keep membership fresh."""

        async def reg(ev):
            _LOGGER.debug("[%s] Registry %s -> refresh", self._entry_id, ev.event_type)
            await self.async_request_refresh()

        async def reg_entity(ev):
            """Handle entity registry updates more selectively.

            Only refresh when a scene entity is affected to avoid unnecessary work,
            or when the entity's labels changed (event may not include labels, so
            fall back to a refresh if uncertain).
            """
            try:
                entity_id = ev.data.get("entity_id")
                action = ev.data.get("action")
            except Exception:
                entity_id = None
                action = None

            if entity_id and entity_id.startswith("scene."):
                _LOGGER.debug(
                    "[%s] Entity registry update for scene %s (action=%s) -> refresh",
                    self._entry_id,
                    entity_id,
                    action,
                )
                await self.async_request_refresh()
                return

            # If no specific entity_id supplied, fall back to a full refresh
            _LOGGER.debug(
                "[%s] Entity registry update (no scene-specific id) -> refresh",
                self._entry_id,
            )
            await self.async_request_refresh()

        async def st(ev):
            eid = ev.data.get("entity_id")
            # Refresh when a tracked target changes, or when any scene entity changes
            # so that scene edits (entities added/removed) are picked up.
            if not eid:
                return

            # If entity is a tracked target, refresh
            if eid in self._targets:
                _LOGGER.debug(
                    "[%s] state_changed tracked target %s -> refresh",
                    self._entry_id,
                    eid,
                )
                await self.async_request_refresh()
                return

            # If it's a scene entity, refresh
            if eid.startswith("scene."):
                _LOGGER.debug("[%s] state_changed scene %s -> refresh", self._entry_id, eid)
                await self.async_request_refresh()
                return

            # If the entity is part of any discovered scene, refresh
            for sents in self._scene_entities.values():
                if eid in sents:
                    _LOGGER.debug(
                        "[%s] state_changed scene member %s -> refresh",
                        self._entry_id,
                        eid,
                    )
                    await self.async_request_refresh()
                    return

        # Use a selective handler for entity registry updates (scene entities)
        self._unsub.append(self.hass.bus.async_listen(EVENT_ENTITY_REGISTRY_UPDATED, reg_entity))
        # Use generic handler for device and label registry updates
        self._unsub.append(self.hass.bus.async_listen(EVENT_DEVICE_REGISTRY_UPDATED, reg))
        self._unsub.append(self.hass.bus.async_listen(EVENT_LABEL_REGISTRY_UPDATED, reg))
        self._unsub.append(self.hass.bus.async_listen(EVENT_STATE_CHANGED, st))

    @callback
    def detach_listeners(self):
        for u in self._unsub:
            u()
        self._unsub.clear()

    async def async_config_entry_first_refresh(self):
        """Attach listeners, then run first refresh."""
        await self.async_setup_listeners()
        return await super().async_config_entry_first_refresh()

    async def _async_update_data(self) -> dict[str, Any]:
        """Render template, compute membership, and count 'on' entities."""
        label = self._label_name
        norm_label = slugify_label(label)

        _LOGGER.debug(
            "[%s] Coordinator refresh for label=%s (slug=%s) group_type=%s",
            self._entry_id,
            label,
            norm_label,
            self._group_type,
        )

        try:
            ent_reg = async_get_entity_registry(self.hass)
            dev_reg = async_get_device_registry(self.hass)
        except Exception as exc:  # pragma: no cover - defensive
            _LOGGER.exception("[%s] Failed to get registries: %s", self._entry_id, exc)
            return {"targets": [], "total": 0, "on_count": 0}

        targets: list[str] = []

        # If this entry is a scene group, we intentionally do NOT scan entities/devices
        # for membership. Scene-backed groups operate only on scene entities.
        if self._group_type == GROUP_TYPE_SCENE:
            _LOGGER.debug(
                "[%s] Group type is 'scene' — skipping entity/device membership scan",
                self._entry_id,
            )
        else:
            # Iterate all registered entities; include an entity if it or its
            # device has the requested label. Filter to allowed domains.
            for entry in ent_reg.entities.values():
                try:
                    # entry.labels is a set-like of labels attached to the entity
                    for lab in entry.labels or set():
                        if slugify_label(lab) == norm_label:
                            targets.append(entry.entity_id)
                            raise StopIteration

                    # If entity belongs to a device, check device labels
                    if entry.device_id:
                        dev = dev_reg.devices.get(entry.device_id)
                        if dev:
                            for lab in dev.labels or set():
                                if slugify_label(lab) == norm_label:
                                    targets.append(entry.entity_id)
                                    raise StopIteration
                except Exception:
                    # Skip entries we can't inspect
                    continue

        # Filter to allowed domains and ensure entity exists in state machine
        filtered: list[str] = []
        for e in targets:
            domain = e.split(".", 1)[0]
            st = self.hass.states.get(e)
            if st and domain in ALLOWED_DOMAINS:
                filtered.append(e)

        self._targets = list(dict.fromkeys(filtered))

        # Count on entities for non-scene groups
        on_count = 0
        if self._group_type != GROUP_TYPE_SCENE:
            for e in self._targets:
                s = self.hass.states.get(e)
                if s is not None and s.state == "on":
                    on_count += 1

        # Discover scenes that have the requested label via the entity registry
        scenes: list[str] = []
        scene_entities: dict[str, list[str]] = {}
        scene_names: dict[str, str] = {}

        try:
            # Use the entity registry to find scene entities that have labels
            for entry in ent_reg.entities.values():
                try:
                    if not entry.entity_id.startswith("scene."):
                        continue

                    for lab in entry.labels or set():
                        if slugify_label(lab) == norm_label:
                            scenes.append(entry.entity_id)
                            break
                except Exception:
                    continue

            # For each matching scene entity, collect its friendly name and referenced entities
            for scene_eid in scenes:
                st = self.hass.states.get(scene_eid)
                sname = st.name if st is not None else scene_eid
                scene_names[scene_eid] = sname

                ents: list[str] = []
                if st is not None:
                    # Some scene implementations use 'entities', others use 'entity_id'
                    ent_map = st.attributes.get("entities") or st.attributes.get("entity_id")

                    # Common case: dict mapping entity_id -> state
                    if isinstance(ent_map, dict):
                        for eid in ent_map.keys():
                            if self.hass.states.get(eid):
                                ents.append(eid)

                    # List/tuple/set of entity_ids
                    elif isinstance(ent_map, (list, tuple, set)):
                        for eid in ent_map:
                            if isinstance(eid, str) and self.hass.states.get(eid):
                                ents.append(eid)

                    # Single entity id string
                    elif isinstance(ent_map, str):
                        if self.hass.states.get(ent_map):
                            ents.append(ent_map)
                    
                    # Also check for device references in scene attributes
                    # When users add devices to scenes, they may be stored as device_id references
                    device_ids = st.attributes.get("device_ids", [])
                    if isinstance(device_ids, (list, tuple, set)):
                        for dev_id in device_ids:
                            if isinstance(dev_id, str):
                                # Get all entities for this device
                                dev = dev_reg.devices.get(dev_id)
                                if dev:
                                    for ent_entry in ent_reg.entities.values():
                                        if ent_entry.device_id == dev_id and ent_entry.entity_id not in ents:
                                            if self.hass.states.get(ent_entry.entity_id):
                                                ents.append(ent_entry.entity_id)

                scene_entities[scene_eid] = ents

            # Debug: log discovered scenes and their referenced entities
            # Persist discovered scene_entities for use by the state-change listener
            self._scene_entities = scene_entities

            if scenes:
                for sid in scenes:
                    sents = scene_entities.get(sid) or []
                    _LOGGER.debug(
                        "[%s] Discovered scene %s -> name=%s entities=%s",
                        self._entry_id,
                        sid,
                        scene_names.get(sid),
                        sents,
                    )
                    if not sents:
                        # Log attributes to help diagnose why no entities were found
                        st = self.hass.states.get(sid)
                        _LOGGER.debug(
                            "[%s] Scene %s attributes: %s",
                            self._entry_id,
                            sid,
                            st.attributes if st is not None else None,
                        )
            else:
                _LOGGER.debug("[%s] No scenes discovered for label %s", self._entry_id, label)

            # If group type is scene, aggregate all entities from all matching scenes
            if self._group_type == GROUP_TYPE_SCENE and scenes:
                aggregated_targets: set[str] = set()
                for scene_eid in scenes:
                    scene_ents = scene_entities.get(scene_eid, [])
                    aggregated_targets.update(scene_ents)
                
                self._targets = list(aggregated_targets)
                
                # Count on entities from aggregated list
                on_count = 0
                for e in self._targets:
                    s = self.hass.states.get(e)
                    if s is not None and s.state == "on":
                        on_count += 1
                
                _LOGGER.debug(
                    "[%s] Scene group aggregated %d unique entities from %d scenes",
                    self._entry_id,
                    len(self._targets),
                    len(scenes),
                )

        except Exception:
            # Defensive: if something goes wrong enumerating scenes, continue with empty lists
            scenes = []
            scene_entities = {}
            scene_names = {}

        _LOGGER.debug(
            "[%s] Coordinator result: targets=%d on_count=%d scenes=%d",
            self._entry_id,
            len(self._targets),
            on_count,
            len(scenes),
        )

        return {
            "targets": self._targets,
            "total": len(self._targets),
            "on_count": on_count,
            "scenes": scenes,
            "scene_entities": scene_entities,
            "scene_names": scene_names,
        }
