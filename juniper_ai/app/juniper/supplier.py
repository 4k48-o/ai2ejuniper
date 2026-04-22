"""Abstract interface for hotel supplier clients."""

from abc import ABC, abstractmethod


class HotelSupplier(ABC):
    """Abstract base class defining the hotel supplier interface."""

    # ---- Static data ----

    @abstractmethod
    async def zone_list(self, product_type: str = "HOT") -> list[dict]:
        """Retrieve destination zone codes for a product type."""

    @abstractmethod
    async def hotel_portfolio(self, page_token: str | None = None, page_size: int = 500) -> dict:
        """Retrieve hotel codes (JPCode) with pagination."""

    @abstractmethod
    async def hotel_content(self, hotel_codes: list[str]) -> list[dict]:
        """Retrieve detailed information for up to 25 hotels by JPCode."""

    @abstractmethod
    async def generic_data_catalogue(self, catalogue_type: str) -> list[dict]:
        """Retrieve generic data catalogue (CURRENCY, COUNTRIES, LANGUAGES)."""

    @abstractmethod
    async def hotel_catalogue_data(self) -> dict:
        """Retrieve hotel-specific catalogue (categories, boards, room types)."""

    # ---- Booking flow ----

    @abstractmethod
    async def hotel_avail(
        self,
        zone_code: str | None = None,
        check_in: str = "",
        check_out: str = "",
        adults: int = 2,
        children: int = 0,
        star_rating: int | None = None,
        max_price: float | None = None,
        board_type: str | None = None,
        country_of_residence: str | None = None,
        *,
        hotel_codes: list[str] | None = None,
        **kwargs,
    ) -> list[dict]:
        """Search for available hotels.

        Caller MUST provide at least one of ``hotel_codes`` (preferred) or
        ``zone_code`` (legacy / mock-only fallback).

        Preferred path — ``hotel_codes`` (JPCode list, e.g. ``["JP046300", ...]``):
            This is the only path accepted by Juniper UAT for the
            ``TestXMLFlicknmix`` account. Searching availability by
            ``DestinationZone`` returns ``REQ_PRACTICE`` per Juniper support
            (ticket 1096690). Production SOAP implementations MUST use this
            path and SHOULD raise ``ValueError`` when ``hotel_codes`` is
            missing.

        Legacy path — ``zone_code`` (numeric ``DestinationZone`` or
        ``JPDxxxxxx``):
            Kept only for the in-memory mock client and local tests. Real
            SOAP clients should treat this as unsupported.

        Args:
            zone_code: Destination zone code; mock / legacy only.
            check_in:  ISO date ``YYYY-MM-DD``.
            check_out: ISO date ``YYYY-MM-DD``.
            adults / children: Pax distribution.
            star_rating / max_price / board_type: Optional post-filters.
            country_of_residence: ISO-3166-1 alpha-2; must stay consistent
                across the whole booking flow.
            hotel_codes: Explicit JPCode list used by the production SOAP
                path (keyword-only).

        Raises:
            ValueError: If both ``hotel_codes`` and ``zone_code`` are empty
                (concrete implementations decide the exact enforcement).
        """

    @abstractmethod
    async def hotel_check_avail(self, rate_plan_code: str) -> dict:
        """Check if a specific rate plan is still available."""

    @abstractmethod
    async def hotel_booking_rules(self, rate_plan_code: str) -> dict:
        """Validate booking rules, get cancellation policy and BookingCode."""

    @abstractmethod
    async def hotel_booking(
        self, rate_plan_code: str, guest_name: str, guest_email: str, **kwargs,
    ) -> dict:
        """Create a hotel booking."""

    @abstractmethod
    async def read_booking(self, booking_id: str, user_id: str | None = None) -> dict:
        """Read an existing booking."""

    @abstractmethod
    async def list_bookings(self, user_id: str | None = None) -> list[dict]:
        """List bookings, optionally filtered by user."""

    @abstractmethod
    async def cancel_booking(
        self, booking_id: str, user_id: str | None = None, only_fees: bool = False,
    ) -> dict:
        """Cancel a booking, or query cancellation fees only (only_fees=True)."""

    @abstractmethod
    async def hotel_modify(self, booking_id: str, user_id: str | None = None, **modifications) -> dict:
        """Step 1 of modification: request available modification options.

        Returns dict with modify_code, new pricing, and available options.
        """

    @abstractmethod
    async def hotel_confirm_modify(self, modify_code: str) -> dict:
        """Step 2 of modification: confirm a previously requested modification."""
