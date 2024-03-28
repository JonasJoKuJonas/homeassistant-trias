"""The Trias base entity."""

from homeassistant.const import ATTR_ID
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import ATTR_ATTRIBUTION
from .const import ATTRIBUTION


class TriasCoordinatorEntity(CoordinatorEntity):
    """Trias base entity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, sensor: dict) -> None:
        """Initialize the Trias base entity."""
        super().__init__(coordinator)
        self._attr_name = sensor["name"]
        self._attr_extra_state_attributes = {ATTR_ATTRIBUTION: ATTRIBUTION}
        # self._attr_device_info = DeviceInfo(
        #    identifiers={(ATTR_ID, sensor["id"])},
        #    name=sensor["name"],
        #    entry_type=DeviceEntryType.SERVICE,
        # )
