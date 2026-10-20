"""Constants for the Trias API integration."""

DOMAIN = "trias"

DEFAULT_SCAN_INTERVAL = 1  # Minutes

ATTRIBUTION = "Data provided by Trias API"

DEFAULT_DEPARTURE_LIMIT = 2


def get_trip_id(origin_id: str, destination_id: str) -> str:
    """Return a stable ID for an ordered pair of stops."""
    return f"{len(origin_id)}:{origin_id}{destination_id}"
