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
        self._pending_stop_edits: list[str] = []
        self._pending_stop_edit_index = 0
        self._pending_stop_options: dict[str, Any] = {}
        self._pending_trip_edits: list[str] = []
        self._pending_trip_edit_index = 0
        self._pending_trip_options: dict[str, Any] = {}
        self._pending_trip_data: dict[str, Any] = {}

    def _configured_stop_entities(self) -> list[Any]:
        """Return registered sensor entities for configured stops."""
        registry = er.async_get(self.hass)
        stop_ids = self.config_entry.options.get("stops", {})
        return [
            entity
            for entity in registry.entities.values()
            if entity.config_entry_id == self.config_entry.entry_id
            and entity.domain == "sensor"
            and entity.unique_id in stop_ids
        ]

    def _configured_trip_entities(self) -> list[Any]:
        """Return registered sensor entities for configured trips."""
        registry = er.async_get(self.hass)
        trip_ids = self.config_entry.options.get("trips", {})
        return [
            entity
            for entity in registry.entities.values()
            if entity.config_entry_id == self.config_entry.entry_id
            and entity.domain == "sensor"
            and entity.unique_id in trip_ids
        ]

    @staticmethod
    def _trip_route_names(trip: dict[str, Any]) -> tuple[str, str]:
        """Return the saved origin and destination names of a trip."""
        if "origin" in trip and "destination" in trip:
            origin = trip["origin"]
            destination = trip["destination"]
            return (
                str(origin.get("name") or origin.get("id") or ""),
                str(destination.get("name") or destination.get("id") or ""),
            )

        stop_ids = [
            stop_id
            for stop_id in trip
            if stop_id not in {"name", "max_interchanges"}
        ]
        if len(stop_ids) == 2:
            return (
                str(trip.get(stop_ids[0]) or stop_ids[0]),
                str(trip.get(stop_ids[1]) or stop_ids[1]),
            )
        return "", ""

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

    def _station_step_id(self) -> str:
        """Return the step for the current station selection."""
        if self._search_data.get("count") == 2:
            if len(self._search_data["return_data"]) == 1:
                return "trip_destination"
            return "trip_origin"
        return "search_station"

    def _station_description_placeholders(self) -> dict[str, str]:
        """Return placeholders for the current station-selection prompt."""
        if self._station_step_id() == "trip_destination":
            origin_name = next(iter(self._search_data["return_data"]))
            return {"origin": origin_name}
        return {}

    def _show_station_selection(
        self,
        search_value: str,
        selected_station: str,
        errors: dict[str, str] | None = None,
    ) -> FlowResult:
        """Show search results with an optional selection error."""
        stop_point_names = ["search"] + list(self._search_data["stop_points"])
        return self.async_show_form(
            step_id=self._station_step_id(),
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
            description_placeholders=self._station_description_placeholders(),
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
        stop_entities = self._configured_stop_entities()
        menu_options = ["add_stop"]
        if stop_entities:
            menu_options.extend(["edit_stops", "delete_stops"])
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
        stop_entities = self._configured_stop_entities()
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

    async def async_step_edit_stops(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select stops to edit in sequence."""
        stop_entities = self._configured_stop_entities()
        if not stop_entities:
            return self.async_abort(reason="no_stop_sensors")

        if user_input is not None:
            configured_stops = self.config_entry.options.get("stops", {})
            self._pending_stop_edits = [
                stop_id
                for stop_id in user_input.get("stops", [])
                if isinstance(configured_stops.get(stop_id), dict)
            ]
            self._pending_stop_edit_index = 0
            self._pending_stop_options = {
                stop_id: dict(stop) if isinstance(stop, dict) else stop
                for stop_id, stop in configured_stops.items()
            }
            if not self._pending_stop_edits:
                return await self.save({})
            return await self.async_step_edit_stop()

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
            step_id="edit_stops",
            data_schema=vol.Schema(
                {
                    vol.Required("stops", default=[]): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options, multiple=True)
                    )
                }
            ),
        )

    async def async_step_edit_stop(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit the result limit for each selected stop."""
        if user_input is not None:
            stop_id = self._pending_stop_edits[self._pending_stop_edit_index]
            stop_data = self._pending_stop_options[stop_id]
            if "departure_limit" in user_input:
                stop_data["departure_limit"] = user_input["departure_limit"]
            else:
                stop_data.pop("departure_limit", None)
            self._pending_stop_edit_index += 1
            if self._pending_stop_edit_index == len(self._pending_stop_edits):
                return await self.save({"stops": self._pending_stop_options})

        stop_id = self._pending_stop_edits[self._pending_stop_edit_index]
        stop = self._pending_stop_options.get(stop_id, {})
        registry = er.async_get(self.hass)
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, stop_id)
        registry_entity = registry.async_get(entity_id) if entity_id else None
        state = self.hass.states.get(entity_id) if entity_id else None
        friendly_name = (
            state.attributes.get("friendly_name") if state else None
        ) or (
            registry_entity.original_name
            if registry_entity is not None
            else entity_id or stop_id
        )
        schema_field = vol.Optional("departure_limit")
        if stop.get("departure_limit") is not None:
            schema_field = vol.Optional(
                "departure_limit", default=stop["departure_limit"]
            )
        return self.async_show_form(
            step_id="edit_stop",
            data_schema=vol.Schema(
                {schema_field: vol.All(int, vol.Range(min=1))}
            ),
            description_placeholders={
                "friendly_name": friendly_name,
                "entity_id": entity_id or "",
            },
        )

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
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show the trips options menu."""
        menu_options = ["add_trip", "global_trip_options"]
        if self._configured_trip_entities():
            menu_options[1:1] = ["edit_trips", "delete_trips"]
        return self.async_show_menu(step_id="trips", menu_options=menu_options)

    async def async_step_add_trip(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Search for the origin and destination of a new trip."""
        return await self.async_step_search_station(
            function=self.async_step_trip_name, count=2
        )

    async def async_step_trip_origin(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        """Handle searching for or selecting a trip origin."""
        return await self.async_step_search_station(user_input)

    async def async_step_trip_destination(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        """Handle searching for or selecting a trip destination."""
        return await self.async_step_search_station(user_input)

    async def async_step_edit_trips(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select trips to edit in sequence."""
        trip_entities = self._configured_trip_entities()
        if not trip_entities:
            return self.async_abort(reason="no_trip_sensors")

        if user_input is not None:
            configured_trips = self.config_entry.options.get("trips", {})
            self._pending_trip_edits = [
                trip_id
                for trip_id in user_input.get("trips", [])
                if isinstance(configured_trips.get(trip_id), dict)
            ]
            self._pending_trip_edit_index = 0
            self._pending_trip_options = {
                trip_id: dict(trip) if isinstance(trip, dict) else trip
                for trip_id, trip in configured_trips.items()
            }
            if not self._pending_trip_edits:
                return await self.save({})
            return await self.async_step_edit_trip()

        options = []
        for entity in trip_entities:
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
            step_id="edit_trips",
            data_schema=vol.Schema(
                {
                    vol.Required("trips", default=[]): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options, multiple=True),

                    )
                }
            ),
        )

    async def async_step_edit_trip(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit the interchange limit for each selected trip."""
        if user_input is not None:
            trip_id = self._pending_trip_edits[self._pending_trip_edit_index]
            trip_data = self._pending_trip_options[trip_id]
            if "max_interchanges" in user_input:
                trip_data["max_interchanges"] = user_input["max_interchanges"]
            else:
                trip_data.pop("max_interchanges", None)
            self._pending_trip_edit_index += 1
            if self._pending_trip_edit_index == len(self._pending_trip_edits):
                return await self.save({"trips": self._pending_trip_options})

        trip_id = self._pending_trip_edits[self._pending_trip_edit_index]
        trip = self._pending_trip_options.get(trip_id, {})
        origin, destination = self._trip_route_names(trip)
        registry = er.async_get(self.hass)
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, trip_id)
        registry_entity = registry.async_get(entity_id) if entity_id else None
        state = self.hass.states.get(entity_id) if entity_id else None
        friendly_name = (
            state.attributes.get("friendly_name") if state else None
        ) or (
            registry_entity.original_name
            if registry_entity is not None
            else entity_id or trip_id
        )
        schema_field = vol.Optional("max_interchanges")
        if trip.get("max_interchanges") is not None:
            schema_field = vol.Optional(
                "max_interchanges", default=trip["max_interchanges"]
            )
        return self.async_show_form(
            step_id="edit_trip",
            data_schema=vol.Schema(
                {schema_field: vol.All(int, vol.Range(min=0))}
            ),
            description_placeholders={
                "friendly_name": friendly_name,
                "entity_id": entity_id or "",
                "origin": origin,
                "destination": destination,
            },
        )

    async def async_step_delete_trips(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Delete one or more configured trips."""
        trip_entities = self._configured_trip_entities()
        if not trip_entities:
            return self.async_abort(reason="no_trip_sensors")

        if user_input is None:
            options = []
            for entity in trip_entities:
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
                step_id="delete_trips",
                data_schema=vol.Schema(
                    {
                        vol.Optional("trips", default=[]): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=options,
                                multiple=True,
                            )
                        )
                    }
                ),
            )

        selected_trips = set(user_input.get("trips", []))
        trips = dict(self.config_entry.options.get("trips", {}))
        registry = er.async_get(self.hass)
        for entity in trip_entities:
            if entity.unique_id in selected_trips:
                trips.pop(entity.unique_id, None)
                registry.async_remove(entity.entity_id)
        return await self.save({"trips": trips})

    async def async_step_global_trip_options(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure the global default trip interchange limit."""
        if user_input is not None:
            options = dict(self.config_entry.options)
            if "global_max_interchanges" in user_input:
                options["global_max_interchanges"] = user_input[
                    "global_max_interchanges"
                ]
            else:
                options.pop("global_max_interchanges", None)
            options["toggle"] = not self.config_entry.options.get("toggle")
            return self.async_create_entry(title="", data=options)

        current_value = self.config_entry.options.get("global_max_interchanges")
        schema_field = vol.Optional("global_max_interchanges")
        if current_value is not None:
            schema_field = vol.Optional(
                "global_max_interchanges", default=current_value
            )
        return self.async_show_form(
            step_id="global_trip_options",
            data_schema=vol.Schema(
                {schema_field: vol.All(int, vol.Range(min=0))}
            ),
        )

    async def async_step_trip_name(
        self,
        user_input: dict[str, Any] | None = None,
        add: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Manage the trip name options."""
        if add is not None:
            self._pending_trip_data = add

        trip_data = self._pending_trip_data
        origin = trip_data["origin"]
        destination = trip_data["destination"]
        route_placeholders = {
            "origin": origin.get("name") or origin.get("id", ""),
            "destination": destination.get("name") or destination.get("id", ""),
        }

        if user_input is None:
            return self.async_show_form(
                step_id="trip_name",
                data_schema=vol.Schema(
                    {
                        vol.Required("trip_name"): selector.TextSelector(),
                        vol.Optional("max_interchanges"): vol.All(
                            int, vol.Range(min=0)
                        ),
                    }
                ),
                description_placeholders=route_placeholders,
            )

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
                        max_interchanges_field: vol.All(int, vol.Range(min=0)),
                    }
                ),
                errors={"base": "trip_already_exists"},
                description_placeholders=route_placeholders,
            )

        trip = {
            "origin": origin,
            "destination": destination,
        }
        if "max_interchanges" in user_input:
            trip["max_interchanges"] = user_input["max_interchanges"]

        trips = dict(self.config_entry.options.get("trips", {}))
        trips[trip_id] = trip
        er.async_get(self.hass).async_get_or_create(
            "sensor",
            DOMAIN,
            trip_id,
            config_entry=self.config_entry,
            has_entity_name=True,
            original_name=user_input["trip_name"],
            suggested_object_id=slugify(user_input["trip_name"]),
        )
        return await self.save({"trips": trips})

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
                step_id=self._station_step_id(),
                data_schema=vol.Schema(
                    {
                        vol.Optional(
                            "search_value",
                        ): selector.TextSelector(selector.TextSelectorConfig()),
                    }
                ),
                description_placeholders=self._station_description_placeholders(),
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
                    step_id=self._station_step_id(),
                    data_schema=vol.Schema(
                        {
                            vol.Optional(
                                "search_value",
                                default=user_input.get("search_value", ""),
                            ): selector.TextSelector(selector.TextSelectorConfig()),
                        }
                    ),
                    errors={"base": "search_error"},
                    description_placeholders=self._station_description_placeholders(),
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
                if origin_id == selected_id:
                    return self._show_station_selection(
                        user_input.get("search_value", ""),
                        selected_name,
                        errors={"base": "same_trip_stops"},
                    )
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
