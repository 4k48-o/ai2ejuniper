"""Mock Juniper client for development without real API credentials."""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from juniper_ai.app.juniper.exceptions import BookingOwnershipError, NoResultsError, RoomUnavailableError
from juniper_ai.app.juniper.supplier import HotelSupplier

logger = logging.getLogger(__name__)

MOCK_HOTELS = [
    {
        "hotel_code": "HOT001",
        "name": "NH Collection Barcelona Gran Hotel Calderón",
        "category": "4 stars",
        "address": "Rambla de Catalunya 26",
        "city": "Barcelona",
        "rate_plan_code": "RPC_001_DBL_BB",
        "total_price": "180.00",
        "currency": "EUR",
        "board_type": "Bed & Breakfast",
        "room_type": "Double Standard",
        "cancellation_policy": "Free cancellation until 48h before check-in",
    },
    {
        "hotel_code": "HOT002",
        "name": "Eurostars Grand Marina Hotel",
        "category": "5 stars",
        "address": "Moll de Barcelona s/n",
        "city": "Barcelona",
        "rate_plan_code": "RPC_002_SUP_RO",
        "total_price": "220.00",
        "currency": "EUR",
        "board_type": "Room Only",
        "room_type": "Superior Double",
        "cancellation_policy": "Non-refundable",
    },
    {
        "hotel_code": "HOT003",
        "name": "Hotel Arts Barcelona",
        "category": "5 stars",
        "address": "Marina 19-21",
        "city": "Barcelona",
        "rate_plan_code": "RPC_003_DLX_HB",
        "total_price": "350.00",
        "currency": "EUR",
        "board_type": "Half Board",
        "room_type": "Deluxe Sea View",
        "cancellation_policy": "Free cancellation until 72h before check-in",
    },
    {
        "hotel_code": "HOT004",
        "name": "Hotel Continental Barcelona",
        "category": "3 stars",
        "address": "La Rambla 138",
        "city": "Barcelona",
        "rate_plan_code": "RPC_004_STD_BB",
        "total_price": "95.00",
        "currency": "EUR",
        "board_type": "Bed & Breakfast",
        "room_type": "Standard Single",
        "cancellation_policy": "Free cancellation until 24h before check-in",
    },
    {
        "hotel_code": "HOT005",
        "name": "Mandarin Oriental Barcelona",
        "category": "5 stars",
        "address": "Passeig de Gràcia 38-40",
        "city": "Barcelona",
        "rate_plan_code": "RPC_005_PRE_FB",
        "total_price": "520.00",
        "currency": "EUR",
        "board_type": "Full Board",
        "room_type": "Premium Room",
        "cancellation_policy": "Free cancellation until 7 days before check-in",
    },
]

# In-memory fallback for tests that don't have a DB session available.
# In production mock mode, bookings are persisted to DB by the conversation handler.
MOCK_BOOKINGS: dict[str, dict] = {}


MOCK_ZONES = [
    {"jpdcode": "JPD086855", "code": "49435", "name": "Barcelona", "area_type": "CTY", "searchable": True, "parent_jpdcode": "JPD034804"},
    {"jpdcode": "JPD054557", "code": "15011", "name": "Palma de Mallorca", "area_type": "CTY", "searchable": True, "parent_jpdcode": "JPD036705"},
    {"jpdcode": "JPD034804", "code": "118", "name": "Spain", "area_type": "PAS", "searchable": True, "parent_jpdcode": ""},
    {"jpdcode": "JPD036705", "code": "1953", "name": "Majorca", "area_type": "REG", "searchable": True, "parent_jpdcode": "JPD034804"},
]

MOCK_CURRENCIES = [
    {"code": "EUR", "name": "Euro"},
    {"code": "USD", "name": "American Dollar"},
    {"code": "GBP", "name": "Pound Sterling"},
]

MOCK_COUNTRIES = [
    {"code": "ES", "name": "Spain"},
    {"code": "CN", "name": "China"},
    {"code": "US", "name": "United States"},
    {"code": "GB", "name": "United Kingdom"},
]

MOCK_BOARD_TYPES = [
    {"code": "SA", "name": "Room Only"},
    {"code": "AD", "name": "Bed & Breakfast"},
    {"code": "MP", "name": "Half Board"},
    {"code": "PC", "name": "Full Board"},
    {"code": "TI", "name": "All Inclusive"},
]

MOCK_HOTEL_CATEGORIES = [
    {"code": "3est", "name": "3 Stars"},
    {"code": "4est", "name": "4 Stars"},
    {"code": "5est", "name": "5 Stars"},
]


class MockJuniperClient(HotelSupplier):
    """Mock implementation of the Juniper SOAP client for development."""

    # ---- Static data ----

    async def zone_list(self, product_type: str = "HOT") -> list[dict]:
        logger.info("[MOCK] ZoneList: product_type=%s", product_type)
        return MOCK_ZONES

    async def hotel_portfolio(self, page_token: str | None = None, page_size: int = 500) -> dict:
        logger.info("[MOCK] HotelPortfolio: token=%s", page_token)
        hotels = [
            {
                "jp_code": h["hotel_code"],
                "name": h["name"],
                "zone_jpdcode": "JPD086855",
                "category_type": h["category"].replace(" stars", "est"),
                "address": h["address"],
                "latitude": "41.3874",
                "longitude": "2.1686",
                "city_name": h["city"],
                "city_jpdcode": "JPD086855",
            }
            for h in MOCK_HOTELS
        ]
        return {"hotels": hotels, "next_token": "", "total_records": len(hotels)}

    async def hotel_content(self, hotel_codes: list[str]) -> list[dict]:
        logger.info("[MOCK] HotelContent: %s", hotel_codes)
        results = []
        for code in hotel_codes[:25]:
            hotel = next((h for h in MOCK_HOTELS if h["hotel_code"] == code), None)
            if hotel:
                results.append({
                    "jp_code": hotel["hotel_code"],
                    "name": hotel["name"],
                    "images": [],
                    "descriptions": {"SHT": f"A lovely {hotel['category']} hotel in {hotel['city']}"},
                    "features": ["WIFI", "Pool"],
                    "check_in_time": "14:00",
                    "check_out_time": "12:00",
                })
        return results

    async def generic_data_catalogue(self, catalogue_type: str) -> list[dict]:
        logger.info("[MOCK] GenericDataCatalogue: %s", catalogue_type)
        if catalogue_type == "CURRENCY":
            return MOCK_CURRENCIES
        if catalogue_type == "COUNTRIES":
            return MOCK_COUNTRIES
        return []

    async def hotel_catalogue_data(self) -> dict:
        logger.info("[MOCK] HotelCatalogueData")
        return {
            "hotel_categories": MOCK_HOTEL_CATEGORIES,
            "board_types": MOCK_BOARD_TYPES,
        }

    # ---- Booking flow ----

    async def hotel_avail(
        self, zone_code: str, check_in: str, check_out: str,
        adults: int = 2, children: int = 0,
        star_rating: int | None = None,
        max_price: float | None = None,
        board_type: str | None = None,
        country_of_residence: str | None = None,
        **kwargs,
    ) -> list[dict]:
        logger.info("[MOCK] HotelAvail: zone=%s, %s to %s, star=%s, max_price=%s, board=%s",
                     zone_code, check_in, check_out, star_rating, max_price, board_type)
        # In mock mode, return all hotels (zone filtering is simulated)
        results = list(MOCK_HOTELS)

        if star_rating is not None:
            results = [h for h in results if str(star_rating) in h["category"]]
        if max_price is not None:
            results = [h for h in results if float(h["total_price"]) <= max_price]
        if board_type is not None:
            bt = board_type.lower()
            results = [h for h in results if bt in h["board_type"].lower()]

        return results

    async def hotel_check_avail(self, rate_plan_code: str) -> dict:
        logger.info("[MOCK] HotelCheckAvail: %s", rate_plan_code)
        hotel = next((h for h in MOCK_HOTELS if h["rate_plan_code"] == rate_plan_code), None)
        if hotel is None:
            raise RoomUnavailableError(f"Rate plan {rate_plan_code} not found")
        return {
            "available": True,
            "rate_plan_code": rate_plan_code,
            "total_price": hotel["total_price"],
            "currency": hotel["currency"],
            "price_changed": False,
        }

    async def hotel_booking_rules(self, rate_plan_code: str) -> dict:
        logger.info("[MOCK] HotelBookingRules: %s", rate_plan_code)
        hotel = next((h for h in MOCK_HOTELS if h["rate_plan_code"] == rate_plan_code), None)
        if hotel is None:
            raise RoomUnavailableError(f"Rate plan {rate_plan_code} not found")
        from datetime import datetime, timedelta, timezone
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        return {
            "valid": True,
            "rate_plan_code": rate_plan_code,
            "total_price": hotel["total_price"],
            "currency": hotel["currency"],
            "cancellation_policy": hotel["cancellation_policy"],
            "remarks": "",
            "booking_code": f"MOCK_BC_{rate_plan_code}",
            "booking_code_expires_at": expires_at.isoformat(),
        }

    async def hotel_booking(
        self, rate_plan_code: str, guest_name: str, guest_email: str, **kwargs,
    ) -> dict:
        logger.info("[MOCK] HotelBooking: %s for %s", rate_plan_code, guest_name)
        hotel = next((h for h in MOCK_HOTELS if h["rate_plan_code"] == rate_plan_code), None)
        if hotel is None:
            raise RoomUnavailableError(f"Rate plan {rate_plan_code} not found")
        booking_id = f"JNP-{uuid.uuid4().hex[:8].upper()}"
        booking = {
            "booking_id": booking_id,
            "status": "confirmed",
            "hotel_name": hotel["name"],
            "check_in": kwargs.get("check_in", "2026-04-15"),
            "check_out": kwargs.get("check_out", "2026-04-18"),
            "total_price": hotel["total_price"],
            "currency": hotel["currency"],
            "user_id": kwargs.get("user_id"),
            "country_of_residence": kwargs.get("country_of_residence", ""),
            "external_booking_reference": kwargs.get("external_booking_reference", ""),
        }
        MOCK_BOOKINGS[booking_id] = booking
        return booking

    async def read_booking(self, booking_id: str, user_id: str | None = None) -> dict:
        logger.info("[MOCK] ReadBooking: %s, user_id=%s", booking_id, user_id)
        if booking_id not in MOCK_BOOKINGS:
            return {
                "booking_id": booking_id,
                "status": "not_found",
                "hotel_name": "",
                "check_in": "",
                "check_out": "",
                "total_price": "0",
                "currency": "EUR",
                "guest_name": "",
            }
        booking = MOCK_BOOKINGS[booking_id]
        if user_id and booking.get("user_id") and booking["user_id"] != user_id:
            raise BookingOwnershipError(f"Booking {booking_id} does not belong to this user")
        return {**booking, "guest_name": "Mock Guest"}

    async def list_bookings(self, user_id: str | None = None) -> list[dict]:
        logger.info("[MOCK] ListBookings: %d bookings, user_id=%s", len(MOCK_BOOKINGS), user_id)
        if user_id:
            return [b for b in MOCK_BOOKINGS.values() if b.get("user_id") == user_id]
        return list(MOCK_BOOKINGS.values())

    async def cancel_booking(
        self, booking_id: str, user_id: str | None = None, only_fees: bool = False,
    ) -> dict:
        logger.info("[MOCK] CancelBooking: %s, user_id=%s, only_fees=%s", booking_id, user_id, only_fees)
        if booking_id in MOCK_BOOKINGS:
            booking = MOCK_BOOKINGS[booking_id]
            if user_id and booking.get("user_id") and booking["user_id"] != user_id:
                raise BookingOwnershipError(f"Booking {booking_id} does not belong to this user")
            if only_fees:
                return {
                    "booking_id": booking_id,
                    "status": "fee_query",
                    "cancel_cost": "0.00",
                    "cancel_cost_currency": booking.get("currency", "EUR"),
                    "warnings": ["warnCancellationCostRetrieved"],
                }
            booking["status"] = "cancelled"
        return {
            "booking_id": booking_id,
            "status": "cancelled",
            "warnings": ["warnCancelledAndCancellationCostRetrieved"],
        }

    async def hotel_modify(self, booking_id: str, user_id: str | None = None, **modifications) -> dict:
        logger.info("[MOCK] HotelModify: %s, user_id=%s", booking_id, user_id)
        if booking_id in MOCK_BOOKINGS:
            booking = MOCK_BOOKINGS[booking_id]
            if user_id and booking.get("user_id") and booking["user_id"] != user_id:
                raise BookingOwnershipError(f"Booking {booking_id} does not belong to this user")
            # Return modification preview with a modify_code
            preview = {**booking, "guest_name": "Mock Guest"}
            if modifications.get("check_in"):
                preview["check_in"] = modifications["check_in"]
            if modifications.get("check_out"):
                preview["check_out"] = modifications["check_out"]
            preview["modify_code"] = f"MC-{uuid.uuid4().hex[:8].upper()}"
            preview["status"] = "modification_pending"
            return preview
        return {"booking_id": booking_id, "status": "not_found", "modify_code": ""}

    async def hotel_confirm_modify(self, modify_code: str) -> dict:
        logger.info("[MOCK] HotelConfirmModify: %s", modify_code)
        # In mock mode, find any pending booking and confirm it
        return {"status": "modified", "modify_code": modify_code}


_client_instance = None


def get_juniper_client() -> HotelSupplier:
    """Factory: return cached mock or real client based on config.

    Returns a singleton instance to avoid re-initializing on every call.
    For the real client, this prevents re-downloading the WSDL on each request.
    """
    global _client_instance
    if _client_instance is not None:
        return _client_instance

    from juniper_ai.app.config import settings

    if settings.juniper_use_mock:
        _client_instance = MockJuniperClient()
    else:
        from juniper_ai.app.juniper.client import JuniperClient
        _client_instance = JuniperClient()
    return _client_instance
