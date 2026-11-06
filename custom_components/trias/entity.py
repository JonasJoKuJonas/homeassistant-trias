"""The Trias base entity."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ATTRIBUTION
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN


class TriasCoordinatorEntity(CoordinatorEntity):
    """Trias base entity."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator, sensor: dict, config_entry: ConfigEntry
    ) -> None:
        """Initialize the Trias base entity."""
        super().__init__(coordinator)
        self._attr_name = sensor["name"]
        self._attr_extra_state_attributes = {ATTR_ATTRIBUTION: ATTRIBUTION}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=config_entry.title,
            entry_type=DeviceEntryType.SERVICE,
        )
