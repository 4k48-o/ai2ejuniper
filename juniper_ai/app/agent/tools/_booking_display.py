"""Format booking rows for agent tool text output."""


def guest_name_email_from_details(booking_details: dict | None) -> tuple[str, str]:
    """Read guest name and email from persisted ``booking_details`` (book_hotel payload)."""
    if not isinstance(booking_details, dict):
        return "N/A", "N/A"
    name = str(booking_details.get("guest_name") or "").strip() or "N/A"
    email = str(booking_details.get("guest_email") or "").strip() or "N/A"
    return name, email
