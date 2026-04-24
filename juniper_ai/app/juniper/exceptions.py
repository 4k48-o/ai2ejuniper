class JuniperError(Exception):
    """Base exception for Juniper API errors."""


class SOAPTimeoutError(JuniperError):
    """SOAP request timed out."""


class JuniperFaultError(JuniperError):
    """Juniper returned a SOAP fault."""

    def __init__(self, fault_code: str, fault_string: str):
        self.fault_code = fault_code
        self.fault_string = fault_string
        super().__init__(f"Juniper SOAP Fault [{fault_code}]: {fault_string}")


class RoomUnavailableError(JuniperError):
    """The requested room is no longer available."""


class PriceChangedError(JuniperError):
    """The price has changed since the last availability check.

    When raised by ``HotelCheckAvail`` the new ``RatePlanCode`` (if Juniper
    supplied one) is attached as :attr:`new_rate_plan_code` — per the
    official docs, callers should retry the booking flow with the new code
    rather than the one from the original ``HotelAvail`` response.
    """

    def __init__(
        self,
        old_price: str,
        new_price: str,
        currency: str,
        *,
        new_rate_plan_code: str = "",
    ):
        self.old_price = old_price
        self.new_price = new_price
        self.currency = currency
        self.new_rate_plan_code = new_rate_plan_code
        super().__init__(f"Price changed from {old_price} to {new_price} {currency}")


class BookingPendingError(JuniperError):
    """Booking was submitted but confirmation timed out."""

    def __init__(self, idempotency_key: str):
        self.idempotency_key = idempotency_key
        super().__init__(f"Booking pending confirmation (key={idempotency_key})")


class NoResultsError(JuniperError):
    """No hotels found matching the search criteria."""


class BookingOwnershipError(JuniperError):
    """The booking does not belong to the requesting user."""
