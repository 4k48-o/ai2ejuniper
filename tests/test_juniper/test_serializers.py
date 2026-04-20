"""Tests for Juniper response serializers."""

from juniper_ai.app.juniper.serializers import hotels_to_llm_summary


def test_hotels_to_llm_summary_empty():
    result = hotels_to_llm_summary([])
    assert "No hotels found" in result


def test_hotels_to_llm_summary_with_hotels():
    hotels = [
        {
            "name": "Hotel Test",
            "category": "4 stars",
            "total_price": "150.00",
            "currency": "EUR",
            "board_type": "Bed & Breakfast",
            "city": "Madrid",
            "rate_plan_code": "RPC_TEST_001",
        }
    ]
    result = hotels_to_llm_summary(hotels)
    assert "Hotel Test" in result
    assert "150.00" in result
    assert "EUR" in result
    assert "RPC_TEST_001" in result
