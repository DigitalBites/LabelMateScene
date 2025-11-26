from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    CONF_GROUP_COLOR,
    CONF_GROUP_TYPE,
    CONF_LABEL_NAME,
    DEFAULT_COLOR_HEX,
    DOMAIN,
    GROUP_TYPE_LIGHT,
    GROUP_TYPE_SCENE,
    GROUP_TYPE_SWITCH,
)

_LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------
#                      CONFIG FLOW (initial setup)
# -------------------------------------------------------------


class LabelGroupConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup of a Label Group entry."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """First step: ask for label name and group type."""
        errors: dict[str, str] = {}

        if user_input is not None:
            label_name = user_input[CONF_LABEL_NAME].strip()

            if not label_name:
                errors["base"] = "label_required"
            else:
                # Create config entry with basic data + default options
                # Provide a hex color default for the new combined option
                hex_default = DEFAULT_COLOR_HEX

                return self.async_create_entry(
                    title=f"Label {label_name} Group",
                    data={
                        CONF_LABEL_NAME: label_name,
                    },
                    options={
                        CONF_GROUP_TYPE: user_input[CONF_GROUP_TYPE],
                        CONF_GROUP_COLOR: hex_default,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_LABEL_NAME): str,
                vol.Required(
                    CONF_GROUP_TYPE,
                    default=GROUP_TYPE_SWITCH,
                ): vol.In(
                    {
                        GROUP_TYPE_SWITCH: "Switch",
                        GROUP_TYPE_LIGHT: "Light",
                        GROUP_TYPE_SCENE: "Scene",
                    }
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    # ---------------------------------------------------------
    #        OPTIONS FLOW REGISTRATION (NEW-STYLE HOOK)
    # ---------------------------------------------------------

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow handler for this entry."""
        return LabelGroupOptionsFlow(config_entry)


# -------------------------------------------------------------
#                     OPTIONS FLOW (Configure)
# -------------------------------------------------------------


class LabelGroupOptionsFlow(config_entries.OptionsFlow):
    """Handle options for an existing Label Group entry."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        # Always fetch the latest config entry from registry to avoid stale options
        entry = self.hass.config_entries.async_get_entry(self._entry.entry_id)
        stored = {**entry.data, **entry.options}
        current_label = entry.data.get(CONF_LABEL_NAME, "")

        _LOGGER.debug(
            "Opening options flow for entry %s: entry=%s stored=%s",
            entry.entry_id,
            entry,
            stored,
        )

        # Start with stored options/data, then try to fall back to the running
        # integration state (coordinator) if options appear empty in memory.
        opts = entry.options or {}
        current_type = opts.get(CONF_GROUP_TYPE) or entry.data.get(CONF_GROUP_TYPE)

        if not current_type:
            # Try to read the live coordinator (created during setup) which may
            # have the resolved group type even if the in-memory entry.options
            # are not yet populated.
            live = (
                self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
                if hasattr(self.hass, "data")
                else None
            )
            coordinator = live.get("coordinator") if isinstance(live, dict) else None
            current_type = getattr(coordinator, "_group_type", None) if coordinator else None

        current_type = current_type or GROUP_TYPE_SWITCH

        _LOGGER.debug(
            "Opening options flow for entry %s: label=%s resolved_group_type=%s options=%s",
            entry.entry_id,
            current_label,
            current_type,
            opts,
        )

        if user_input is not None:
            new_label = user_input[CONF_LABEL_NAME].strip()

            if not new_label:
                errors["base"] = "label_required"
            else:
                new_data = dict(entry.data)
                new_data[CONF_LABEL_NAME] = new_label

                new_options = dict(entry.options)
                new_options[CONF_GROUP_TYPE] = user_input[CONF_GROUP_TYPE]

                # Normalize and persist combined hex color if provided
                hex_val = user_input.get(CONF_GROUP_COLOR)
                abort_save = False
                if hex_val:
                    # validate hex color server-side (allow optional leading '#')
                    m = re.fullmatch(r"#?[0-9A-Fa-f]{6}", str(hex_val).strip())
                    if not m:
                        errors["base"] = "invalid_color"
                        abort_save = True
                    else:
                        h = str(hex_val).lstrip("#").lower()
                        new_options[CONF_GROUP_COLOR] = f"#{h}"
                else:
                    # Always persist a valid hex color (default if missing)
                    new_options[CONF_GROUP_COLOR] = DEFAULT_COLOR_HEX

                if not errors and not abort_save:
                    # Persist changes
                    _LOGGER.debug(
                        "Persisting options for entry %s: data=%s options=%s new_entry=%s",
                        self._entry.entry_id,
                        new_data,
                        new_options,
                        entry.entry_id,
                    )
                    # Persist only the entry data programmatically. Return the
                    # `new_options` as the flow result so the frontend will
                    # store the options atomically. Doing both avoids races
                    # where the UI persists options separately from data.
                    self.hass.config_entries.async_update_entry(
                        entry,
                        data=new_data,
                    )
                    return self.async_create_entry(title="", data=new_options)

                # Persist changes (even if there were validation errors we saved normalized values)
                _LOGGER.debug(
                    "Updating entry %s (post-validate): data=%s options=%s new_entry=%s",
                    self._entry.entry_id,
                    new_data,
                    new_options,
                    entry.entry_id,
                )
                # Persist only the entry data; return options as the flow
                # payload so the frontend will persist them.
                self.hass.config_entries.async_update_entry(
                    entry,
                    data=new_data,
                )
                return self.async_create_entry(title="", data=new_options)

        # Compute a stable default hex for the color field. Prefer stored
        # options; if missing, try the running integration data (rgb tuple),
        # otherwise use the static default.
        ui_hex_default = None
        if opts.get(CONF_GROUP_COLOR):
            ui_hex_default = opts.get(CONF_GROUP_COLOR)
        else:
            live = (
                self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
                if hasattr(self.hass, "data")
                else None
            )
            rgb = None
            if isinstance(live, dict):
                rgb = live.get("group_color")

            if isinstance(rgb, (list, tuple)) and len(rgb) == 3:
                try:
                    ui_hex_default = "#{:02x}{:02x}{:02x}".format(*rgb)
                except Exception:
                    ui_hex_default = DEFAULT_COLOR_HEX
            else:
                ui_hex_default = DEFAULT_COLOR_HEX

        try:
            schema = vol.Schema(
                {
                    vol.Required(CONF_LABEL_NAME, default=current_label): str,
                    vol.Required(
                        CONF_GROUP_TYPE,
                        default=current_type,
                    ): vol.In(
                        {
                            GROUP_TYPE_SWITCH: "Switch",
                            GROUP_TYPE_LIGHT: "Light",
                            GROUP_TYPE_SCENE: "Scene",
                        }
                    ),
                    vol.Optional(CONF_GROUP_COLOR, default=ui_hex_default): vol.Any(None, str),
                }
            )

        except Exception as exc:  # pragma: no cover - should not normally happen
            _LOGGER.exception("Failed to build options schema: %s", exc)
            errors["base"] = "schema_error"

            # Fallback: show a minimal schema so the UI can still open
            return self.async_show_form(
                step_id="init",
                data_schema=vol.Schema({vol.Required(CONF_LABEL_NAME, default=current_label): str}),
                errors=errors,
            )

        try:
            return self.async_show_form(
                step_id="init",
                data_schema=schema,
                errors=errors,
            )
        except Exception as exc:  # pragma: no cover - catch UI rendering errors
            _LOGGER.exception("Error showing options form: %s", exc)
            errors["base"] = "show_form_error"
            return self.async_show_form(
                step_id="init",
                data_schema=vol.Schema({vol.Required(CONF_LABEL_NAME, default=current_label): str}),
                errors=errors,
            )
