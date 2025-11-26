from __future__ import annotations

import logging

from homeassistant.components.light import (
    ColorMode,
    LightEntity,
)
from homeassistant.core import HomeAssistant

from .const import (
    CONF_GROUP_TYPE,
    CONF_LABEL_NAME,
    DEFAULT_COLOR_HEX,
    DOMAIN,
    GROUP_TYPE_LIGHT,
    GROUP_TYPE_SWITCH,
)
from .group_base import LabelGroupBase
from .helpers import slugify_label

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up LabelGroupLight from config entry."""

    # Prefer explicit options, fall back to stored data, then default to switch
    gtype = entry.options.get(CONF_GROUP_TYPE) or entry.data.get(CONF_GROUP_TYPE) or GROUP_TYPE_SWITCH
    _LOGGER.debug(
        "async_setup_entry for light platform: entry=%s group_type=%s options=%s",
        entry.entry_id,
        gtype,
        entry.options,
    )
    if gtype != GROUP_TYPE_LIGHT:
        return  # do not load light entity

    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]

    # Ensure color always exists; `hass.data` stores an RGB tuple. Accept
    # either an RGB tuple/list or a hex string (for compatibility).
    raw = data.get("group_color")
    group_color = None
    if isinstance(raw, (list, tuple)) and len(raw) == 3:
        try:
            group_color = (int(raw[0]), int(raw[1]), int(raw[2]))
        except Exception:
            group_color = None

    if group_color is None:
        # If raw was a hex string or missing, normalize and parse it
        hex_src = raw if raw else DEFAULT_COLOR_HEX
        h = str(hex_src).lstrip("#")
        try:
            group_color = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        except Exception:
            group_color = (255, 180, 120)

    async_add_entities([LabelGroupLight(hass, coordinator, entry, group_color)])


class LabelGroupLight(LabelGroupBase, LightEntity):
    """Light variant of a LabelGroup."""

    _attr_supported_color_modes = {ColorMode.RGB}

    def __init__(self, hass: HomeAssistant, coordinator, entry, group_color):
        super().__init__(hass, coordinator, entry.entry_id, entry.data)

        label = entry.data.get(CONF_LABEL_NAME)

        # Store a slugified version of the label for internal/ID purposes
        self._label_slug = slugify_label(label)

        self._attr_unique_id = f"{entry.entry_id}_light"
        self._attr_name = f"Label {label} Group"
        self._group_color = group_color

    # ------------------------------------------------------------------
    #                          STATE
    # ------------------------------------------------------------------

    @property
    def is_on(self):
        """Light is ON if any member device is ON."""
        # return self.coordinator.data["on_count"] > 0
        return super().is_on

    @property
    def brightness(self):
        """Brightness = percentage of devices ON mapped to 0–255."""
        total = self.coordinator.data["total"]
        on_count = self.coordinator.data["on_count"]

        if total <= 0:
            return 0

        pct = on_count / total
        return int(pct * 255)

    @property
    def rgb_color(self):
        """Return UI representation color."""
        return self._group_color

    @property
    def color_mode(self):
        """Required when using supported_color_modes."""
        return ColorMode.RGB

    # ------------------------------------------------------------------
    #                       TURN ON / OFF
    # ------------------------------------------------------------------

    async def async_turn_on(self, **kwargs):
        await super().async_turn_on(**kwargs)

    async def async_turn_off(self, **kwargs):
        await super().async_turn_off(**kwargs)

    # @property
    # def extra_state_attributes(self):
    #    """Expose group membership and scene info in a HA-friendly way."""
    #    # Start with base attributes (last_on_scene, last_off_scene)
    #    data = dict(super().extra_state_attributes or {})

    # Add member entities under the attribute name HA expects for groups
    #    coordinator_data = self.coordinator.data or {}
    #    data["entity_id"] = coordinator_data.get("targets", [])

    #    return data
