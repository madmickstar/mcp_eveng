"""Exception hierarchy for the EVENG API client."""

from __future__ import annotations


class EvengError(Exception):
    """Base class for all errors raised by the EVENG client."""


class EvengAuthError(EvengError):
    """Raised when login fails or a session is not/no-longer authenticated."""


class EvengNotFoundError(EvengError):
    """Raised when EVENG returns a 404 for a lab/node/folder/user/etc."""


class EvengAPIError(EvengError):
    """Raised for any other non-success ("fail"/"error") JSend response."""

    def __init__(self, message: str, *, code: int | None = None, status: str | None = None):
        super().__init__(message)
        self.code = code
        self.status = status
