"""§11.3 — unit tests for the shared ``_parsers`` module.

These tests pin down the low-level contract that every serializer
(`serialize_hotel_avail`, and §11.4+ rewrites of `serialize_check_avail` /
`serialize_booking_rules` / `serialize_booking`) inherits. A regression here
ripples through the whole booking flow, so each parser gets a focused test
with a zeep-shaped ``SimpleNamespace`` stand-in mirroring the real XML
structures documented in ``uploads/hotel-api-0.md`` and
``agent-tools/3c188552-...txt``.
"""

from types import SimpleNamespace

from juniper_ai.app.juniper._parsers import (
    KNOWN_WARNING_CODES,
    attr,
    bool_attr,
    int_attr,
    iter_list,
    parse_allowed_credit_cards,
    parse_board,
    parse_booking_code,
    parse_cancellation_policy,
    parse_comments,
    parse_hotel_content_short,
    parse_hotel_info,
    parse_offers,
    parse_preferences,
    parse_prices,
    parse_required_fields,
    parse_rooms,
    parse_supplements,
    parse_warnings,
    text,
    warning_codes,
)


# ---------------------------------------------------------------------------
# Zeep-shape helpers
# ---------------------------------------------------------------------------


def test_iter_list_normalises_shapes():
    assert iter_list(None) == []
    assert iter_list([]) == []
    assert iter_list([1, None, 2]) == [1, 2]  # drops None
    assert iter_list((1, 2)) == [1, 2]
    single = SimpleNamespace(x=1)
    assert iter_list(single) == [single]  # single node wrapped


def test_text_handles_scalars_and_complex_types():
    assert text(None) == ""
    assert text(None, default="fallback") == "fallback"
    assert text("hello") == "hello"
    assert text(42) == "42"
    # Zeep complex-type-with-text: <elem Attr="X">payload</elem>
    assert text(SimpleNamespace(_value_1="payload", Attr="X")) == "payload"
    # Complex type with no _value_1 → default
    assert text(SimpleNamespace(Attr="X"), default="-") == "-"


def test_attr_and_bool_attr_and_int_attr():
    node = SimpleNamespace(Gross="223.01", Included="true", Units=3, Missing=None)
    assert attr(node, "Gross") == "223.01"
    assert attr(node, "Missing", default="0") == "0"  # None treated as missing
    assert attr(None, "Anything", default="d") == "d"

    assert bool_attr(node, "Included") is True
    assert bool_attr(node, "Missing", default=True) is True
    assert bool_attr(SimpleNamespace(Flag=False), "Flag") is False
    assert bool_attr(SimpleNamespace(Flag="1"), "Flag") is True
    assert bool_attr(SimpleNamespace(Flag="no"), "Flag") is False

    assert int_attr(node, "Units") == 3
    assert int_attr(node, "Missing") is None
    assert int_attr(node, "Missing", default=0) == 0
    # Non-numeric → default
    assert int_attr(SimpleNamespace(Units="abc"), "Units", default=-1) == -1


# ---------------------------------------------------------------------------
# Warnings
# ---------------------------------------------------------------------------


def test_parse_warnings_empty_and_absent():
    assert parse_warnings(None) == []
    assert parse_warnings(SimpleNamespace()) == []
    assert parse_warnings(SimpleNamespace(Warnings=None)) == []


def test_parse_warnings_single_and_multi():
    # Per docs: Warnings/Warning[*] with @Code + @Text. warnObsoleteJPCode
    # is emitted when a synonym JPCode was requested.
    response = SimpleNamespace(
        Warnings=SimpleNamespace(
            Warning=[
                SimpleNamespace(Code="warnObsoleteJPCode", Text="Use master JPCode"),
                SimpleNamespace(Code="warnPriceChanged", Text="Rate changed since search"),
            ]
        )
    )
    warnings = parse_warnings(response)
    assert warnings == [
        {"code": "warnObsoleteJPCode", "text": "Use master JPCode"},
        {"code": "warnPriceChanged", "text": "Rate changed since search"},
    ]

    codes = warning_codes(warnings)
    assert "warnPriceChanged" in codes
    assert "warnObsoleteJPCode" in codes
    assert codes <= KNOWN_WARNING_CODES.union({"warnPriceChanged", "warnObsoleteJPCode"})


def test_parse_warnings_tolerates_single_warning_not_wrapped_as_list():
    """Zeep returns a single Warning as a bare node (not a list)."""
    response = SimpleNamespace(
        Warnings=SimpleNamespace(
            Warning=SimpleNamespace(Code="warnStatusChanged", Text="Availability changed")
        )
    )
    assert parse_warnings(response) == [
        {"code": "warnStatusChanged", "text": "Availability changed"}
    ]


# ---------------------------------------------------------------------------
# Board / HotelInfo / Rooms
# ---------------------------------------------------------------------------


def test_parse_board_missing_and_full():
    assert parse_board(None) == {"type": "", "name": ""}
    board = SimpleNamespace(Type="SA", _value_1="Room Only")
    assert parse_board(board) == {"type": "SA", "name": "Room Only"}


def test_parse_hotel_info_missing_returns_blank_dict():
    """ShowHotelInfo=false → serializer still returns a usable empty dict."""
    info = parse_hotel_info(None)
    assert info["name"] == ""
    assert info["category"] == ""
    assert info["category_type"] == ""


def test_parse_hotel_info_full():
    node = SimpleNamespace(
        Name="Meliá Palma Bay",
        Address="Avinguda Gabriel Roca 39",
        Latitude="39.57",
        Longitude="2.63",
        HotelCategory=SimpleNamespace(Type="4est", _value_1="4 Stars"),
    )
    info = parse_hotel_info(node)
    assert info["name"] == "Meliá Palma Bay"
    assert info["category"] == "4 Stars"
    assert info["category_type"] == "4est"
    assert info["latitude"] == "39.57"


def test_parse_hotel_info_tolerates_list_category():
    """HotelCategory may come as a list (rare) — take the first."""
    node = SimpleNamespace(
        Name="X", Address="", Latitude="", Longitude="",
        HotelCategory=[
            SimpleNamespace(Type="3est", _value_1="3 Stars"),
            SimpleNamespace(Type="4est", _value_1="4 Stars"),
        ],
    )
    info = parse_hotel_info(node)
    assert info["category"] == "3 Stars"
    assert info["category_type"] == "3est"


def test_parse_rooms_handles_absent_and_populated():
    assert parse_rooms(None) == []
    rooms_node = SimpleNamespace(
        HotelRoom=[
            SimpleNamespace(
                Name="Double Standard",
                Units=1, Source=2, AvailRooms=10,
                RoomCategory=SimpleNamespace(Type="DBT.ST", _value_1="Double Standard"),
                RoomOccupancy=SimpleNamespace(Occupancy=2, Adults=2, Children=0),
            ),
        ]
    )
    rooms = parse_rooms(rooms_node)
    assert len(rooms) == 1
    assert rooms[0]["category_type"] == "DBT.ST"
    assert rooms[0]["units"] == 1
    assert rooms[0]["avail_rooms"] == 10
    assert rooms[0]["adults"] == 2


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------


def test_parse_prices_none():
    empty = parse_prices(None)
    assert empty["total_price"] == "0"
    assert empty["currency"] == ""
    assert empty["taxes_included"] is None


def test_parse_prices_full_with_service_and_taxes():
    """Mirrors ``uploads/hotel-api-0.md`` lines 43-50."""
    total_fix = SimpleNamespace(
        Gross="223.01",
        Nett="223.01",
        Service=SimpleNamespace(Amount="202.74"),
        ServiceTaxes=SimpleNamespace(Included="false", Amount="20.27"),
    )
    prices = SimpleNamespace(
        Price=[SimpleNamespace(Currency="EUR", Type="S", TotalFixAmounts=total_fix)]
    )
    out = parse_prices(prices)
    assert out == {
        "currency": "EUR",
        "total_price": "223.01",
        "nett_price": "223.01",
        "service": "202.74",
        "service_taxes": "20.27",
        "taxes_included": False,
    }


def test_parse_prices_takes_first_when_multiple():
    """Suppliers may return multiple Price blocks (sale + cost); agent uses
    the first (primary sale price)."""
    prices = SimpleNamespace(Price=[
        SimpleNamespace(Currency="EUR", Type="S", TotalFixAmounts=SimpleNamespace(Gross="100", Nett="100")),
        SimpleNamespace(Currency="EUR", Type="C", TotalFixAmounts=SimpleNamespace(Gross="80", Nett="80")),
    ])
    assert parse_prices(prices)["total_price"] == "100"


# ---------------------------------------------------------------------------
# CancellationPolicy — tightest test in this module because the XML is real
# prone to mis-parsing (PercentPrice, not Percent; rules nested under
# PolicyRules; from/to in *days*; multiple Rule entries with different Type).
# ---------------------------------------------------------------------------


def test_parse_cancellation_policy_none():
    assert parse_cancellation_policy(None) is None


def test_parse_cancellation_policy_mirrors_official_sample():
    """Recreates the sample from the official docs
    (``agent-tools/...txt`` lines 2701-2709)."""
    rule1 = SimpleNamespace(
        From=0, To=3,
        DateFrom="2019-11-17", DateFromHour="00:00",
        DateTo="2019-11-21", DateToHour="00:00",
        Type="V",
        FixedPrice="0", PercentPrice="100",
        Nights=0, ApplicationTypeNights="Average",
        FirstNightPrice=None, MostExpensiveNightPrice=None,
    )
    rule2 = SimpleNamespace(
        From=4, To=7,
        DateFrom="2019-11-13", DateFromHour="00:00",
        DateTo="2019-11-17", DateToHour="00:00",
        Type="V",
        FixedPrice="0", PercentPrice="25",
        Nights=0, ApplicationTypeNights="Average",
        FirstNightPrice=None, MostExpensiveNightPrice=None,
    )
    node = SimpleNamespace(
        CurrencyCode="EUR",
        FirstDayCostCancellation=SimpleNamespace(Hour="00:00", _value_1="2019-11-13"),
        Description=None,
        PolicyRules=SimpleNamespace(Rule=[rule1, rule2]),
    )
    parsed = parse_cancellation_policy(node)
    assert parsed is not None
    assert parsed["currency"] == "EUR"
    assert parsed["first_day_cost_date"] == "2019-11-13"
    assert parsed["first_day_cost_hour"] == "00:00"
    assert len(parsed["rules"]) == 2

    # First rule: 100% fee window closest to check-in
    r1 = parsed["rules"][0]
    assert r1["type"] == "V"
    assert r1["from_days"] == 0
    assert r1["to_days"] == 3
    assert r1["percent_price"] == "100"   # NOT ``percent``
    assert r1["fixed_price"] == "0"
    assert r1["application_type_nights"] == "Average"

    # Second rule: 25% fee for a 4-7 day window
    r2 = parsed["rules"][1]
    assert r2["percent_price"] == "25"
    assert r2["from_days"] == 4
    assert r2["to_days"] == 7


def test_parse_cancellation_policy_tolerates_open_ended_rule():
    """Rules without @To describe an open-ended window (e.g. "8+ days out").
    Must not crash and should surface ``to_days=None``."""
    rule = SimpleNamespace(
        From=8, To=None,
        DateFrom="2019-10-03", DateFromHour="00:00",
        DateTo="2019-11-13", DateToHour="00:00",
        Type="V",
        FixedPrice="0", PercentPrice="0",
        Nights=None, ApplicationTypeNights="Average",
        FirstNightPrice=None, MostExpensiveNightPrice=None,
    )
    node = SimpleNamespace(
        CurrencyCode="USD",
        FirstDayCostCancellation=None,
        PolicyRules=SimpleNamespace(Rule=rule),  # single rule, not wrapped
    )
    parsed = parse_cancellation_policy(node)
    assert parsed["currency"] == "USD"
    assert parsed["first_day_cost_date"] == ""
    assert len(parsed["rules"]) == 1
    assert parsed["rules"][0]["from_days"] == 8
    assert parsed["rules"][0]["to_days"] is None
    assert parsed["rules"][0]["percent_price"] == "0"


def test_parse_cancellation_policy_no_rules_returns_empty_list():
    node = SimpleNamespace(
        CurrencyCode="EUR",
        FirstDayCostCancellation=SimpleNamespace(Hour="12:00", _value_1="2026-06-01"),
        PolicyRules=None,
    )
    parsed = parse_cancellation_policy(node)
    assert parsed["rules"] == []


# ---------------------------------------------------------------------------
# Offers / Supplements
# ---------------------------------------------------------------------------


def test_parse_offers_and_supplements_absent():
    assert parse_offers(None) == []
    assert parse_supplements(None) == []
    # AdditionalElements present but empty wrappers
    empty = SimpleNamespace(HotelOffers=None, HotelSupplements=None)
    assert parse_offers(empty) == []
    assert parse_supplements(empty) == []


def test_parse_offers_populated():
    additional = SimpleNamespace(
        HotelOffers=SimpleNamespace(
            HotelOffer=[
                SimpleNamespace(
                    Code="843", Category="GEN",
                    Begin="2026-06-01", End="2026-06-30",
                    RoomCategory="DBT.ST",
                    Name="Early Bird", Description="5% off",
                ),
            ]
        ),
    )
    offers = parse_offers(additional)
    assert offers == [{
        "code": "843",
        "category": "GEN",
        "begin": "2026-06-01",
        "end": "2026-06-30",
        "room_category": "DBT.ST",
        "name": "Early Bird",
        "description": "5% off",
    }]


def test_parse_supplements_populated():
    additional = SimpleNamespace(
        HotelSupplements=SimpleNamespace(
            HotelSupplement=[
                SimpleNamespace(
                    Code="WIFI",
                    Name="WiFi",
                    Description="Premium WiFi in room",
                    DirectPayment="true",
                ),
            ]
        ),
    )
    supps = parse_supplements(additional)
    assert supps == [{
        "code": "WIFI",
        "name": "WiFi",
        "description": "Premium WiFi in room",
        "direct_payment": True,
    }]


# ---------------------------------------------------------------------------
# BookingRules-specific parsers (§11.5 additions)
# ---------------------------------------------------------------------------


def test_parse_booking_code_with_expiration():
    node = SimpleNamespace(
        _value_1="ya79dM4dS6R6EywV4XhfEvwI...",
        ExpirationDate="2019-10-03T09:46:30+02:00",
    )
    parsed = parse_booking_code(node)
    assert parsed["value"] == "ya79dM4dS6R6EywV4XhfEvwI..."
    assert parsed["expires_at"] == "2019-10-03T09:46:30+02:00"


def test_parse_booking_code_as_bare_string():
    """When zeep hands us a bare string we still surface it as ``value``
    with empty expiry — callers should refresh before use."""
    parsed = parse_booking_code("BARE_CODE_ABC")
    assert parsed == {"value": "BARE_CODE_ABC", "expires_at": ""}


def test_parse_booking_code_none():
    assert parse_booking_code(None) == {"value": "", "expires_at": ""}


def test_parse_hotel_content_short_from_booking_rules_shape():
    """Mirror lines 2740-2753 of the official example — especially the
    ``<Address><Address>…</Address></Address>`` double-nesting."""
    node = SimpleNamespace(
        Code="JP046300",
        JPCode=None,
        HotelName="APARTAMENTOS ALLSUN PIL-LARI PLAYA",
        Zone=SimpleNamespace(JPDCode="JPD086855", Code="49435"),
        HotelCategory=SimpleNamespace(Type="3est", _value_1="3 Stars"),
        HotelType=SimpleNamespace(Type="GEN", _value_1="General"),
        Address=SimpleNamespace(
            Address="Calle Marbella 24",
            Latitude="39.564713", Longitude="2.627979",
        ),
    )
    parsed = parse_hotel_content_short(node)
    assert parsed["code"] == "JP046300"
    # When ``@JPCode`` is absent the parser falls back to ``@Code`` so
    # downstream DB-joins still work.
    assert parsed["jpcode"] == "JP046300"
    assert parsed["name"] == "APARTAMENTOS ALLSUN PIL-LARI PLAYA"
    assert parsed["category"] == "3 Stars"
    assert parsed["category_type"] == "3est"
    assert parsed["type"] == "General"
    assert parsed["type_code"] == "GEN"
    assert parsed["jpdcode"] == "JPD086855"
    assert parsed["zone_code"] == "49435"
    assert parsed["address"] == "Calle Marbella 24"
    assert parsed["latitude"] == "39.564713"
    assert parsed["longitude"] == "2.627979"


def test_parse_hotel_content_short_none_yields_empty_shape():
    parsed = parse_hotel_content_short(None)
    assert parsed == {
        "code": "", "jpcode": "", "name": "",
        "category": "", "category_type": "",
        "type": "", "type_code": "",
        "jpdcode": "", "zone_code": "",
        "address": "", "latitude": "", "longitude": "",
    }


def test_parse_comments_from_optional_elements():
    """Comments/Comment[*] — critical for showing additional taxes,
    promo explanations, etc. from the hotel. CDATA text is preserved."""
    oe = SimpleNamespace(
        Comments=SimpleNamespace(
            Comment=[
                SimpleNamespace(Type="HOT", _value_1="City tax 2 EUR/pax/night"),
                SimpleNamespace(Type="GEN", _value_1="Pool closed for renovations"),
            ]
        )
    )
    assert parse_comments(oe) == [
        {"type": "HOT", "text": "City tax 2 EUR/pax/night"},
        {"type": "GEN", "text": "Pool closed for renovations"},
    ]


def test_parse_comments_empty_shapes():
    assert parse_comments(None) == []
    assert parse_comments(SimpleNamespace(Comments=None)) == []


def test_parse_preferences_and_credit_cards():
    oe = SimpleNamespace(
        Preferences=SimpleNamespace(
            Preference=[SimpleNamespace(
                Code="LATE_CHKIN",
                Description=SimpleNamespace(_value_1="Late check-in"),
            )]
        ),
        AllowedCreditCards=SimpleNamespace(
            CreditCard=[
                SimpleNamespace(Code="VISA", _value_1="Visa"),
                SimpleNamespace(Code="MC", _value_1="Mastercard"),
            ]
        ),
    )
    assert parse_preferences(oe) == [
        {"code": "LATE_CHKIN", "description": "Late check-in"},
    ]
    assert parse_allowed_credit_cards(oe) == [
        {"code": "VISA", "name": "Visa"},
        {"code": "MC", "name": "Mastercard"},
    ]


def test_parse_preferences_and_credit_cards_empty():
    assert parse_preferences(None) == []
    assert parse_allowed_credit_cards(None) == []


def test_parse_required_fields_captures_pax_template_and_holder():
    """The required-fields TEMPLATE: which child elements are present on
    each pax, holder→pax mapping, plus the hotel-element metadata needed
    to build the subsequent HotelBooking request."""
    node = SimpleNamespace(
        HotelBooking=SimpleNamespace(
            Paxes=SimpleNamespace(Pax=[
                SimpleNamespace(
                    IdPax="1",
                    Name="Holder Name", Surname="Holder Surname",
                    PhoneNumbers=SimpleNamespace(PhoneNumber="000000000"),
                    Address="Address", City="City", Country="Country",
                    PostalCode="00000", Age="30",
                ),
                SimpleNamespace(IdPax="2", Age="30"),
                SimpleNamespace(IdPax="3", Age="8"),
            ]),
            Holder=SimpleNamespace(RelPax=SimpleNamespace(IdPax="1")),
            Elements=SimpleNamespace(
                HotelElement=SimpleNamespace(
                    BookingCode="ya79...",
                    HotelBookingInfo=SimpleNamespace(
                        Start="2019-11-20", End="2019-11-22",
                        HotelCode="JP046300",
                    ),
                )
            ),
        )
    )
    parsed = parse_required_fields(node)
    assert parsed["has_hotel_element"] is True
    assert parsed["has_booking_code"] is True
    assert parsed["hotel_codes"] == ["JP046300"]
    assert parsed["check_in"] == "2019-11-20"
    assert parsed["check_out"] == "2019-11-22"
    assert parsed["holder"]["rel_pax_ids"] == ["1"]

    by_id = {p["id_pax"]: p for p in parsed["paxes"]}
    assert "PhoneNumbers" in by_id["1"]["fields"]
    assert "Address" in by_id["1"]["fields"]
    assert "Age" in by_id["1"]["fields"]
    # Pax 2 / 3 only have Age — template must not falsely require other fields.
    assert by_id["2"]["fields"] == ["Age"]
    assert by_id["3"]["fields"] == ["Age"]


def test_parse_required_fields_empty_shapes():
    empty = {
        "paxes": [], "holder": {"rel_pax_ids": []},
        "has_hotel_element": False, "has_booking_code": False,
        "hotel_codes": [], "check_in": "", "check_out": "",
    }
    assert parse_required_fields(None) == empty
    assert parse_required_fields(SimpleNamespace(HotelBooking=None)) == empty


def test_parse_required_fields_multiple_holders():
    """Holder may reference multiple pax (joint-holder bookings)."""
    node = SimpleNamespace(
        HotelBooking=SimpleNamespace(
            Paxes=SimpleNamespace(Pax=[
                SimpleNamespace(IdPax="1", Name="A"),
                SimpleNamespace(IdPax="2", Name="B"),
            ]),
            Holder=SimpleNamespace(RelPax=[
                SimpleNamespace(IdPax="1"),
                SimpleNamespace(IdPax="2"),
            ]),
            Elements=None,
        )
    )
    parsed = parse_required_fields(node)
    assert parsed["holder"]["rel_pax_ids"] == ["1", "2"]
    assert parsed["has_hotel_element"] is False
