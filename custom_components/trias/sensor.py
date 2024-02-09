"""Trias sensor integration."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import TriasCoordinatorEntity


from .const import (
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Trias sensors."""

    coordinator = hass.data[DOMAIN][entry.entry_id]

    stops = coordinator.stops
    trips = coordinator.trips

    entities = []
    for id, stop in stops.items():
        sensor = StopSensor(
            stop,
            coordinator,
        )
        entities.append(sensor)
        _LOGGER.debug("Added sensors '%s'", stop["name"])

    for id, trip in trips.items():
        sensor = TripSensor(
            trip,
            coordinator,
        )
        entities.append(sensor)
        _LOGGER.debug("Added sensors '%s'", trip["name"])

    async_add_entities(entities)


class StopSensor(TriasCoordinatorEntity, SensorEntity):
    """Contains the next departure time."""

    device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:bus-stop"

    def __init__(self, stop, coordinator):
        """Initialize the sensor."""
        super().__init__(coordinator, stop)
        self.coordinator = coordinator

        self._stop_id = stop["id"]
        self._attr_unique_id = stop["id"]

        self._name = stop["name"]

        self._attr_extra_state_attributes = stop["attrs"]

    @property
    def native_value(self):
        """Return the state of the device."""
        return self.coordinator.stops[self._stop_id]["data"].get("next_departure", None)


class TripSensor(TriasCoordinatorEntity, SensorEntity):
    """Contains the next trip time."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:bus-clock"

    def __init__(self, trip, coordinator):
        """Initialize the sensor."""
        super().__init__(coordinator, trip)
        self.coordinator = coordinator

        self._trip_id = trip["id"]
        self._attr_unique_id = trip["id"]

        self._name = trip["name"]

        self._attr_extra_state_attributes = trip["attrs"]

    @property
    def native_value(self):
        """Return the state of the device."""
        return self.coordinator.trips[self._trip_id]["data"].get("start", None)
