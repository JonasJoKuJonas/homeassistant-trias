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

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# TODO adjust the data schema to the data that you need
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("url"): str,
        vol.Optional("api_key"): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """

    # Return info that you want to store in the config entry.
    return {"title": "Name of the device"}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Trias API."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


OPTIONS_MENU = {"stops": "Stops", "trips": "Trips"}


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle the option flow for WebUntis."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry
        self._search_data = {}

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
                        vol.Optional("departure_limit_config", default=5): int,
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
                        vol.Optional("trip_name"): selector.TextSelector(),
                        vol.Optional(
                            "trip",
                            description={"suggested_value": add},
                        ): selector.ObjectSelector(),
                    }
                ),
            )
        else:
            trip = {user_input["trip_name"]: user_input["trip"]}
            return await self.async_step_trips(None, trip)

    async def async_step_search_station(
        self, user_input: dict[str, str] = None, function=None, count=1
    ) -> FlowResult:
        if function:
            self._search_data["function"] = function
            self._search_data["return_data"] = {}
            self._search_data["count"] = count

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
        elif user_input.get("station", "search") == "search":
            client = self.hass.data[DOMAIN][self.config_entry.entry_id].client

            data = await self.hass.async_add_executor_job(
                client.location_information_request, user_input["search_value"], 4
            )

            stop_points = {}

            if "Location" in data:
                locations = data["Location"]

                if isinstance(locations, list):  # Handling multiple locations
                    for stop in locations:
                        _LOGGER.warning(stop)
                        stop_point_name = (
                            stop["Location"]["LocationName"]["Text"]
                            + ", "
                            + stop["Location"]["StopPoint"]["StopPointName"]["Text"]
                        )
                        stop_point_id = stop["Location"]["StopPoint"]["StopPointRef"]
                        stop_points[stop_point_name] = stop_point_id
                else:  # Handling single location
                    stop_point_name = (
                        locations["Location"]["LocationName"]["Text"]
                        + ", "
                        + locations["Location"]["StopPoint"]["StopPointName"]["Text"]
                    )
                    stop_point_id = locations["Location"]["StopPoint"]["StopPointRef"]
                    stop_points[stop_point_name] = stop_point_id

            stop_point_names = ["search"] + list(stop_points.keys())

            self._search_data["stop_points"] = stop_points

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
        else:
            self._search_data["return_data"][
                self._search_data["stop_points"][user_input["station"]]
            ] = user_input["station"]

            if len(self._search_data["return_data"]) < self._search_data["count"]:
                return await self.async_step_search_station()
            _function = self._search_data["function"]
            return await _function(None, self._search_data["return_data"])


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
