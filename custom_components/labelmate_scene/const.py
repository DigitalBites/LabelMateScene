from __future__ import annotations

DOMAIN = "labelmate_scene"

# Config keys
CONF_LABEL_NAME = "label_name"
CONF_GROUP_TYPE = "group_type"

# New: combined hex color config key
CONF_GROUP_COLOR = "group_color"

# Group type values
GROUP_TYPE_SWITCH = "switch"
GROUP_TYPE_LIGHT = "light"
# Scene group type
GROUP_TYPE_SCENE = "scene"

# Domains the label group will control
ALLOWED_DOMAINS = ["light", "switch", "fan", "input_boolean"]

DEFAULT_COLOR_HEX = "#ffb478"  # warm white hex default
