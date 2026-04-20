"""Date validation utilities for agent tools."""

from datetime import date, datetime


def validate_dates(check_in: str, check_out: str) -> str | None:
    """Validate check-in and check-out dates.

    Returns an error message string if validation fails, None if dates are valid.
    """
    try:
        ci = datetime.strptime(check_in, "%Y-%m-%d").date()
    except ValueError:
        return f"Invalid check-in date format: '{check_in}'. Please use YYYY-MM-DD format."

    try:
        co = datetime.strptime(check_out, "%Y-%m-%d").date()
    except ValueError:
        return f"Invalid check-out date format: '{check_out}'. Please use YYYY-MM-DD format."

    today = date.today()

    if ci < today:
        return f"Check-in date {check_in} is in the past. Please provide a future date."

    if co <= ci:
        return f"Check-out date {check_out} must be after check-in date {check_in}."

    return None
