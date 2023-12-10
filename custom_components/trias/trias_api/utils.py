import datetime
import pytz


def convert_to_zulu_format(dt=None):
    """
    Convert a datetime object to a Zulu-formatted string (UTC).
    """
    if dt is None:
        dt = datetime.datetime.now(pytz.utc)

    # Ensure the datetime object has a timezone
    if dt.tzinfo is None:
        raise ValueError("Datetime object must have a timezone")

    # Convert to UTC
    dt_utc = dt.astimezone(pytz.utc).replace(tzinfo=None)

    # Format as a string
    formatted_string = dt_utc.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    return formatted_string


def convert_to_local_format(dt):
    """
    Convert a datetime object to a string in local time format '2023-12-01T07:00:00'.
    """
    # Ensure the datetime object has a timezone
    if dt.tzinfo is not None:
        dt = dt.astimezone(
            pytz.timezone("Europe/Berlin")
        )  # Replace 'Europe/Berlin' with your desired timezone

    # Format as a string
    formatted_string = dt.strftime("%Y-%m-%dT%H:%M:%S")

    return formatted_string


def to_datetime(zulu_time):
    """format Zulu time to datetime"""
    if not zulu_time:
        return None

    return datetime.datetime.fromisoformat(zulu_time)


def parse_duration(duration):
    """
    Parse a duration string in the format "PT[hours]H[minutes]M" into a timedelta object.

    :param duration: a string in the format "PT[hours]H[minutes]M"
    :return: the timedelta as a string
    """
    minutes = 0
    hours = 0

    try:
        hours = int(duration[2 : duration.index("H")])
    except ValueError:
        pass

    try:
        if "H" in duration:
            minutes = int(duration[duration.index("H") + 1 : duration.index("M")])
        else:
            minutes = int(duration[2 : duration.index("M")])
    except ValueError:
        pass

    parsed_duration = datetime.timedelta(hours=hours, minutes=minutes)
    return str(parsed_duration)


def get_timedelta(start_dt, end_dt, to_str=True):
    if not start_dt or not end_dt:
        return None

    # Calculate the timedelta
    delta = end_dt - start_dt

    # Calculate hours, minutes, and seconds
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    # Format the timedelta as "hh:mm:ss"
    timedelta_str = "{:02}:{:02}:{:02}".format(hours, minutes, seconds)

    if to_str:
        delta = str(delta)

    return delta
