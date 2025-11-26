from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_GROUP_COLOR,
    CONF_LABEL_NAME,
    DEFAULT_COLOR_HEX,
    DOMAIN,
)
from .entity_manager import LabelGroupCoordinator

_LOGGER = logging.getLogger(f"custom_components.{DOMAIN}")

PLATFORMS = ["switch", "light", "sensor"]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up via YAML (not used; config entries only)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up a Label Group config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = LabelGroupCoordinator(hass, entry.entry_id, entry)
    await coordinator.async_config_entry_first_refresh()

    _LOGGER.debug(
        "Setting up Label Group entry %s: label=%s options=%s",
        entry.entry_id,
        entry.data.get(CONF_LABEL_NAME),
        entry.options,
    )

    # Resolve color from options; fallback to warm white if any component missing
    opts = entry.options or {}
    # Prefer the combined hex option if present.
    hex_color = opts.get(CONF_GROUP_COLOR) or DEFAULT_COLOR_HEX
    h = str(hex_color).lstrip("#")
    try:
        rgb = tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))
    except Exception:
        # Fallback to a safe literal if parsing fails
        rgb = (255, 180, 120)

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "label_name": entry.data[CONF_LABEL_NAME],
        "group_color": rgb,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Add listener so integration reloads when options change
    entry.async_on_unload(entry.add_update_listener(_update_listener))

    entry.async_on_unload(coordinator.detach_listeners)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a Label Group entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok and DOMAIN in hass.data:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Handle options updates (reload integration)."""
    _LOGGER.debug(
        "Config entry %s updated; reloading integration",
        entry.entry_id,
    )
    await hass.config_entries.async_reload(entry.entry_id)
