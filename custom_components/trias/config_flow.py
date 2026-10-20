"""Config flow for Trias API integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector
from homeassistant.util import slugify
from requests.exceptions import MissingSchema

from .const import DEFAULT_DEPARTURE_LIMIT, DOMAIN, get_trip_id
from .trias_client import client as trias
from .trias_client.exceptions import HttpError, InvalidApiKey, InvalidRequest

_LOGGER = logging.getLogger(__name__)


def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    client = trias.Client(url=data["url"], api_key=data.get("api_key", ""))
    client.test_connection()


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Trias API."""

    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await self.hass.async_add_executor_job(
                    validate_input, self.hass, user_input
                )
            except InvalidRequest:
                errors["base"] = "invalid_request"
            except InvalidApiKey:
                errors["api_key"] = "invalid_api_key"
            except HttpError as err:
                errors["base"] = "http_error"
            except MissingSchema:
                errors["base"] = "invalid_url"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=user_input["name"], data=user_input
                )
        else:
            user_input = {}

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=user_input.get("name", "")): str,
                    vol.Required("url", default=user_input.get("url", "")): str,
                    vol.Optional("api_key", default=user_input.get("api_key", "")): str,
                }
            ),
            errors=errors,
        )

OPTIONS_MENU = ["stops", "trips"]


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle the option flow for the Trias integration."""

    def __init__(self) -> None:
        """Initialize options flow."""
        self._search_data = {}
        self._pending_trip_names: dict[str, str] = {}
        self._pending_trip_locations: dict[str, dict] = {}

    def _trip_already_exists(self, origin_id: str, destination_id: str) -> bool:
        """Return whether the ordered trip is already configured."""
        trip_id = get_trip_id(origin_id, destination_id)
        configured_trips = self.config_entry.options.get("trips", {})
        if trip_id in configured_trips:
            return True

        for trip in configured_trips.values():
            if not isinstance(trip, dict):
                continue
            if "origin" in trip and "destination" in trip:
                configured_origin = trip["origin"].get("id")
                configured_destination = trip["destination"].get("id")
            else:
                stop_ids = [
                    key for key in trip if key not in {"name", "max_interchanges"}
                ]
                if len(stop_ids) != 2:
                    continue
                configured_origin, configured_destination = stop_ids

            if (
                configured_origin == origin_id
                and configured_destination == destination_id
            ):
                return True

        return False

    def _show_station_selection(
        self,
        search_value: str,
        selected_station: str,
        errors: dict[str, str] | None = None,
    ) -> FlowResult:
        """Show search results with an optional selection error."""
        stop_point_names = ["search"] + list(self._search_data["stop_points"])
        return self.async_show_form(
            step_id="search_station",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "search_value", default=search_value
                    ): selector.TextSelector(selector.TextSelectorConfig()),
                    vol.Optional(
                        "station", default=selected_station
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=stop_point_names,
                            translation_key="station_search",
                        )
                    ),
                }
            ),
            errors=errors or {},
        )

    @property
    def config_entry(self):
        return self.hass.config_entries.async_get_entry(self.handler)

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,  # pylint: disable=unused-argument
    ) -> FlowResult:
        """Manage the options."""
        return self.async_show_menu(step_id="init", menu_options=OPTIONS_MENU)

    async def save(self, user_input, reload=True):
        """Save the options"""
        _LOGGER.debug("Saving options: %s", user_input)

        options = dict(self.config_entry.options)  # old options
        options.update(user_input)  # update old options with new options
        if reload:
            options.update({"toggle": not self.config_entry.options.get("toggle")})
        return self.async_create_entry(title="", data=options)

    async def async_step_stops(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show the stops options menu."""
        registry = er.async_get(self.hass)
        stop_ids = self.config_entry.options.get("stops", {})
        menu_options = ["add_stop"]
        if any(
            entity.config_entry_id == self.config_entry.entry_id
            and entity.domain == "sensor"
            and entity.unique_id in stop_ids
            for entity in registry.entities.values()
        ):
            menu_options.append("delete_stops")
        menu_options.append("global_options")
        return self.async_show_menu(step_id="stops", menu_options=menu_options)

    async def async_step_add_stop(
        self,
        user_input: dict[str, Any] | None = None,
        add: dict[str, str] | None = None,
    ) -> FlowResult:
        """Search for and immediately save a new stop."""
        if add is None:
            return await self.async_step_search_station(
                function=self.async_step_add_stop
            )

        stops = dict(self.config_entry.options.get("stops", {}))
        for stop_id, name in add.items():
            stops[stop_id] = {"name": name}
        return await self.save({"stops": stops})

    async def async_step_delete_stops(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Delete one or more configured stop sensors."""
        registry = er.async_get(self.hass)
        stop_ids = self.config_entry.options.get("stops", {})
        stop_entities = [
            entity
            for entity in registry.entities.values()
            if entity.config_entry_id == self.config_entry.entry_id
            and entity.domain == "sensor"
            and entity.unique_id in stop_ids
        ]
        if not stop_entities:
            return self.async_abort(reason="no_stop_sensors")

        if user_input is None:
            options = []
            for entity in stop_entities:
                state = self.hass.states.get(entity.entity_id)
                friendly_name = (
                    state.attributes.get("friendly_name") if state else None
                ) or entity.original_name or entity.entity_id
                options.append(
                    {
                        "label": f"{friendly_name} ({entity.entity_id})",
                        "value": entity.unique_id,
                    }
                )
            return self.async_show_form(
                step_id="delete_stops",
                data_schema=vol.Schema(
                    {
                        vol.Optional("stops", default=[]): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=options,
                                multiple=True,
                            )
                        )
                    }
                ),
            )

        selected_stops = set(user_input.get("stops", []))
        options = dict(self.config_entry.options)
        stops = dict(options.get("stops", {}))
        for entity in stop_entities:
            if entity.unique_id not in selected_stops:
                continue
            stops.pop(entity.unique_id, None)
            registry.async_remove(entity.entity_id)

        options["stops"] = stops
        return await self.save(options)

    async def async_step_global_options(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure options that apply to all sensors."""
        if user_input is not None:
            return await self.save(user_input)

        return self.async_show_form(
            step_id="global_options",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "departure_limit_config",
                        default=self.config_entry.options.get(
                            "departure_limit_config", DEFAULT_DEPARTURE_LIMIT
                        ),
                    ): vol.All(int, vol.Range(min=1))
                }
            ),
        )

    async def async_step_trips(
        self, user_input: dict[str, str] = None, add={}
    ) -> FlowResult:
        """Manage the trips options."""

        if user_input is None:
            trip_dict = self.config_entry.options.get("trips", {})
            trip_dict = {**trip_dict}
            trip_dict.update(add)
            for trip_id, trip in add.items():
                if isinstance(trip, dict):
                    self._pending_trip_locations[trip_id] = trip

            return self.async_show_form(
                step_id="trips",
                data_schema=vol.Schema(
                    {
                        vol.Optional(
                            "trips",
                            description={"suggested_value": trip_dict},
                        ): selector.ObjectSelector(),
                        vol.Optional("add_stop", default=False): bool,
                    }
                ),
            )

        if user_input["add_stop"]:
            return await self.async_step_search_station(
                function=self.async_step_trip_name, count=2
            )

        trips = user_input.get("trips", self.config_entry.options.get("trips", {}))
        trips = {
            trip_key: dict(trip) if isinstance(trip, dict) else trip
            for trip_key, trip in trips.items()
        }
        existing_trips = self.config_entry.options.get("trips", {})
        registry = er.async_get(self.hass)
        for trip_key, trip in trips.items():
            if not isinstance(trip, dict):
                continue

            previous_trip = existing_trips.get(trip_key, {})
            pending_trip = self._pending_trip_locations.get(trip_key, {})
            if "origin" in trip and "destination" in trip:
                for endpoint in ("origin", "destination"):
                    location = dict(trip[endpoint])
                    fallback_location = pending_trip.get(
                        endpoint, previous_trip.get(endpoint, {})
                    )
                    if not location.get("name"):
                        location["name"] = fallback_location.get("name", "")
                    trip[endpoint] = location
                origin_id = trip["origin"].get("id")
                destination_id = trip["destination"].get("id")
            else:
                stop_ids = [
                    key
                    for key in trip
                    if key not in {"name", "max_interchanges"}
                ]
                if len(stop_ids) != 2:
                    trip.pop("name", None)
                    continue
                origin_id, destination_id = stop_ids

            trip_id = trip_key
            trip_name = (
                self._pending_trip_names.get(trip_id)
                or self._pending_trip_names.get(trip_key)
                or trip.get("name")
            )
            if trip_name:
                registry.async_get_or_create(
                    "sensor",
                    DOMAIN,
                    trip_id,
                    config_entry=self.config_entry,
                    has_entity_name=True,
                    original_name=trip_name,
                    suggested_object_id=slugify(trip_name),
                )
            trip.pop("name", None)

        user_input["trips"] = trips

        return await self.save(user_input)

    async def async_step_trip_name(
        self, user_input: dict[str, str] = None, add={}
    ) -> FlowResult:
        """Manage the trip name options."""

        if user_input is None:
            return self.async_show_form(
                step_id="trip_name",
                data_schema=vol.Schema(
                    {
                        vol.Required("trip_name"): selector.TextSelector(),
                        vol.Required(
                            "trip",
                            description={"suggested_value": add},
                        ): selector.ObjectSelector(),
                        vol.Optional("max_interchanges"): vol.All(
                            int, vol.Range(min=0)
                        ),
                    }
                ),
            )

        trip_data = user_input["trip"]
        origin = trip_data["origin"]
        destination = trip_data["destination"]
        trip_id = get_trip_id(origin["id"], destination["id"])
        if self._trip_already_exists(origin["id"], destination["id"]):
            max_interchanges_field = vol.Optional("max_interchanges")
            if "max_interchanges" in user_input:
                max_interchanges_field = vol.Optional(
                    "max_interchanges", default=user_input["max_interchanges"]
                )
            return self.async_show_form(
                step_id="trip_name",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            "trip_name", default=user_input["trip_name"]
                        ): selector.TextSelector(),
                        vol.Required(
                            "trip",
                            description={"suggested_value": trip_data},
                        ): selector.ObjectSelector(),
                        max_interchanges_field: vol.All(int, vol.Range(min=0)),
                    }
                ),
                errors={"base": "trip_already_exists"},
            )

        trip = {
            trip_id: {
                "origin": origin,
                "destination": destination,
            }
        }
        if "max_interchanges" in user_input:
            trip[trip_id]["max_interchanges"] = user_input["max_interchanges"]
        self._pending_trip_names[trip_id] = user_input["trip_name"]
        return await self.async_step_trips(None, trip)

    async def async_step_search_station(
        self, user_input: dict[str, str] = None, function=None, count=1
    ) -> FlowResult:
        """Search and select stations for trips or stops."""

        # Setup function, count, and temporary return data
        if function:
            self._search_data["function"] = function
            self._search_data["return_data"] = {}
            self._search_data["count"] = count

        # Show search form
        if user_input is None:
            return self.async_show_form(
                step_id="search_station",
                data_schema=vol.Schema(
                    {
                        vol.Optional(
                            "search_value",
                        ): selector.TextSelector(selector.TextSelectorConfig()),
                    }
                ),
            )

        # Handle search query
        elif user_input.get("station", "search") == "search":
            # Get API credentials from config entry
            config_entry = self.config_entry
            api_key = config_entry.data.get("api_key", "")
            url = config_entry.data["url"]

            # SYNCHRONEN Client neu erstellen (nicht async)
            # Wir können hier keinen async Client verwenden, da self.hass.helpers nicht verfügbar ist
            client = trias.Client(url=url, api_key=api_key)

            try:
                # SYNCHRONER Aufruf mit async_add_executor_job
                data = await self.hass.async_add_executor_job(
                    client.location_information_request, user_input["search_value"], 4
                )

                stop_points = {}

                if "Location" in data:
                    locations = data["Location"]

                    # Multiple locations
                    if isinstance(locations, list):
                        for stop in locations:
                            stop_point_name = (
                                stop["Location"]["LocationName"]["Text"]
                                + ", "
                                + stop["Location"]["StopPoint"]["StopPointName"]["Text"]
                            )
                            stop_point_id = stop["Location"]["StopPoint"][
                                "StopPointRef"
                            ]
                            stop_points[stop_point_name] = stop_point_id
                    else:  # Single location
                        stop_point_name = (
                            locations["Location"]["LocationName"]["Text"]
                            + ", "
                            + locations["Location"]["StopPoint"]["StopPointName"][
                                "Text"
                            ]
                        )
                        stop_point_id = locations["Location"]["StopPoint"][
                            "StopPointRef"
                        ]
                        stop_points[stop_point_name] = stop_point_id

                self._search_data["stop_points"] = stop_points

                return self._show_station_selection(
                    user_input.get("search_value", ""), "search"
                )

            except Exception as err:
                _LOGGER.error(f"Error searching station: {err}")
                return self.async_show_form(
                    step_id="search_station",
                    data_schema=vol.Schema(
                        {
                            vol.Optional(
                                "search_value",
                                default=user_input.get("search_value", ""),
                            ): selector.TextSelector(selector.TextSelectorConfig()),
                        }
                    ),
                    errors={"base": "search_error"},
                )

        # Handle selection of a station
        else:
            selected_name = user_input["station"]
            selected_id = self._search_data["stop_points"][selected_name]

            if self._search_data["count"] == 1:
                configured_stops = self.config_entry.options.get("stops", {})
                if selected_id in configured_stops:
                    return self._show_station_selection(
                        user_input.get("search_value", ""),
                        selected_name,
                        errors={"base": "stop_already_exists"},
                    )
            elif len(self._search_data["return_data"]) == 1:
                origin_id = next(iter(self._search_data["return_data"].values()))
                if self._trip_already_exists(origin_id, selected_id):
                    return self._show_station_selection(
                        user_input.get("search_value", ""),
                        selected_name,
                        errors={"base": "trip_already_exists"},
                    )

            self._search_data["return_data"][selected_name] = selected_id

            # Check if we still need more stations
            if len(self._search_data["return_data"]) < self._search_data["count"]:
                return await self.async_step_search_station()

            # Map first selection to origin, second to destination (for trips)
            if self._search_data["count"] == 2:
                names = list(self._search_data["return_data"].keys())
                ids = list(self._search_data["return_data"].values())
                trip_data = {
                    "origin": {"id": ids[0], "name": names[0]},
                    "destination": {"id": ids[1], "name": names[1]},
                }
            else:
                # Single station case (e.g., stops)
                name, id_ = next(iter(self._search_data["return_data"].items()))
                trip_data = {id_: name}

            # Call the next step function with processed data
            _function = self._search_data["function"]
            return await _function(None, trip_data)
