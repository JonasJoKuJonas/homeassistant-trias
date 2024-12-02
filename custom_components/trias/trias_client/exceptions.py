class InvalidApiKey(Exception):
    pass


class InvalidUrl(Exception):
    pass


class InvalidNumberOfResults(Exception):
    pass


class ApiError(Exception):
    pass


class InvalidLocationName(Exception):
    pass

class HttpError(Exception):
    def __init__(self, status_code, response, *args: object) -> None:
        super().__init__(*args)
        self.status_code = status_code
        self.response = response
