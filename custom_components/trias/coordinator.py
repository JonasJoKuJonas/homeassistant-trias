"""The Trias update coordinator."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_LATITUDE, ATTR_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .trias_client import client as trias
from .trias_client.exceptions import ApiError, InvalidLocationName, HttpError


from homeassistant.exceptions import ConfigEntryNotReady
from requests.exceptions import RequestException

from .const import DEFAULT_DEPARTURE_LIMIT

_LOGGER = logging.getLogger(__name__)


class TriasDataUpdateCoordinator(DataUpdateCoordinator):
    """Get the latest data from the API."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        logger: logging.Logger,
        name: str,
        update_interval: int,
    ) -> None:
        """Initialize the data object."""

        super().__init__(
            hass=hass,
            logger=logger,
            name=name,
            update_interval=timedelta(minutes=update_interval),
        )

        self._hass = hass
        self._entry = entry
        self._config = entry.options

        self.name = entry.title

        self._setup = False

        self._url: str = entry.data["url"]
        self._api_key: str = entry.data.get("api_key", "")

        self.client: trias.Client = trias.Client(url=self._url, api_key=self._api_key)
        self.stop_ids: list[str] = entry.options.get("stop_ids", [])
        self.departure_limit: str = entry.options.get(
            "departure_limit_config", DEFAULT_DEPARTURE_LIMIT
        )
        self.stops: dict[dict] = {}

        self.trip_list: list[str] = entry.options.get("trips", {})
        # {
        #    "origin": {"id": "...", "name": "..."},
        #    "destination": {"id": "...", "name": "..."},
        # }

        self.trips = {}

    async def setup(self) -> bool:
        """Set up the Trias API."""

        stop_id_dict = {}

        for stop_id in self.stop_ids:
            stop_dict = {
                "id": stop_id,
                "created": False,
                "ok": True,
                "prevestly_ok": False,
                "attrs": {},
                "data": {},
            }

            try:
                station_data = await self.hass.async_add_executor_job(
                    self.client.get_station_data, stop_id
                )
            except ApiError as error:
                _LOGGER.error("Could not request data for %s reason %s", stop_id, error)
                stop_dict["ok"] = False
                continue
            except InvalidLocationName as error:
                _LOGGER.error("Could not request data for %s reason %s", stop_id, error)
                stop_dict["ok"] = False
                continue
            except HttpError as error:
                _LOGGER.error(f"Http error {error.status_code}:\n{error.response}")
                stop_dict["ok"] = False
                continue

            stop_dict["name"] = (
                station_data["LocationName"]["Text"]
                + ", "
                + station_data["StopPoint"]["StopPointName"]["Text"]
            )

            stop_dict["attrs"][ATTR_LATITUDE] = station_data["GeoPosition"]["Latitude"]
            stop_dict["attrs"][ATTR_LONGITUDE] = station_data["GeoPosition"][
                "Longitude"
            ]

            self.stops[stop_id] = stop_dict

            self.add_stop(stop_dict)

            # update options

            if (
                not self._config.get("stop_id_dict", {}).get(stop_id)
                or self._config["stop_id_dict"][stop_id] != stop_dict["name"]
            ):
                stop_id_dict[stop_id] = stop_dict["name"]

        if stop_id_dict:
            options = {**self._config}

            options["stop_id_dict"] = {
                **options.get("stop_id_dict", {}),
                **stop_id_dict,
            }

            _LOGGER.info("Updatet stop infos: \n%s", stop_id_dict)
            self._hass.config_entries.async_update_entry(self._entry, options=options)

        for trip_name, locations in self.trip_list.items():
            trip_id = trip_name.lower().replace(" ", "-")

            if "origin" in locations and "destination" in locations:
                # New format
                from_location_id = locations["origin"]["id"]
                from_location_name = locations["origin"].get("name", "")
                to_location_id = locations["destination"]["id"]
                to_location_name = locations["destination"].get("name", "")
            else:
                # Old format
                ids = list(locations.keys())
                from_location_id, to_location_id = ids
                from_location_name, to_location_name = "", ""

            try:
                from_station_data = await self._hass.async_add_executor_job(
                    self.client.get_station_data, from_location_id
                )
                to_station_data = await self._hass.async_add_executor_job(
                    self.client.get_station_data, to_location_id
                )

            except ApiError as error:
                _LOGGER.error(
                    "Could not request data for %s reason %s", trip_name, error
                )
                continue
            except InvalidLocationName as error:
                _LOGGER.error(
                    "Could not request data for %s reason %s", trip_name, error
                )
                continue

            from_name = (
                from_station_data["LocationName"]["Text"]
                + ", "
                + from_station_data["StopPoint"]["StopPointName"]["Text"]
            )
            to_name = (
                to_station_data["LocationName"]["Text"]
                + ", "
                + to_station_data["StopPoint"]["StopPointName"]["Text"]
            )

            _LOGGER.info(from_name + " " + to_name)
            _LOGGER.info(from_location_name + " " + to_location_name)

            if from_location_name != from_name or to_location_name != to_name:
                options = {**self._config}

                options["trips"][trip_name] = {
                    "origin": {"id": from_location_id, "name": from_name},
                    "destination": {"id": to_location_id, "name": to_name},
                }

                _LOGGER.info("Updatet trip infos: '%s'", trip_name)
                self._hass.config_entries.async_update_entry(
                    self._entry, options=options
                )

            trip_dict = {
                "id": trip_id,
                "created": False,
                "ok": True,
                "prevestly_ok": False,
                "name": trip_name,
                "from": from_location_id,
                "to": to_location_id,
                "data": {},
                "attrs": {
                    "from": from_name,
                    "to": to_name,
                },
            }

            self.trips[trip_id] = trip_dict
            self.add_trip(trip_dict)

        return True

    async def _async_update_data(self) -> dict:
        """Get the latest data from the Trias API."""

        if not self._setup:
            try:
                setup_ok = await self.setup()
            except RequestException as err:
                raise ConfigEntryNotReady from err
            if not setup_ok:
                _LOGGER.error("Could not setup integration")
                return False
            self._setup = True

        _LOGGER.debug("Fetching new data from Trias API")

        for stop_id, data in self.stops.items():
            self.stops[stop_id]["prevestly_ok"] = self.stops[stop_id]["ok"]
            try:
                departures = await self._hass.async_add_executor_job(
                    self.client.get_departures, stop_id, self.departure_limit
                )
            except ApiError as err:
                self.stops[stop_id]["ok"] = False
                self.stops[stop_id]["data"] = {}
                status = {
                    "ok": False,
                    "message": err,
                    "exception": True,
                }
            else:
                data = {}

                if departures[0]["EstimatedTime"]:
                    data["next_departure"] = departures[0]["EstimatedTime"]
                else:
                    data["next_departure"] = departures[0]["TimetabledTime"]

                departure_attr = []
                for departure in departures:
                    departure_attr.append(
                        {
                            "Mode": departure["mode"],
                            "StopPointName": departure["StopPointName"],
                            "LineName": departure["LineName"],
                            "DestinationText": departure["DestinationText"],
                            "StartTime": departure["EstimatedTime"]
                            or departure["TimetabledTime"],
                            "TimetabledTime": departure["TimetabledTime"],
                            "EstimatedTime": departure["EstimatedTime"],
                            "PlannedBay": departure.get("PlannedBay"),
                            "Delay": (
                                str(departure["Delay"])
                                if departure.get("Delay")
                                else None
                            ),
                            "DelaySeconds": (
                                int(departure["Delay"].total_seconds())
                                if departure.get("Delay") is not None
                                else 0
                            ),
                            "DelayMinutes": (
                                int(departure["Delay"].total_seconds() / 60)
                                if departure.get("Delay") is not None
                                else 0
                            ),
                        }
                    )

                self.stops[stop_id]["data"] = data

                self.stops[stop_id]["attrs"]["departures"] = departure_attr

                status = {
                    "ok": True,
                }

            if not status["ok"] and self.stops[stop_id]["prevestly_ok"]:
                _LOGGER.error(
                    "Error when updating stop %s: %s",
                    stop_id,
                    status["message"],
                )
                continue
        # _LOGGER.debug("Stops:\n" + json.dumps(self.stops, default=str, indent=2))

        for trip_id, data in self.trips.items():
            self.trips[trip_id]["prevestly_ok"] = self.trips[trip_id]["ok"]
            try:
                trips = await self._hass.async_add_executor_job(
                    self.client.get_trip,
                    data["from"],
                    data["to"],
                    self.departure_limit,
                )

            except ApiError as err:
                self.trips[trip_id]["ok"] = False
                self.trips[trip_id]["data"] = {}
                status = {
                    "ok": False,
                    "message": err,
                    "exception": True,
                }
            else:
                if not trips:
                    self.trips[trip_id]["ok"] = False
                    self.trips[trip_id]["data"] = {}
                    status = {
                        "ok": False,
                        "message": "Keine Trips gefunden",
                        "exception": False,
                    }
                else:
                    # Erster Trip wird als Hauptwert verwendet
                    first_trip = trips[0]

                    # Daten für den Haupt-Sensorwert (erster Trip)
                    if first_trip.get("EstimatedStartTime"):
                        next_departure = first_trip["EstimatedStartTime"]
                    else:
                        next_departure = first_trip["StartTime"]

                    data = {"start": next_departure}

                    # _LOGGER.debug("Trip %s data %s", trip_id, first_trip)

                    # Attributes für den ersten Trip
                    attr = {
                        "StartTime": first_trip["StartTime"],
                        "TimetabledStartTime": first_trip["StartTimetabledTime"],
                        "EstimatedStartTime": first_trip.get("StartEstimatedTime"),
                        "EndTime": first_trip["EndTime"],
                        "TimetabledEndTime": first_trip.get("EndTimetabledTime"),
                        "EstimatedEndTime": first_trip.get("EstimatedEndTime"),
                        "Interchanges": first_trip["Interchanges"],
                        "LineName": first_trip["Transportation"][0]["LineName"],
                        "DestinationText": first_trip["Transportation"][0][
                            "DestinationText"
                        ],
                        "Duration": first_trip["Duration"],
                        "Delay": (
                            str(first_trip["Delay"])
                            if first_trip.get("Delay")
                            else None
                        ),
                        "DelaySeconds": (
                            int(first_trip["Delay"].total_seconds())
                            if first_trip.get("Delay") is not None
                            else 0
                        ),
                        "DelayMinutes": (
                            int(first_trip["Delay"].total_seconds() / 60)
                            if first_trip.get("Delay") is not None
                            else 0
                        ),
                    }

                    # Weitere Trips als departures-Liste
                    departures = []
                    for idx, trip in enumerate(trips):
                        trip_info = {
                            "index": idx,
                            "StartTime": trip["StartTime"],
                            "TimetabledStartTime": trip["StartTimetabledTime"],
                            "EstimatedStartTime": trip.get("StartEstimatedTime"),
                            "EndTime": trip["EndTime"],
                            "TimetabledEndTime": trip.get("EndTimetabledTime"),
                            "EstimatedEndTime": trip.get("EstimatedEndTime"),
                            "Interchanges": trip["Interchanges"],
                            "LineName": trip["Transportation"][0]["LineName"],
                            "DestinationText": trip["Transportation"][0][
                                "DestinationText"
                            ],
                            "Duration": trip["Duration"],
                            "Delay": (
                                str(trip["Delay"]) if trip.get("Delay") else None
                            ),
                            "DelaySeconds": (
                                int(trip["Delay"].total_seconds())
                                if trip.get("Delay") is not None
                                else 0
                            ),
                            "DelayMinutes": (
                                int(trip["Delay"].total_seconds() / 60)
                                if trip.get("Delay") is not None
                                else 0
                            ),
                        }

                        # Berechne Verzögerung für Abfahrt
                        if trip_info.get("EstimatedStartTime") and trip_info.get(
                            "StartTime"
                        ):
                            delay = (
                                trip_info["EstimatedStartTime"] - trip_info["StartTime"]
                            )
                            trip_info["CurrentDelay"] = str(delay)
                            trip_info["CurrentDelayMinutes"] = int(
                                delay.total_seconds() / 60
                            )

                        departures.append(trip_info)

                    attr["departures"] = departures

                    # Füge zusätzlich die Anzahl der verfügbaren Trips hinzu
                    attr["available_trips"] = len(trips)

                    self.trips[trip_id]["data"] = data
                    self.trips[trip_id]["attrs"].update(attr)

                    status = {
                        "ok": True,
                    }

            if not status["ok"] and self.trips[trip_id]["prevestly_ok"]:
                _LOGGER.warning(
                    "Error when updating trip %s: %s",
                    trip_id,
                    status["message"],
                )
                continue

        return True

    def add_stop(self, stop: dict):
        """Add stop to the entity list."""

        if stop["created"]:
            _LOGGER.warning(
                "Sensor for station with id %s was already created", stop["id"]
            )
            return

        self.stops[stop["id"]]["created"] = True
        _LOGGER.debug("add_stop %s", stop["id"])

    def add_trip(self, trip: dict):
        """Add trip to the entity list."""

        if trip["created"]:
            _LOGGER.warning(
                "Sensor for station with id %s was already created", trip["id"]
            )
            return

        self.trips[trip["id"]]["created"] = True
        _LOGGER.debug("add_trip %s", trip["id"])


class DummyException(Exception):
    pass
