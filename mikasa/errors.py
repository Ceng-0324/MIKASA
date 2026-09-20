class MikasaError(Exception):
    """An actionable error safe to show to a caller."""


class Conflict(MikasaError):
    pass


class Forbidden(MikasaError):
    pass


class NotFound(MikasaError):
    pass
