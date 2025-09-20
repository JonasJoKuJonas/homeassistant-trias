"""Config flow for Trias API integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector
from requests.exceptions import MissingSchema

from .const import DEFAULT_DEPARTURE_LIMIT, DOMAIN
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

    VERSION = 1

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


OPTIONS_MENU = {"stops": "Stops", "trips": "Trips"}


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle the option flow for WebUntis."""

    def __init__(self) -> None:
        """Initialize options flow."""
        self._search_data = {}

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
        self, user_input: dict[str, str] = None, add={}
    ) -> FlowResult:
        """Manage the stops options."""

        if user_input is None:
            stop_id_dict = self.config_entry.options.get("stop_id_dict", {})
            stop_id_dict.update(add)

            return self.async_show_form(
                step_id="stops",
                data_schema=vol.Schema(
                    {
                        vol.Optional(
                            "stop_id_dict",
                            description={"suggested_value": stop_id_dict},
                        ): selector.ObjectSelector(),
                        vol.Optional("add_stop", default=False): bool,
                        vol.Optional(
                            "departure_limit_config",
                            default=self.config_entry.options.get(
                                "departure_limit_config", DEFAULT_DEPARTURE_LIMIT
                            ),
                        ): int,
                    }
                ),
            )

        if user_input["add_stop"]:
            return await self.async_step_search_station(function=self.async_step_stops)

        if "stop_id_dict" in user_input:
            user_input["stop_ids"] = list(user_input["stop_id_dict"].keys())

        return await self.save(user_input)

    async def async_step_trips(
        self, user_input: dict[str, str] = None, add={}
    ) -> FlowResult:
        """Manage the trips options."""

        if user_input is None:
            trip_dict = self.config_entry.options.get("trips", {})
            trip_dict.update(add)

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

        if "trips" in user_input:
            pass  # validate input

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
                        vol.Optional(
                            "trip",
                            description={"suggested_value": add},
                        ): selector.ObjectSelector(),
                    }
                ),
            )
        else:
            trip = {
                user_input["trip_name"]: {
                    "origin": user_input["trip"]["origin"],
                    "destination": user_input["trip"]["destination"],
                }
            }
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
            client = self.hass.data[DOMAIN][self.config_entry.entry_id].client

            # Fetch locations from WebUntis
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
                        stop_point_id = stop["Location"]["StopPoint"]["StopPointRef"]
                        stop_points[stop_point_name] = stop_point_id
                else:  # Single location
                    stop_point_name = (
                        locations["Location"]["LocationName"]["Text"]
                        + ", "
                        + locations["Location"]["StopPoint"]["StopPointName"]["Text"]
                    )
                    stop_point_id = locations["Location"]["StopPoint"]["StopPointRef"]
                    stop_points[stop_point_name] = stop_point_id

            stop_point_names = ["search"] + list(stop_points.keys())
            self._search_data["stop_points"] = stop_points
            # Show selection form
            return self.async_show_form(
                step_id="search_station",
                data_schema=vol.Schema(
                    {
                        vol.Optional(
                            "search_value",
                            default=user_input.get("search_value", ""),
                        ): selector.TextSelector(selector.TextSelectorConfig()),
                        vol.Optional(
                            "station", default="search"
                        ): selector.SelectSelector(
                            selector.SelectSelectorConfig(options=stop_point_names)
                        ),
                    }
                ),
            )

        # Handle selection of a station
        else:
            selected_name = user_input["station"]
            selected_id = self._search_data["stop_points"][selected_name]
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
