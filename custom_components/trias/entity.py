"""The Trias base entity."""
from homeassistant.const import ATTR_ID
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity


class TriasCoordinatorEntity(CoordinatorEntity):
    """Trias base entity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, sensor: dict) -> None:
        """Initialize the Trias base entity."""
        super().__init__(coordinator)
        self._attr_name = sensor["name"]
        # self._attr_device_info = DeviceInfo(
        #    identifiers={(ATTR_ID, sensor["id"])},
        #    name=sensor["name"],
        #    entry_type=DeviceEntryType.SERVICE,
        # )
