from __future__ import annotations

from typing import Any

from homeassistant.util import slugify as ha_slugify


def slugify_label(value: Any) -> str:
    """Return a Home Assistant-safe slug for a label.

    This centralizes label slugification so all modules use the same
    behaviour. Accepts any input and coerces to string.
    """
    if value is None:
        return ""
    return ha_slugify(str(value).strip())
