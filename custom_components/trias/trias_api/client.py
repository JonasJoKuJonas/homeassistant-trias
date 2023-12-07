"""Client class from Trias module"""
# -*- coding: utf-8 -*-
# API Dokumentation: https://opentransportdata.swiss/de/cookbook/abfahrts-ankunftsanzeiger/

import datetime
import json
import logging

import requests
import xmltodict

from . import exceptions
from .utils import (
    convert_to_zulu_format,
    to_datetime,
    parse_duration,
    get_timedelta_string,
    convert_to_local_format,
)

_LOGGER = logging.getLogger(__name__)


class Client:
    """Client class for Trias API"""

    def __init__(
        self,
        api_key: str = None,
        url: str = None,
    ):
        if api_key is None:
            raise exceptions.InvalidApiKey
        if url is None:
            raise exceptions.InvalidUrl
        self.api_key = api_key
        self.url = url

    def get(self, payload):
        """Call API with trias header"""
        header = """
        <?xml version="1.0" encoding="UTF-8"?>
        <Trias version="1.1" xmlns="http://www.vdv.de/trias" xmlns:siri="http://www.siri.org.uk/siri" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
            <ServiceRequest>
                <siri:RequestTimestamp>NOW__</siri:RequestTimestamp>
                <siri:RequestorRef>API-Explorer</siri:RequestorRef>
                <RequestPayload>
                    PAYLOAD__
                </RequestPayload>
            </ServiceRequest>
        </Trias>
        """

        header = header.replace("API-Explorer", self.api_key)
        xml = header.replace("PAYLOAD__", payload)
        xml = xml.replace("NOW__", convert_to_zulu_format())

        req = requests.post(
            self.url,
            data=xml,
            headers={"Content-Type": "application/xml"},
        )

        req.encoding = "utf-8"

        response = req.text

        trias_payload = xmltodict.parse(response)["Trias"]["ServiceDelivery"][
            "DeliveryPayload"
        ]

        error = None
        response_keys = [
            "StopEventResponse",
            "TripResponse",
            "TripInfoResponse",
            "LocationInformationResponse",
        ]

        for key in response_keys:
            trias_data = trias_payload.get(key, {})
            error_message = (
                trias_data.get("ErrorMessage", {}).get("Text", {}).get("Text")
            )

            if error_message:
                raise exceptions.ApiError(error_message)

        return trias_payload

    def stop_event_request(
        self,
        location_id,
        dt=None,
        number_of_results=1,
        stop_event_type="departure",
        include_previous_calls=False,
        include_onward_calls=False,
        include_realtime_data=True,
    ):
        """Make API call to get stop_event_request"""
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
                <StopEventType>StopEventType__</StopEventType>
                <IncludePreviousCalls>IncludePreviousCalls__</IncludePreviousCalls>
                <IncludeOnwardCalls>IncludeOnwardCalls__</IncludeOnwardCalls>
                <IncludeRealtimeData>IncludeRealtimeData__</IncludeRealtimeData>
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

        xml = xml.replace("NumberOfResults__", str(number_of_results))
        xml = xml.replace("StopEventType__", str(stop_event_type).lower())
        xml = xml.replace("IncludePreviousCalls__", str(include_previous_calls).lower())
        xml = xml.replace("IncludeOnwardCalls__", str(include_onward_calls).lower())
        xml = xml.replace("IncludeRealtimeData__", str(include_realtime_data).lower())

        return self.get(xml)

    def trip_request(
        self,
        location_id_origin,
        location_id_destination,
        number_of_results=1,
        dt=None,
    ):
        """Make API call to get trip_request"""
        if number_of_results < 1:
            raise exceptions.InvalidNumberOfResults
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

        xml = xml.replace("LOCATION_NAME_ORIGIN__", location_id_origin)
        xml = xml.replace("NumberOfResults__", str(number_of_results))
        xml = xml.replace("LOCATION_NAME_DESTINATION__", location_id_destination)
        if dt is None:
            xml = xml.replace("DepArrTime__", "")
        else:
            time = convert_to_local_format(dt)
            xml = xml.replace("DepArrTime__", f"<DepArrTime>{time}</DepArrTime>")

        trias_payload = self.get(xml)
        return trias_payload["TripResponse"]

    def trip_info_request(
        self,
        journey_ref,
        operating_day_ref,
        use_timetabled_data_only=True,
        include_calls=True,
        include_position=False,
        include_service=True,
    ):
        """Make API call to get trip_info_request"""
        xml = """
        <TripInfoRequest>
            <JourneyRef>JourneyRef__</JourneyRef>
            <OperatingDayRef>OperatingDayRef__</OperatingDayRef>
            <Params>
                <UseTimetabledDataOnly>UseTimetabledDataOnly__</UseTimetabledDataOnly>
                <IncludeCalls>IncludeCalls__</IncludeCalls>
                <IncludePosition>IncludePosition__</IncludePosition>
                <IncludeService>IncludeService__</IncludeService>
            </Params>
        </TripInfoRequest>
        """

        xml = xml.replace("JourneyRef__", journey_ref)
        xml = xml.replace("OperatingDayRef__", operating_day_ref)
        xml = xml.replace(
            "UseTimetabledDataOnly__", str(use_timetabled_data_only).lower()
        )
        xml = xml.replace("IncludeCalls__", str(include_calls).lower())
        xml = xml.replace("IncludePosition__", str(include_position).lower())
        xml = xml.replace("IncludeService__", str(include_service).lower())

        return self.get(xml)

    def location_information_request(
        self, location_name, number_of_results=1, include_pt_podes=False
    ):
        """Make API call to get location_information_request"""
        xml = """
        <LocationInformationRequest>
            <InitialInput>
                <LocationName>LocationName__</LocationName>
            </InitialInput>
            <Restrictions>
                <Type>stop</Type>
                <NumberOfResults>NumberOfResults__</NumberOfResults>
                <IncludePtModes>IncludePtModes__</IncludePtModes>
            </Restrictions>
        </LocationInformationRequest>
        """

        xml = xml.replace("LocationName__", location_name)
        xml = xml.replace("NumberOfResults__", str(number_of_results))
        xml = xml.replace("IncludePtModes__", str(include_pt_podes).lower())

        result = self.get(xml)

        error = None
        try:
            error = result["LocationInformationResponse"]["ErrorMessage"]["Text"][
                "Text"
            ]
        except KeyError:
            pass

        if number_of_results == 1:
            try:
                probability = float(
                    result["LocationInformationResponse"]["Location"]["Probability"]
                )
                if probability < 0.75:
                    found = result["LocationInformationResponse"]["Location"][
                        "Location"
                    ]["StopPoint"]["StopPointName"]["Text"]
                    error = f"{location_name} <> {found} - probability of a correct result: {probability}"
            except KeyError:
                pass

        if error:
            raise exceptions.InvalidLocationName(error)

        return result["LocationInformationResponse"]

    def get_departures(self, location_name, number_results=1, dt=None):
        """
        Get formatted departures from a station.

        Args:
            location_name (str): The name or ID of the location (station).
            number_results (int, optional): The number of departure results to retrieve (default is 1).
            dt (datetime, optional): The time for which departures are to be retrieved.

        Returns:
            list: A list of dictionaries containing departure information.
        """
        if number_results < 1:
            raise ValueError("Number of results must be 1 or greater")
        xml = self.stop_event_request(
            location_id=location_name, number_of_results=number_results, dt=dt
        )

        xml = xml["StopEventResponse"]["StopEventResult"]

        if not isinstance(xml, list):
            xml = [xml]

        xmlresult = []

        for index, stop_event in enumerate(xml):
            data = {}
            data["id"] = index
            data["mode"] = stop_event["StopEvent"]["Service"]["Mode"]["PtMode"]
            data["StopPointName"] = stop_event["StopEvent"]["ThisCall"]["CallAtStop"][
                "StopPointName"
            ]["Text"]
            data["PublishedLineName"] = stop_event["StopEvent"]["Service"][
                "PublishedLineName"
            ]["Text"]
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
                ].get("EstimatedTime", None)
            )
            data["CurrentDelay"] = get_timedelta_string(
                data["EstimatedTime"], data["TimetabledTime"]
            )

            if stop_event["StopEvent"]["Service"]["Mode"]["PtMode"] == "rail":
                data["PlannedBay"] = stop_event["StopEvent"]["ThisCall"]["CallAtStop"][
                    "PlannedBay"
                ]["Text"]
            elif stop_event["StopEvent"]["Service"]["Mode"]["PtMode"] == "bus":
                pass
            xmlresult.append(data)

        return xmlresult

    def get_station_data(self, location_name):
        """Get station date from station name"""
        xml = self.location_information_request(location_name)
        return xml["Location"]["Location"]

    def get_station_id(self, location_name):
        """Get station id from station name"""
        xml = self.get_station_data(location_name)
        return xml["StopPoint"]["StopPointRef"]

    def get_trip(
        self,
        location_id_origin,
        location_id_destination,
        number_of_results=1,
        dt=None,
    ):
        """Get trip from a to b"""
        trip_data = self.trip_request(
            location_id_origin=location_id_origin,
            location_id_destination=location_id_destination,
            dt=dt,
            number_of_results=number_of_results,
        )["TripResult"]

        _LOGGER.debug("Trip Request: %s", trip_data)

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

            if trip_result["Interchanges"] == 0:
                transport_data = [transport_data]

            for transportation in transport_data:
                leg_data = {
                    "LegId": int(transportation["LegId"]),
                }

                if "TimedLeg" in transportation:
                    timed_leg = transportation["TimedLeg"]

                    leg_data["PTMode"] = timed_leg["Service"]["Mode"]["PtMode"]

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
                    leg_data["EntryCurrentDelay"] = get_timedelta_string(
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
                    leg_data["ExitCurrentDelay"] = get_timedelta_string(
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

            trip_result["StartTimetabledTime"] = trip_result["Transportation"][0][
                "EntryTimetabledTime"
            ]
            trip_result["StartEstimatedTime"] = trip_result["Transportation"][0][
                "EntryEstimatedTime"
            ]

            trip_results.append(trip_result)

        return trip_results
