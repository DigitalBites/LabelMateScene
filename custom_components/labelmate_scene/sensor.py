from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .entity_manager import LabelGroupCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: LabelGroupCoordinator = data["coordinator"]
    label_name: str = data["label_name"]

    async_add_entities(
        [
            LabelGroupActiveCountSensor(coordinator, entry.entry_id, label_name),
            LabelGroupTotalCountSensor(coordinator, entry.entry_id, label_name),
        ],
        True,
    )


class BaseLabelGroupSensor(CoordinatorEntity[LabelGroupCoordinator], SensorEntity):
    """Base class to attach common device info."""

    _attr_should_poll = False

    def __init__(self, coordinator, entry_id, label_name):
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._label_name = label_name

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": f"Label {self._label_name} Group",
            "manufacturer": "Custom",
            "model": "Label Group Switch",
        }


class LabelGroupActiveCountSensor(BaseLabelGroupSensor):
    """Sensor that reports number of ON entities."""

    def __init__(self, coordinator, entry_id, label_name):
        super().__init__(coordinator, entry_id, label_name)
        self._attr_unique_id = f"{entry_id}_sensor_active"
        self._attr_name = f"Label {label_name} Group Active Count"

    @property
    def state(self):
        d = self.coordinator.data or {}
        return d.get("on_count", 0)

    @property
    def extra_state_attributes(self):
        return self.coordinator.data or {}


class LabelGroupTotalCountSensor(BaseLabelGroupSensor):
    """Sensor that reports total number of monitored entities."""

    def __init__(self, coordinator, entry_id, label_name):
        super().__init__(coordinator, entry_id, label_name)
        self._attr_unique_id = f"{entry_id}_sensor_total"
        self._attr_name = f"Label {label_name} Group Total Count"

    @property
    def state(self):
        d = self.coordinator.data or {}
        return d.get("total", 0)

    @property
    def extra_state_attributes(self):
        return self.coordinator.data or {}
