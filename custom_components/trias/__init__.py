"""The Trias API integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, get_trip_id
from .coordinator import TriasDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]


def _migrate_entity_registry_entry(
    entity_registry: er.EntityRegistry,
    entry: ConfigEntry,
    unique_id: str,
    name: str | None,
    legacy_unique_ids: tuple[str, ...] = (),
) -> str | None:
    """Migrate an entity's registry identity and initialize its display name."""
    registry_entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, unique_id
    )
    registry_entry = (
        entity_registry.async_get(registry_entity_id)
        if registry_entity_id is not None
        else None
    )

    if registry_entry is None:
        for legacy_unique_id in legacy_unique_ids:
            legacy_entity_id = entity_registry.async_get_entity_id(
                "sensor", DOMAIN, legacy_unique_id
            )
            if legacy_entity_id is None:
                continue
            registry_entry = entity_registry.async_get(legacy_entity_id)
            if registry_entry is not None:
                break

    if registry_entry is not None and name is None:
        name = registry_entry.original_name

    if registry_entry is None and name:
        registry_entry = entity_registry.async_get_or_create(
            "sensor",
            DOMAIN,
            unique_id,
            config_entry=entry,
            has_entity_name=True,
            original_name=name,
            suggested_object_id=slugify(name),
        )
    elif registry_entry is not None:
        update: dict[str, str | bool] = {"has_entity_name": True}
        if registry_entry.unique_id != unique_id:
            update["new_unique_id"] = unique_id
        if name:
            update["original_name"] = name

        expected_old_entity_id = f"sensor.{slugify(registry_entry.unique_id)}"
        if name and registry_entry.entity_id == expected_old_entity_id:
            new_entity_id = f"sensor.{slugify(name)}"
            suffix = 2
            while (
                existing_entry := entity_registry.async_get(new_entity_id)
            ) is not None and existing_entry.entity_id != registry_entry.entity_id:
                new_entity_id = f"sensor.{slugify(name)}_{suffix}"
                suffix += 1
            if new_entity_id != registry_entry.entity_id:
                update["new_entity_id"] = new_entity_id

        entity_registry.async_update_entity(registry_entry.entity_id, **update)

    return name


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate stored options and entity registry entries."""
    if entry.version == 2:
        return True
    if entry.version != 1:
        _LOGGER.error("Cannot migrate config entry from version %s", entry.version)
        return False

    options = dict(entry.options)
    entity_registry = er.async_get(hass)

    def cached_trip_station_names(
        trip_id: str, legacy_unique_ids: tuple[str, ...] = ()
    ) -> tuple[str | None, str | None]:
        for unique_id in (trip_id, *legacy_unique_ids):
            entity_id = entity_registry.async_get_entity_id(
                "sensor", DOMAIN, unique_id
            )
            if entity_id is None:
                continue
            state = hass.states.get(entity_id)
            if state is None:
                continue
            origin_name = state.attributes.get("from")
            destination_name = state.attributes.get("to")
            return (
                origin_name if isinstance(origin_name, str) else None,
                destination_name if isinstance(destination_name, str) else None,
            )
        return None, None

    stop_names = dict(options.get("stop_id_dict", {}))
    stops = {}
    for stop_id, stop_data in options.get("stops", {}).items():
        if isinstance(stop_data, dict):
            stop_data = dict(stop_data)
            stop_names.setdefault(stop_id, stop_data.get("name"))
        else:
            stop_data = {}
        stops[stop_id] = stop_data

    for stop_id in options.get("stop_ids", []):
        stops.setdefault(stop_id, {})

    for stop_id, stop_data in stops.items():
        stop_name = _migrate_entity_registry_entry(
            entity_registry, entry, stop_id, stop_names.get(stop_id)
        )
        if stop_name:
            stop_names[stop_id] = stop_name
            stop_data.setdefault("name", stop_name)

    trips: dict[str, dict] = {}
    migrated_routes: set[tuple[str, str]] = set()
    for trip_key, trip_data in options.get("trips", {}).items():
        if not isinstance(trip_data, dict):
            _LOGGER.warning("Skipping invalid trip option %s during migration", trip_key)
            continue

        if "origin" in trip_data and "destination" in trip_data:
            origin = dict(trip_data["origin"])
            destination = dict(trip_data["destination"])
            origin_id = origin["id"]
            destination_id = destination["id"]
            origin_name = origin.get("name") or stop_names.get(origin_id)
            destination_name = destination.get("name") or stop_names.get(
                destination_id
            )
            trip_name = trip_data.get("name")
        else:
            stop_ids = [
                key
                for key in trip_data
                if key not in {"name", "max_interchanges"}
            ]
            if len(stop_ids) != 2:
                _LOGGER.warning(
                    "Skipping invalid trip option %s during migration", trip_key
                )
                continue
            origin_id, destination_id = stop_ids
            origin_name = trip_data.get(origin_id) or stop_names.get(origin_id)
            destination_name = trip_data.get(destination_id) or stop_names.get(
                destination_id
            )
            trip_name = trip_data.get("name") or trip_key

        new_trip_id = get_trip_id(origin_id, destination_id)
        legacy_unique_ids = (trip_key, slugify(trip_key))
        if trip_name:
            legacy_unique_ids += (slugify(trip_name),)
        cached_origin_name, cached_destination_name = cached_trip_station_names(
            new_trip_id, legacy_unique_ids
        )
        origin_name = origin_name or cached_origin_name
        destination_name = destination_name or cached_destination_name
        migrated_trip = {
            "origin": {"id": origin_id},
            "destination": {"id": destination_id},
        }
        if origin_name:
            migrated_trip["origin"]["name"] = origin_name
        if destination_name:
            migrated_trip["destination"]["name"] = destination_name
        if "max_interchanges" in trip_data:
            migrated_trip["max_interchanges"] = trip_data["max_interchanges"]

        route = (origin_id, destination_id)
        if route in migrated_routes:
            _LOGGER.warning("Skipping duplicate trip %s during migration", trip_key)
            continue
        migrated_routes.add(route)

        registry_entry = None
        for legacy_unique_id in legacy_unique_ids:
            registry_entity_id = entity_registry.async_get_entity_id(
                "sensor", DOMAIN, legacy_unique_id
            )
            if registry_entity_id is not None:
                registry_entry = entity_registry.async_get(registry_entity_id)
                if registry_entry is not None:
                    break

        # Keep the existing registry unique ID (and entity ID); only new trips
        # use the stop-pair ID generated by get_trip_id.
        trip_id = (
            registry_entry.unique_id
            if registry_entry is not None
            else slugify(trip_name or trip_key)
        )
        if trip_id in trips:
            _LOGGER.warning(
                "Skipping trip %s because its legacy unique ID is already used",
                trip_key,
            )
            continue
        trips[trip_id] = migrated_trip

        if not trip_name and trip_key != trip_id:
            trip_name = trip_key
        if registry_entry is not None and trip_name:
            entity_registry.async_update_entity(
                registry_entry.entity_id, original_name=trip_name
            )

    options.pop("stop_ids", None)
    options.pop("stop_id_dict", None)
    options["stops"] = stops
    options["trips"] = trips
    hass.config_entries.async_update_entry(entry, options=options, version=2)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Trias API from a config entry."""

    hass.data.setdefault(DOMAIN, {})

    hass.data[DOMAIN][entry.entry_id] = coordinator = TriasDataUpdateCoordinator(
        hass,
        entry,
        _LOGGER,
        name=entry.unique_id or DOMAIN,
        update_interval=DEFAULT_SCAN_INTERVAL,
    )

    await coordinator.async_config_entry_first_refresh()

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)

        # Client session schließen
        try:
            if coordinator and hasattr(coordinator, "client"):
                await coordinator.client.close()
        except Exception as err:
            _LOGGER.warning(f"Error closing client session: {err}")

    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
