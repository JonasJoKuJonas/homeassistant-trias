"""Constants for the Trias API integration."""

DOMAIN = "trias"

DEFAULT_SCAN_INTERVAL = 1  # Minutes

ATTRIBUTION = "Data provided by Trias API"

DEFAULT_DEPARTURE_LIMIT = 2


def get_trip_id(origin_id: str, destination_id: str) -> str:
    """Return a stable ID for an ordered pair of stops."""
    return f"{len(origin_id)}:{origin_id}{destination_id}"


def get_entity_unique_id(config_entry_id: str, sensor_id: str) -> str:
    """Return a unique entity ID scoped to a Trias config entry."""
    return f"{config_entry_id}_{sensor_id}"
