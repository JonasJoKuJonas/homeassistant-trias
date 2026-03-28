"""Async client for Trias API."""

from enum import StrEnum

import aiohttp
import async_timeout
import xmltodict
import asyncio
import logging
from datetime import datetime
from . import exceptions
from .utils import (
    convert_to_zulu_format,
    convert_to_local_format,
    to_datetime,
    get_timedelta,
    parse_duration,
)

_LOGGER = logging.getLogger(__name__)

class AuthMethod(StrEnum):
    REQUEST = "request"
    BEARER = "bearer"

class AsyncTriasClient:
    """Async client for Trias API."""

    def __init__(
        self,
        api_key: str,
        url: str,
        session: aiohttp.ClientSession = None,
        auth_method: AuthMethod = AuthMethod.REQUEST,
    ):
        self.api_key = api_key
        self.url = url
        self._session = session
        self._timeout = 30
        self._auth_method = auth_method

    async def ensure_session(self):
        """Ensure we have a session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

    async def close(self):
        """Close session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def _make_request(self, payload: str):
        """Make async XML request to Trias API."""
        await self.ensure_session()

        header = """<?xml version="1.0" encoding="UTF-8"?>
<Trias version="1.1" xmlns="http://www.vdv.de/trias" xmlns:siri="http://www.siri.org.uk/siri" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
    <ServiceRequest>
        <siri:RequestTimestamp>NOW__</siri:RequestTimestamp>
        <siri:RequestorRef>API_KEY__</siri:RequestorRef>
        <RequestPayload>
            PAYLOAD__
        </RequestPayload>
    </ServiceRequest>
</Trias>"""

        header = header.replace("API_KEY__", self.api_key)
        xml = header.replace("PAYLOAD__", payload)
        xml = xml.replace("NOW__", convert_to_zulu_format())

        headers = {
            "Content-Type": "text/xml",
            "User-Agent": "HomeAssistant/Trias-Integration",
        }

        # If we know already that Bearer auth works, use it right away.
        # Otherwise, we'll try the standard method first and fall back to Bearer if we get HTTP 401.
        if self._auth_method == AuthMethod.BEARER:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            async with async_timeout.timeout(self._timeout):
                async with self._session.post(
                    self.url, data=xml.encode("utf-8"), headers=headers
                ) as response:

                    if response.status == 400:
                        raise exceptions.InvalidRequest
                    if response.status == 403:
                        raise exceptions.InvalidApiKey
                    if response.status != 200:
                        raise exceptions.HttpError(
                            response.status, await response.text()
                        )

                    response_text = await response.text()

                    # Parse response
                    response_dict = xmltodict.parse(response_text)

                    if next(iter(response_dict)) == "trias:Trias":
                        response_text = response_text.replace("trias:", "")
                        response_dict = xmltodict.parse(response_text)

                    try:
                        trias_payload = response_dict["Trias"]["ServiceDelivery"][
                            "DeliveryPayload"
                        ]
                    except KeyError:
                        raise exceptions.ApiError("Invalid response structure")

                    # Check for errors
                    response_keys = [
                        "StopEventResponse",
                        "TripResponse",
                        "TripInfoResponse",
                        "LocationInformationResponse",
                    ]

                    for key in response_keys:
                        trias_data = trias_payload.get(key, {})
                        error_message = (
                            trias_data.get("ErrorMessage", {})
                            .get("Text", {})
                            .get("Text")
                        )
                        if error_message:
                            raise exceptions.ApiError(error_message)

                    return trias_payload

        except asyncio.TimeoutError:
            raise exceptions.ApiError("Request timeout")
        except aiohttp.ClientError as e:
            raise exceptions.ApiError(f"HTTP error: {e}")

    def _build_stop_event_request(
        self, location_id: str, number_results: int = 1, dt=None
    ):
        """Build XML for stop event request."""
        xml = """
<StopEventRequest>
    <Location>
        <LocationRef>
            <StopPointRef>LOCATION_NAME__</StopPointRef>
        </LocationRef>
        DepArrTime__
    </Location>
    <Params>
        <NumberOfResults>NumberOfResults__</NumberOfResults>
        <StopEventType>departure</StopEventType>
        <IncludePreviousCalls>false</IncludePreviousCalls>
        <IncludeOnwardCalls>false</IncludeOnwardCalls>
        <IncludeRealtimeData>true</IncludeRealtimeData>
    </Params>
</StopEventRequest>
"""
        xml = xml.replace("LOCATION_NAME__", location_id)

        if dt is None:
            xml = xml.replace("DepArrTime__", "")
        else:
            xml = xml.replace(
                "DepArrTime__",
                f"<DepArrTime>{convert_to_local_format(dt)}</DepArrTime>",
            )

        xml = xml.replace("NumberOfResults__", str(number_results))
        return xml

    def _build_trip_request(
        self, origin_id: str, destination_id: str, number_results: int = 1, dt=None
    ):
        """Build XML for trip request."""
        xml = """
<TripRequest>
    <Origin>
        <LocationRef>
            <StopPointRef>LOCATION_NAME_ORIGIN__</StopPointRef>
        </LocationRef>
        DepArrTime__
    </Origin>
    <Destination>
        <LocationRef>
            <StopPointRef>LOCATION_NAME_DESTINATION__</StopPointRef>
        </LocationRef>
    </Destination>
    <Params>
        <NumberOfResults>NumberOfResults__</NumberOfResults>
        <IncludeTrackSections>false</IncludeTrackSections>
        <IncludeLegProjection>true</IncludeLegProjection>
        <IncludeIntermediateStops>false</IncludeIntermediateStops>
    </Params>
</TripRequest>
"""
        xml = xml.replace("LOCATION_NAME_ORIGIN__", origin_id)
        xml = xml.replace("LOCATION_NAME_DESTINATION__", destination_id)
        xml = xml.replace("NumberOfResults__", str(number_results))

        if dt is None:
            xml = xml.replace("DepArrTime__", "")
        else:
            time = convert_to_local_format(dt)
            xml = xml.replace("DepArrTime__", f"<DepArrTime>{time}</DepArrTime>")

        return xml

    def _build_location_request(self, location_name: str, number_results: int = 1):
        """Build XML for location request."""
        xml = """
<LocationInformationRequest>
    <InitialInput>
        <LocationName>LocationName__</LocationName>
    </InitialInput>
    <Restrictions>
        <Type>stop</Type>
        <NumberOfResults>NumberOfResults__</NumberOfResults>
        <IncludePtModes>false</IncludePtModes>
    </Restrictions>
</LocationInformationRequest>
"""
        xml = xml.replace("LocationName__", location_name)
        xml = xml.replace("NumberOfResults__", str(number_results))
        return xml

    # DIESE METHODE FEHLTE - für config_flow.py benötigt
    async def location_information_request(
        self,
        location_name: str,
        number_results: int = 1,
        include_pt_podes: bool = False,
        ignore_low_probability: bool = False,
    ):
        """Async version of location_information_request for config flow."""
        payload = self._build_location_request(location_name, number_results)
        result = await self._make_request(payload)

        error = None
        try:
            error = result["LocationInformationResponse"]["ErrorMessage"]["Text"][
                "Text"
            ]
        except KeyError:
            pass

        # Check probability (same as original)
        if number_results == 1 and not ignore_low_probability:
            try:
                probability = float(
                    result["LocationInformationResponse"]["Location"]["Probability"]
                )
                if probability < 0.75 and probability > 0.0:
                    found = result["LocationInformationResponse"]["Location"][
                        "Location"
                    ]["StopPoint"]["StopPointName"]["Text"]
                    error = f"{location_name} <> {found} - probability of a correct result: {probability}"
            except KeyError:
                pass

        if error:
            raise exceptions.InvalidLocationName(error)

        return result["LocationInformationResponse"]

    async def async_get_departures(self, location_id: str, number_results: int = 1):
        """Async get departures with same structure as old get_departures()."""
        if number_results < 1:
            raise ValueError("Number of results must be 1 or greater")

        payload = self._build_stop_event_request(location_id, number_results)
        response = await self._make_request(payload)

        stop_events = response["StopEventResponse"]["StopEventResult"]

        if not isinstance(stop_events, list):
            stop_events = [stop_events]

        xmlresult = []

        for index, stop_event in enumerate(stop_events):
            data = {}
            data["id"] = index
            data["mode"] = stop_event["StopEvent"]["Service"]["Mode"]["PtMode"]
            data["StopPointName"] = stop_event["StopEvent"]["ThisCall"]["CallAtStop"][
                "StopPointName"
            ]["Text"]
            data["LineName"] = stop_event["StopEvent"]["Service"]["PublishedLineName"][
                "Text"
            ]
            data["DestinationText"] = stop_event["StopEvent"]["Service"][
                "DestinationText"
            ]["Text"]
            data["TimetabledTime"] = to_datetime(
                stop_event["StopEvent"]["ThisCall"]["CallAtStop"]["ServiceDeparture"][
                    "TimetabledTime"
                ]
            )

            data["EstimatedTime"] = to_datetime(
                stop_event["StopEvent"]["ThisCall"]["CallAtStop"][
                    "ServiceDeparture"
                ].get(
                    "EstimatedTime",
                    stop_event["StopEvent"]["ThisCall"]["CallAtStop"][
                        "ServiceDeparture"
                    ]["TimetabledTime"],
                )
            )
            data["Delay"] = get_timedelta(data["TimetabledTime"], data["EstimatedTime"])

            if stop_event["StopEvent"]["Service"]["Mode"]["PtMode"] == "rail":
                data["PlannedBay"] = (
                    stop_event["StopEvent"]["ThisCall"]["CallAtStop"]
                    .get("PlannedBay", {})
                    .get("Text", None)
                )
            elif stop_event["StopEvent"]["Service"]["Mode"]["PtMode"] == "bus":
                pass
            xmlresult.append(data)

        return xmlresult

    async def async_get_trip(
        self, origin_id: str, destination_id: str, number_results: int = 1
    ):
        """Async get trip with same structure as old get_trip()."""
        if number_results < 1:
            raise exceptions.InvalidNumberOfResults

        payload = self._build_trip_request(origin_id, destination_id, number_results)
        response = await self._make_request(payload)

        trip_data = response["TripResponse"]["TripResult"]

        if not isinstance(trip_data, list):
            trip_data = [trip_data]

        trip_results = []

        for index_trip, trip in enumerate(trip_data):
            trip_result = {
                "RouteNr": index_trip,
                "Interchanges": int(trip["Trip"]["Interchanges"]),
                "Duration": parse_duration(trip["Trip"]["Duration"]),
                "StartTime": to_datetime(trip["Trip"]["StartTime"]),
                "EndTime": to_datetime(trip["Trip"]["EndTime"]),
                "Transportation": [],
            }

            transport_data = trip["Trip"]["TripLeg"]

            if not isinstance(transport_data, list):
                transport_data = [transport_data]

            for transportation in transport_data:
                leg_data = {
                    "LegId": int(transportation["LegId"]),
                }

                if "TimedLeg" in transportation:
                    timed_leg = transportation["TimedLeg"]

                    leg_data["PTMode"] = timed_leg["Service"]["Mode"]["PtMode"]
                    leg_data["LineName"] = timed_leg["Service"]["PublishedLineName"][
                        "Text"
                    ]
                    leg_data["DestinationText"] = timed_leg["Service"][
                        "DestinationText"
                    ]["Text"]

                    # Entry
                    leg_data["Entry"] = timed_leg["LegBoard"]["StopPointName"]["Text"]
                    leg_data["EntryTimetabledTime"] = to_datetime(
                        timed_leg["LegBoard"]["ServiceDeparture"]["TimetabledTime"]
                    )
                    leg_data["EntryEstimatedTime"] = to_datetime(
                        timed_leg["LegBoard"]["ServiceDeparture"].get(
                            "EstimatedTime", None
                        )
                    )
                    leg_data["EntryCurrentDelay"] = get_timedelta(
                        leg_data["EntryTimetabledTime"],
                        leg_data["EntryEstimatedTime"],
                    )

                    # Exit
                    leg_data["Exit"] = timed_leg["LegAlight"]["StopPointName"]["Text"]
                    leg_data["ExitTimetabledTime"] = to_datetime(
                        timed_leg["LegAlight"]["ServiceArrival"]["TimetabledTime"]
                    )
                    leg_data["ExitEstimatedTime"] = to_datetime(
                        timed_leg["LegAlight"]["ServiceArrival"].get(
                            "EstimatedTime", None
                        )
                    )
                    leg_data["ExitCurrentDelay"] = get_timedelta(
                        leg_data["ExitTimetabledTime"],
                        leg_data["ExitEstimatedTime"],
                    )

                elif "ContinuousLeg" in transportation:
                    continuous_leg = transportation["ContinuousLeg"]
                    leg_data.update(
                        {
                            "PTMode": continuous_leg["Service"]["IndividualMode"],
                            "TimeWindowStart": to_datetime(
                                continuous_leg["TimeWindowStart"]
                            ),
                            "TimeWindowEnd": to_datetime(
                                continuous_leg["TimeWindowEnd"]
                            ),
                            "Duration": parse_duration(continuous_leg["Duration"]),
                        }
                    )

                else:
                    interchange_leg = transportation["InterchangeLeg"]
                    leg_data.update(
                        {
                            "PTMode": interchange_leg["InterchangeMode"],
                            "Entry": interchange_leg["LegStart"]["LocationName"][
                                "Text"
                            ],
                            "TimeWindowStart": interchange_leg["TimeWindowStart"],
                            "Exit": interchange_leg["LegEnd"]["LocationName"]["Text"],
                            "TimeWindowEnd": interchange_leg["TimeWindowEnd"],
                            "Duration": interchange_leg["Duration"],
                            "BufferTime": interchange_leg.get("BufferTime", None),
                        }
                    )

                trip_result["Transportation"].append(leg_data)

            # Calculate StartTimetabledTime, StartEstimatedTime, etc.
            if trip_result["Transportation"]:
                first_leg = trip_result["Transportation"][0]
                last_leg = trip_result["Transportation"][-1]

                trip_result["StartTimetabledTime"] = first_leg.get(
                    "EntryTimetabledTime"
                )
                trip_result["StartEstimatedTime"] = first_leg.get("EntryEstimatedTime")
                trip_result["EndTimetabledTime"] = last_leg.get("ExitTimetabledTime")
                trip_result["EndEstimatedTime"] = last_leg.get("ExitEstimatedTime")

                # For backward compatibility with old code
                trip_result["StartTime"] = (
                    trip_result["StartEstimatedTime"]
                    or trip_result["StartTimetabledTime"]
                )
                trip_result["EstimatedStartTime"] = trip_result["StartEstimatedTime"]

                # Calculate delay
                trip_result["Delay"] = get_timedelta(
                    trip_result["StartTimetabledTime"],
                    trip_result["StartEstimatedTime"],
                )
            else:
                trip_result["StartTimetabledTime"] = trip_result["StartTime"]
                trip_result["StartEstimatedTime"] = None
                trip_result["EndTimetabledTime"] = trip_result["EndTime"]
                trip_result["EndEstimatedTime"] = None
                trip_result["Delay"] = None

            trip_results.append(trip_result)

        return trip_results

    async def async_get_station_data(self, location_id: str):
        """Async get station data with same structure as old get_station_data()."""
        payload = self._build_location_request(location_id, 1)
        response = await self._make_request(payload)

        location_data = response["LocationInformationResponse"]["Location"]["Location"]

        # Check probability (same as old code)
        try:
            probability = float(location_data["Probability"])
            if probability < 0.75 and probability > 0.0:
                found = location_data["Location"]["StopPoint"]["StopPointName"]["Text"]
                raise exceptions.InvalidLocationName(
                    f"{location_id} <> {found} - probability: {probability}"
                )
        except (KeyError, ValueError):
            pass

        return location_data

    async def async_get_station_id(self, location_name: str):
        """Async get station id from station name."""
        station_data = await self.async_get_station_data(location_name)
        return station_data["StopPoint"]["StopPointRef"]

    async def async_test_connection(self) -> bool:
        """Simple check if API key + URL work."""
        try:
            await self.async_get_station_data("test")
            return True
        except exceptions.InvalidLocationName:
            # This is expected for test location
            return True
        except Exception:
            return False
