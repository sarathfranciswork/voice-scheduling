"""Custom exceptions for the CVS API client."""


class CVSAPIError(Exception):
    """Base exception for CVS API errors."""

    def __init__(self, message: str, status_code: int | None = None, response_body: dict | None = None):
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(message)


class TokenError(CVSAPIError):
    """Failed to acquire or refresh the guest token."""


class ExperienceAPIError(CVSAPIError):
    """An experience API call returned a non-success status."""


class RateLimitError(CVSAPIError):
    """Rate limited by CVS servers (HTTP 429)."""


class SessionExpiredError(CVSAPIError):
    """The session or token has expired and could not be refreshed."""


class NoAvailabilityError(CVSAPIError):
    """No stores, dates, or time slots available for the given criteria."""


class AuthenticationError(CVSAPIError):
    """CVS login or MFA verification failed."""
