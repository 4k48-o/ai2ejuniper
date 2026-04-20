"""Serialize Juniper SOAP responses to Python dicts for LLM consumption and API output."""

from typing import Any


def serialize_hotel_avail(response: Any) -> list[dict]:
    """Convert HotelAvail SOAP response to a list of hotel dicts."""
    if response is None:
        return []

    hotels = []
    results = getattr(response, "Results", None) or getattr(response, "HotelResult", [])
    if not hasattr(results, "__iter__"):
        results = [results]

    for hotel in results:
        hotel_info = getattr(hotel, "HotelInfo", hotel)
        hotels.append({
            "hotel_code": str(getattr(hotel_info, "Code", getattr(hotel_info, "HotelCode", ""))),
            "name": str(getattr(hotel_info, "Name", "")),
            "category": str(getattr(hotel_info, "Category", "")),
            "address": str(getattr(hotel_info, "Address", "")),
            "city": str(getattr(hotel_info, "City", "")),
            "rate_plan_code": str(getattr(hotel, "RatePlanCode", "")),
            "total_price": str(getattr(hotel, "Price", getattr(hotel, "TotalPrice", "0"))),
            "currency": str(getattr(hotel, "Currency", "EUR")),
            "board_type": str(getattr(hotel, "BoardType", "")),
            "room_type": str(getattr(hotel, "RoomType", "")),
            "cancellation_policy": str(getattr(hotel, "CancellationPolicy", "")),
        })

    return hotels


def serialize_check_avail(response: Any) -> dict:
    """Convert HotelCheckAvail response to a dict."""
    return {
        "available": bool(getattr(response, "Available", False)),
        "rate_plan_code": str(getattr(response, "RatePlanCode", "")),
        "total_price": str(getattr(response, "Price", getattr(response, "TotalPrice", "0"))),
        "currency": str(getattr(response, "Currency", "EUR")),
        "price_changed": bool(getattr(response, "PriceChanged", False)),
    }


def serialize_booking_rules(response: Any) -> dict:
    """Convert HotelBookingRules response to a dict.

    Extracts BookingCode and its ExpirationDate for downstream use.
    """
    booking_code_node = getattr(response, "BookingCode", None)
    booking_code = ""
    booking_code_expires_at = ""
    if booking_code_node is not None:
        booking_code = str(getattr(booking_code_node, "_value_1", booking_code_node) or "")
        booking_code_expires_at = str(getattr(booking_code_node, "ExpirationDate", "") or "")

    return {
        "valid": bool(getattr(response, "Valid", False)),
        "rate_plan_code": str(getattr(response, "RatePlanCode", "")),
        "total_price": str(getattr(response, "Price", getattr(response, "TotalPrice", "0"))),
        "currency": str(getattr(response, "Currency", "EUR")),
        "cancellation_policy": str(getattr(response, "CancellationPolicy", "")),
        "remarks": str(getattr(response, "Remarks", "")),
        "booking_code": booking_code,
        "booking_code_expires_at": booking_code_expires_at,
    }


def serialize_booking(response: Any) -> dict:
    """Convert HotelBooking response to a dict."""
    return {
        "booking_id": str(getattr(response, "BookingId", getattr(response, "Locator", ""))),
        "status": str(getattr(response, "Status", "confirmed")),
        "hotel_name": str(getattr(response, "HotelName", "")),
        "check_in": str(getattr(response, "CheckIn", "")),
        "check_out": str(getattr(response, "CheckOut", "")),
        "total_price": str(getattr(response, "TotalPrice", "0")),
        "currency": str(getattr(response, "Currency", "EUR")),
    }


def serialize_read_booking(response: Any) -> dict:
    """Convert ReadBooking response to a dict."""
    return {
        "booking_id": str(getattr(response, "BookingId", getattr(response, "Locator", ""))),
        "status": str(getattr(response, "Status", "")),
        "hotel_name": str(getattr(response, "HotelName", "")),
        "check_in": str(getattr(response, "CheckIn", "")),
        "check_out": str(getattr(response, "CheckOut", "")),
        "total_price": str(getattr(response, "TotalPrice", "0")),
        "currency": str(getattr(response, "Currency", "EUR")),
        "guest_name": str(getattr(response, "GuestName", "")),
    }


def hotels_to_llm_summary(hotels: list[dict]) -> str:
    """Format hotel list for LLM context (concise version)."""
    if not hotels:
        return "No hotels found matching the criteria."

    lines = []
    for i, h in enumerate(hotels, 1):
        lines.append(
            f"{i}. {h['name']} ({h['category']}) - {h['total_price']} {h['currency']}/night"
            f" | {h['board_type']} | {h['city']}"
            f" | rate_plan_code: {h['rate_plan_code']}"
        )
    return "\n".join(lines)
