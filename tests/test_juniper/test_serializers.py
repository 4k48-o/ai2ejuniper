"""Tests for Juniper response serializers."""

from types import SimpleNamespace

from juniper_ai.app.juniper.serializers import (
    hotels_to_llm_summary,
    serialize_booking,
    serialize_booking_rules,
    serialize_check_avail,
    serialize_hotel_avail,
    serialize_read_booking,
)


# ---------------------------------------------------------------------------
# hotels_to_llm_summary
# ---------------------------------------------------------------------------


def test_hotels_to_llm_summary_empty():
    result = hotels_to_llm_summary([])
    assert "No hotels found" in result


def test_hotels_to_llm_summary_with_hotels():
    """Legacy/mock-shaped input must still render cleanly."""
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


def test_hotels_to_llm_summary_prefers_board_name_and_marks_rq():
    """New-shaped input uses board_name and annotates status=RQ."""
    hotels = [
        {
            "name": "Playa Hotel",
            "category": "3 Stars",
            "total_price": "223.01",
            "currency": "EUR",
            "board_name": "Room Only",
            "jpdcode": "JPD086855",
            "rate_plan_code": "ABC",
            "status": "RQ",
        },
    ]
    result = hotels_to_llm_summary(hotels)
    assert "Playa Hotel" in result
    assert "Room Only" in result
    assert "JPD086855" in result
    assert "on request" in result


def test_hotels_to_llm_summary_falls_back_to_hotel_code_when_name_missing():
    hotels = [{"hotel_code": "JP046300", "total_price": "447.13", "currency": "EUR"}]
    result = hotels_to_llm_summary(hotels)
    assert "JP046300" in result
    assert "447.13" in result


# ---------------------------------------------------------------------------
# serialize_hotel_avail — new nested-response contract (§11.1)
# ---------------------------------------------------------------------------


def _make_board(code: str, name: str) -> SimpleNamespace:
    return SimpleNamespace(Type=code, _value_1=name)


def _make_prices(currency: str, gross: str, nett: str | None = None) -> SimpleNamespace:
    """Build a zeep-ish ``Prices`` wrapper."""
    total_fix = SimpleNamespace(
        Gross=gross,
        Nett=nett or gross,
        Service=SimpleNamespace(Amount=gross),
        ServiceTaxes=None,
    )
    price = SimpleNamespace(Currency=currency, Type="S", TotalFixAmounts=total_fix)
    return SimpleNamespace(Price=[price])


def _make_hotel_rooms(names: list[str]) -> SimpleNamespace:
    rooms = [
        SimpleNamespace(
            Name=name,
            Units=1,
            Source=i + 1,
            AvailRooms=None,
            RoomCategory=SimpleNamespace(Type="DBT.ST", _value_1="Double Standard"),
            RoomOccupancy=SimpleNamespace(Occupancy=2, Adults=2, Children=0),
        )
        for i, name in enumerate(names)
    ]
    return SimpleNamespace(HotelRoom=rooms)


def _make_hotel_avail_response() -> SimpleNamespace:
    """Mirror the official HotelAvailResponse example:

    * 1 HotelResult (JP046300) with full HotelInfo
    * 2 HotelOptions (Room Only SA / Half Board MP)
    * Each option has 1-2 HotelRoom entries
    """
    hotel_info = SimpleNamespace(
        Name="Meliá Palma Bay",
        Address="Avinguda Gabriel Roca 39",
        Latitude="39.57",
        Longitude="2.63",
        HotelCategory=SimpleNamespace(Type="4est", _value_1="4 Stars"),
    )

    opt1 = SimpleNamespace(
        RatePlanCode="RPC_ROOM_ONLY",
        Status="OK",
        NonRefundable="true",
        PackageContract="false",
        Board=_make_board("SA", "Room Only"),
        Prices=_make_prices("EUR", "223.01"),
        HotelRooms=_make_hotel_rooms(["Double Standard"]),
        AdditionalElements=SimpleNamespace(
            HotelOffers=SimpleNamespace(
                HotelOffer=[SimpleNamespace(
                    Code="843",
                    Category="GEN",
                    Begin="",
                    End="",
                    RoomCategory="",
                    Name="5% discount",
                    Description="Early bird",
                )]
            )
        ),
        CancellationPolicy=None,
    )
    opt2 = SimpleNamespace(
        RatePlanCode="RPC_HALF_BOARD",
        Status="RQ",
        NonRefundable="false",
        PackageContract="false",
        Board=_make_board("MP", "Half Board"),
        Prices=_make_prices("EUR", "289.50"),
        HotelRooms=_make_hotel_rooms(["Double Standard", "Sea View Double"]),
        AdditionalElements=None,
        CancellationPolicy=None,
    )

    hotel_result = SimpleNamespace(
        Code="JP046300",
        JPCode="JP046300",
        JPDCode="JPD086855",
        DestinationZone="15011",
        BestDeal="false",
        HotelInfo=hotel_info,
        HotelOptions=SimpleNamespace(HotelOption=[opt1, opt2]),
    )
    return SimpleNamespace(
        Results=SimpleNamespace(HotelResult=[hotel_result])
    )


def test_serialize_hotel_avail_expands_each_hoteloption_into_a_row():
    response = _make_hotel_avail_response()
    hotels = serialize_hotel_avail(response)

    assert len(hotels) == 2, "Each HotelOption must produce its own row"

    # Hotel-level fields are duplicated on every option
    for h in hotels:
        assert h["hotel_code"] == "JP046300"
        assert h["jpcode"] == "JP046300"
        assert h["jpdcode"] == "JPD086855"
        assert h["destination_zone"] == "15011"
        assert h["name"] == "Meliá Palma Bay"
        assert h["address"] == "Avinguda Gabriel Roca 39"
        assert h["category"] == "4 Stars"
        assert h["category_type"] == "4est"
        assert h["latitude"] == "39.57"
        assert h["best_deal"] is False

    # Option-specific fields vary
    by_rpc = {h["rate_plan_code"]: h for h in hotels}
    assert set(by_rpc) == {"RPC_ROOM_ONLY", "RPC_HALF_BOARD"}

    room_only = by_rpc["RPC_ROOM_ONLY"]
    assert room_only["board_type"] == "SA"
    assert room_only["board_name"] == "Room Only"
    assert room_only["total_price"] == "223.01"
    assert room_only["nett_price"] == "223.01"
    assert room_only["currency"] == "EUR"
    assert room_only["status"] == "OK"
    assert room_only["non_refundable"] is True
    assert len(room_only["rooms"]) == 1
    assert room_only["rooms"][0]["category_type"] == "DBT.ST"
    assert room_only["rooms"][0]["occupancy"] == 2
    assert len(room_only["offers"]) == 1
    assert room_only["offers"][0]["code"] == "843"

    half_board = by_rpc["RPC_HALF_BOARD"]
    assert half_board["board_type"] == "MP"
    assert half_board["board_name"] == "Half Board"
    assert half_board["total_price"] == "289.50"
    assert half_board["status"] == "RQ"
    assert half_board["non_refundable"] is False
    assert len(half_board["rooms"]) == 2


def test_serialize_hotel_avail_empty_and_none_responses():
    assert serialize_hotel_avail(None) == []
    empty = SimpleNamespace(Results=SimpleNamespace(HotelResult=None))
    assert serialize_hotel_avail(empty) == []


def test_serialize_hotel_avail_skips_hotelresult_without_options():
    """A HotelResult with no HotelOption is not a useful candidate."""
    hr = SimpleNamespace(
        Code="JP_EMPTY",
        JPCode="JP_EMPTY",
        JPDCode="",
        DestinationZone="",
        BestDeal="false",
        HotelInfo=None,
        HotelOptions=SimpleNamespace(HotelOption=None),
    )
    response = SimpleNamespace(Results=SimpleNamespace(HotelResult=[hr]))
    assert serialize_hotel_avail(response) == []


def test_serialize_hotel_avail_tolerates_missing_hotel_info():
    """ShowHotelInfo=false → HotelInfo is absent; serializer must not crash."""
    opt = SimpleNamespace(
        RatePlanCode="RPC_NOHI",
        Status="OK",
        NonRefundable=None,
        PackageContract=None,
        Board=_make_board("SA", "Room Only"),
        Prices=_make_prices("USD", "100.00"),
        HotelRooms=None,
        AdditionalElements=None,
        CancellationPolicy=None,
    )
    hr = SimpleNamespace(
        Code="JP001",
        JPCode="JP001",
        JPDCode="",
        DestinationZone="",
        BestDeal="false",
        HotelInfo=None,
        HotelOptions=SimpleNamespace(HotelOption=opt),
    )
    response = SimpleNamespace(Results=SimpleNamespace(HotelResult=hr))

    hotels = serialize_hotel_avail(response)
    assert len(hotels) == 1
    h = hotels[0]
    assert h["hotel_code"] == "JP001"
    assert h["name"] == ""
    assert h["rate_plan_code"] == "RPC_NOHI"
    assert h["currency"] == "USD"
    assert h["total_price"] == "100.00"
    assert h["rooms"] == []


def test_serialize_hotel_avail_xs_any_results_binding():
    """Regression test for the UAT 2026-04-23 diagnosis: Juniper WSDL
    declares ``Results`` with xs:any so zeep packs ``<HotelResult>``
    children into ``Results._value_1`` (list of lxml Elements) instead
    of exposing them as a named ``Results.HotelResult`` attribute.

    Before the fix, ``serialize_hotel_avail`` looked only at the named
    attribute and returned ``[]`` even though Juniper returned a valid
    hotel with multiple board plans — manifesting as spurious
    ``NO_RESULTS`` batches in the sandbox. The fix routes through
    ``resolve_child`` which falls back to ``_value_1`` when the named
    attr is empty.
    """
    from lxml import etree

    xml = """<?xml version="1.0" encoding="UTF-8"?>
<AvailabilityRS xmlns="http://www.juniper.es/webservice/2007/">
  <Results>
    <HotelResult Code="JP046300" JPCode="JP046300" JPDCode="JPD086855"
                 BestDeal="false" Type="HOTEL" DestinationZone="49435">
      <HotelInfo>
        <Name>Allsun Hotel Pil\u00b7lar\u00ed Playa UAT</Name>
        <HotelCategory Type="3est">3 Stars</HotelCategory>
        <Address>Carrer Marbella, 24</Address>
      </HotelInfo>
      <HotelOptions>
        <HotelOption RatePlanCode="RPC_SA" Status="OK" NonRefundable="false" PackageContract="false">
          <Board Type="SA" ExternalCode="3">Room Only</Board>
          <Prices>
            <Price Type="S" Currency="EUR">
              <TotalFixAmounts Gross="291.52" Nett="291.52">
                <Service Amount="268.2"/>
                <ServiceTaxes Included="false" Amount="23.32"/>
              </TotalFixAmounts>
            </Price>
          </Prices>
        </HotelOption>
        <HotelOption RatePlanCode="RPC_MP" Status="OK" NonRefundable="false" PackageContract="false">
          <Board Type="MP" ExternalCode="1">Half Board</Board>
          <Prices>
            <Price Type="S" Currency="EUR">
              <TotalFixAmounts Gross="305.41" Nett="305.41"/>
            </Price>
          </Prices>
        </HotelOption>
      </HotelOptions>
    </HotelResult>
  </Results>
</AvailabilityRS>
"""
    root = etree.fromstring(xml.encode("utf-8"))
    NS = "{http://www.juniper.es/webservice/2007/}"
    results_el = root.find(f"{NS}Results")
    hotel_result_el = results_el.find(f"{NS}HotelResult")
    assert hotel_result_el is not None

    # Simulate zeep's xs:any binding exactly: Results has no named
    # ``HotelResult`` attribute at all, only a ``_value_1`` list of lxml
    # Elements. Every *other* named attr is absent (returns None via
    # SimpleNamespace's lack of attribute → we expose Errors=None etc.).
    results_xs_any = SimpleNamespace(
        HotelResult=None,
        _value_1=[hotel_result_el],
    )
    response = SimpleNamespace(
        Results=results_xs_any,
        HotelResult=None,
        Errors=None,
        Warnings=None,
    )

    hotels = serialize_hotel_avail(response)

    assert len(hotels) == 2, f"expected 2 rows from 2 HotelOptions, got {len(hotels)}"
    sa_row = next(h for h in hotels if h["board_type"] == "SA")
    mp_row = next(h for h in hotels if h["board_type"] == "MP")
    assert sa_row["name"] == "Allsun Hotel Pil\u00b7lar\u00ed Playa UAT"
    assert sa_row["jpcode"] == "JP046300"
    assert sa_row["jpdcode"] == "JPD086855"
    assert sa_row["destination_zone"] == "49435"
    assert sa_row["rate_plan_code"] == "RPC_SA"
    assert sa_row["status"] == "OK"
    assert sa_row["total_price"] == "291.52"
    assert sa_row["currency"] == "EUR"
    assert sa_row["board_name"] == "Room Only"
    assert mp_row["rate_plan_code"] == "RPC_MP"
    assert mp_row["total_price"] == "305.41"
    assert mp_row["board_name"] == "Half Board"


def test_serialize_hotel_avail_xs_any_dict_binding():
    """Second UAT 2026-04-23 finding — zeep sometimes deserialises the
    xs:any children into *plain Python dicts* instead of lxml Elements.

    Smoking gun from the probe::

        .Results._value_1[0] = builtins.dict()
        iter_xs_any_children(HotelResult): dropped 1 item(s) with no
        match; types=['builtins.dict']

    The fix wraps dicts in ``_DictProxy`` (inside
    :func:`unwrap_xs_any_item`) so downstream ``getattr``-based parsers
    keep working. This test reproduces that exact binding by handing
    the serializer a ``Results._value_1 = [ {HotelResult-as-dict} ]``
    structure and asserting the rows come out.
    """
    hotel_result_dict = {
        "Code": "JP046300",
        "JPCode": "JP046300",
        "JPDCode": "JPD086855",
        "BestDeal": "false",
        "Type": "HOTEL",
        "DestinationZone": "49435",
        "HotelInfo": {
            "Name": "Allsun Hotel Pil\u00b7lar\u00ed Playa UAT",
            "HotelCategory": {"Type": "3est", "_value_1": "3 Stars"},
            "Address": "Carrer Marbella, 24",
        },
        "HotelOptions": {
            "HotelOption": [
                {
                    "RatePlanCode": "RPC_SA",
                    "Status": "OK",
                    "NonRefundable": "false",
                    "PackageContract": "false",
                    "Board": {"Type": "SA", "ExternalCode": "3", "_value_1": "Room Only"},
                    "Prices": {
                        "Price": {
                            "Type": "S",
                            "Currency": "EUR",
                            "TotalFixAmounts": {
                                "Gross": "291.52",
                                "Nett": "291.52",
                                "Service": {"Amount": "268.2"},
                                "ServiceTaxes": {"Included": "false", "Amount": "23.32"},
                            },
                        },
                    },
                },
                {
                    "RatePlanCode": "RPC_MP",
                    "Status": "OK",
                    "NonRefundable": "false",
                    "PackageContract": "false",
                    "Board": {"Type": "MP", "ExternalCode": "1", "_value_1": "Half Board"},
                    "Prices": {
                        "Price": {
                            "Type": "S",
                            "Currency": "EUR",
                            "TotalFixAmounts": {"Gross": "305.41", "Nett": "305.41"},
                        },
                    },
                },
            ],
        },
    }
    results_xs_any = SimpleNamespace(
        HotelResult=None,
        _value_1=[hotel_result_dict],
    )
    response = SimpleNamespace(
        Results=results_xs_any,
        HotelResult=None,
        Errors=None,
        Warnings=None,
    )

    hotels = serialize_hotel_avail(response)

    assert len(hotels) == 2, f"expected 2 rows from 2 HotelOptions, got {len(hotels)}"
    sa_row = next(h for h in hotels if h["board_type"] == "SA")
    mp_row = next(h for h in hotels if h["board_type"] == "MP")
    assert sa_row["name"] == "Allsun Hotel Pil\u00b7lar\u00ed Playa UAT"
    assert sa_row["jpcode"] == "JP046300"
    assert sa_row["jpdcode"] == "JPD086855"
    assert sa_row["destination_zone"] == "49435"
    assert sa_row["rate_plan_code"] == "RPC_SA"
    assert sa_row["status"] == "OK"
    assert sa_row["total_price"] == "291.52"
    assert sa_row["currency"] == "EUR"
    assert sa_row["board_name"] == "Room Only"
    assert mp_row["rate_plan_code"] == "RPC_MP"
    assert mp_row["total_price"] == "305.41"
    assert mp_row["board_name"] == "Half Board"


def test_serialize_hotel_avail_xs_any_dict_single_option():
    """Same dict path, but with a single HotelOption (zeep collapses
    single-element lists — ``HotelOption`` becomes a dict, not a list).
    """
    hotel_result_dict = {
        "JPCode": "JP000001",
        "JPDCode": "JPD000001",
        "HotelInfo": {"Name": "Solo Inn"},
        "HotelOptions": {
            "HotelOption": {
                "RatePlanCode": "RPC_SOLO",
                "Status": "OK",
                "Board": {"Type": "AD", "_value_1": "Bed & Breakfast"},
                "Prices": {
                    "Price": {
                        "Currency": "USD",
                        "TotalFixAmounts": {"Gross": "99.00", "Nett": "99.00"},
                    },
                },
            },
        },
    }
    response = SimpleNamespace(
        Results=SimpleNamespace(HotelResult=None, _value_1=[hotel_result_dict]),
        HotelResult=None,
        Errors=None,
    )
    hotels = serialize_hotel_avail(response)
    assert len(hotels) == 1
    assert hotels[0]["name"] == "Solo Inn"
    assert hotels[0]["rate_plan_code"] == "RPC_SOLO"
    assert hotels[0]["board_type"] == "AD"
    assert hotels[0]["total_price"] == "99.00"
    assert hotels[0]["currency"] == "USD"


def test_serialize_hotel_avail_single_hotelresult_single_hoteloption_not_wrapped_as_list():
    """Zeep sometimes returns a single node rather than a list — must still work."""
    opt = SimpleNamespace(
        RatePlanCode="RPC_SINGLE",
        Status="OK",
        NonRefundable=None,
        PackageContract=None,
        Board=_make_board("AD", "Bed & Breakfast"),
        Prices=_make_prices("EUR", "50.00"),
        HotelRooms=_make_hotel_rooms(["Single"]),
        AdditionalElements=None,
        CancellationPolicy=None,
    )
    hr = SimpleNamespace(
        Code="JP999",
        JPCode="JP999",
        JPDCode="JPDX",
        DestinationZone="9",
        BestDeal="true",
        HotelInfo=SimpleNamespace(
            Name="Solo Hotel",
            Address="Calle Uno",
            Latitude="",
            Longitude="",
            HotelCategory=SimpleNamespace(Type="3est", _value_1="3 Stars"),
        ),
        HotelOptions=SimpleNamespace(HotelOption=opt),
    )
    response = SimpleNamespace(Results=SimpleNamespace(HotelResult=hr))

    hotels = serialize_hotel_avail(response)
    assert len(hotels) == 1
    h = hotels[0]
    assert h["name"] == "Solo Hotel"
    assert h["best_deal"] is True
    assert h["rate_plan_code"] == "RPC_SINGLE"
    assert h["board_type"] == "AD"


# ---------------------------------------------------------------------------
# serialize_hotel_avail — §11.3 additions (warnings + refundable tri-state)
# ---------------------------------------------------------------------------


def test_serialize_hotel_avail_derives_refundable_tri_state():
    """``refundable`` is the negation of ``NonRefundable`` when present, and
    ``None`` when the supplier omits the attribute — callers must not
    conflate missing with refundable."""
    # (1) NonRefundable="true" → refundable=False
    opt_nonref = SimpleNamespace(
        RatePlanCode="RPC_NR", Status="OK",
        NonRefundable="true", PackageContract=None,
        Board=_make_board("SA", "Room Only"),
        Prices=_make_prices("EUR", "100.00"),
        HotelRooms=None, AdditionalElements=None, CancellationPolicy=None,
    )
    # (2) NonRefundable="false" → refundable=True
    opt_ref = SimpleNamespace(
        RatePlanCode="RPC_R", Status="OK",
        NonRefundable="false", PackageContract=None,
        Board=_make_board("SA", "Room Only"),
        Prices=_make_prices("EUR", "120.00"),
        HotelRooms=None, AdditionalElements=None, CancellationPolicy=None,
    )
    # (3) attribute absent → refundable=None (unknown)
    opt_unknown = SimpleNamespace(
        RatePlanCode="RPC_U", Status="OK",
        NonRefundable=None, PackageContract=None,
        Board=_make_board("SA", "Room Only"),
        Prices=_make_prices("EUR", "110.00"),
        HotelRooms=None, AdditionalElements=None, CancellationPolicy=None,
    )
    hr = SimpleNamespace(
        Code="JP_TRI", JPCode="JP_TRI", JPDCode="", DestinationZone="",
        BestDeal="false", HotelInfo=None,
        HotelOptions=SimpleNamespace(HotelOption=[opt_nonref, opt_ref, opt_unknown]),
    )
    response = SimpleNamespace(Results=SimpleNamespace(HotelResult=[hr]))

    hotels = serialize_hotel_avail(response)
    by_rpc = {h["rate_plan_code"]: h for h in hotels}
    assert by_rpc["RPC_NR"]["refundable"] is False
    assert by_rpc["RPC_NR"]["non_refundable"] is True
    assert by_rpc["RPC_R"]["refundable"] is True
    assert by_rpc["RPC_R"]["non_refundable"] is False
    assert by_rpc["RPC_U"]["refundable"] is None
    assert by_rpc["RPC_U"]["non_refundable"] is False  # bool_attr default


def test_serialize_hotel_avail_echoes_response_warnings_on_every_row():
    """Response-level ``Warnings`` (e.g. ``warnObsoleteJPCode`` when the
    client sent a synonym JPCode) must reach every candidate row so tools
    don't have to re-parse the raw response."""
    opt = SimpleNamespace(
        RatePlanCode="RPC_W", Status="OK",
        NonRefundable="false", PackageContract=None,
        Board=_make_board("SA", "Room Only"),
        Prices=_make_prices("EUR", "100.00"),
        HotelRooms=None, AdditionalElements=None, CancellationPolicy=None,
    )
    hr = SimpleNamespace(
        Code="JP_W", JPCode="JP_W", JPDCode="", DestinationZone="",
        BestDeal="false", HotelInfo=None,
        HotelOptions=SimpleNamespace(HotelOption=opt),
    )
    response = SimpleNamespace(
        Results=SimpleNamespace(HotelResult=[hr]),
        Warnings=SimpleNamespace(
            Warning=[
                SimpleNamespace(Code="warnObsoleteJPCode", Text="Use master code"),
                SimpleNamespace(Code="warnPriceChanged", Text="Rate moved"),
            ]
        ),
    )

    hotels = serialize_hotel_avail(response)
    assert len(hotels) == 1
    h = hotels[0]
    assert h["warning_codes"] == ["warnObsoleteJPCode", "warnPriceChanged"]
    assert h["warnings"] == [
        {"code": "warnObsoleteJPCode", "text": "Use master code"},
        {"code": "warnPriceChanged", "text": "Rate moved"},
    ]


# ---------------------------------------------------------------------------
# serialize_check_avail — §11.4 (nested Results/HotelResult/HotelOption)
# ---------------------------------------------------------------------------


def _make_check_avail_option(
    rate_plan_code: str,
    status: str,
    gross: str,
    currency: str = "EUR",
    board: tuple[str, str] = ("SA", "Room Only"),
) -> SimpleNamespace:
    return SimpleNamespace(
        RatePlanCode=rate_plan_code,
        Status=status,
        Board=_make_board(*board),
        Prices=_make_prices(currency, gross),
        HotelRooms=_make_hotel_rooms(["Double"]),
    )


def _make_check_avail_response(
    options: list[SimpleNamespace] | None,
    warnings: list[tuple[str, str]] | None = None,
) -> SimpleNamespace:
    """Build a CheckAvailRS response mirroring the official shape.

    ``options=None`` → no ``Results`` at all (supplier refused).
    ``options=[]``   → empty HotelOption list (supplier returned nothing).
    """
    if options is None:
        results = None
    else:
        hr = SimpleNamespace(
            HotelOptions=SimpleNamespace(HotelOption=options if len(options) != 1 else options[0])
        )
        results = SimpleNamespace(HotelResult=hr)

    warnings_node = None
    if warnings:
        warnings_node = SimpleNamespace(
            Warning=[SimpleNamespace(Code=code, Text=text) for code, text in warnings]
        )
    return SimpleNamespace(Results=results, Warnings=warnings_node)


def test_serialize_check_avail_picks_ok_option_with_lowest_price():
    """Multiple options: prefer Status=OK, among those pick the cheapest."""
    opts = [
        _make_check_avail_option("RPC_OK_HIGH", "OK", "300.00"),
        _make_check_avail_option("RPC_OK_LOW", "OK", "200.00"),
        _make_check_avail_option("RPC_RQ", "RQ", "100.00"),   # cheaper but RQ
    ]
    response = _make_check_avail_response(opts)

    result = serialize_check_avail(response)
    assert result["available"] is True
    assert result["status"] == "OK"
    assert result["rate_plan_code"] == "RPC_OK_LOW"     # NEW code from response
    assert result["total_price"] == "200.00"
    assert result["currency"] == "EUR"
    assert result["price_changed"] is False
    assert result["status_changed"] is False
    assert result["check_not_possible"] is False
    assert result["raw_options"] == 3
    assert result["board"]["name"] == "Room Only"


def test_serialize_check_avail_marks_price_changed_from_warnings():
    """Presence of ``warnPriceChanged`` in Warnings flips the price_changed
    flag even if the single option still has Status=OK (docs say the
    RatePlanCode itself is regenerated)."""
    opts = [_make_check_avail_option("RPC_NEW", "OK", "250.00")]
    response = _make_check_avail_response(
        opts,
        warnings=[("warnPriceChanged", "Price changed; use new RatePlanCode")],
    )
    result = serialize_check_avail(response)

    assert result["price_changed"] is True
    assert result["available"] is True
    assert result["rate_plan_code"] == "RPC_NEW"
    assert "warnPriceChanged" in result["warning_codes"]


def test_serialize_check_avail_rq_only_marks_unavailable():
    """No OK options → available=False, but still surface the RQ option for
    diagnostics (rate_plan_code + status=RQ)."""
    opts = [_make_check_avail_option("RPC_RQ", "RQ", "150.00")]
    response = _make_check_avail_response(opts)
    result = serialize_check_avail(response)
    assert result["available"] is False
    assert result["status"] == "RQ"
    assert result["rate_plan_code"] == "RPC_RQ"
    assert result["raw_options"] == 1


def test_serialize_check_avail_no_options_returns_empty_dict():
    """``Results`` missing entirely → every field at its zero-value, no
    AttributeError."""
    response = _make_check_avail_response(None)
    result = serialize_check_avail(response)
    assert result["available"] is False
    assert result["rate_plan_code"] == ""
    assert result["total_price"] == "0"
    assert result["rooms"] == []
    assert result["raw_options"] == 0


def test_serialize_check_avail_check_not_possible_warning_surfaces():
    """``warnCheckNotPossible`` with no options — client layer must treat as
    unavailable, but serializer just surfaces the flag."""
    response = _make_check_avail_response(
        [],  # empty HotelOption list
        warnings=[("warnCheckNotPossible", "Supplier could not verify")],
    )
    # _make_check_avail_response with [] → HotelOption is [] (empty list) —
    # ``iter_list`` treats that as 0 options.
    result = serialize_check_avail(response)
    assert result["check_not_possible"] is True
    assert result["available"] is False
    assert result["rate_plan_code"] == ""


def test_serialize_check_avail_status_changed_warning_surfaces():
    opts = [_make_check_avail_option("RPC_X", "OK", "100.00")]
    response = _make_check_avail_response(
        opts, warnings=[("warnStatusChanged", "Availability changed")]
    )
    result = serialize_check_avail(response)
    # Serializer only reports the flag; client layer decides to raise.
    assert result["status_changed"] is True
    assert result["available"] is True  # option itself is still OK


def test_serialize_check_avail_tolerates_single_option_not_wrapped():
    """Zeep returns a bare node for a single HotelOption — must still work."""
    response = _make_check_avail_response(
        [_make_check_avail_option("RPC_SOLO", "OK", "99.99")]
    )
    result = serialize_check_avail(response)
    assert result["rate_plan_code"] == "RPC_SOLO"
    assert result["total_price"] == "99.99"


# ---------------------------------------------------------------------------
# serialize_booking_rules — §11.5 (nested Results/HotelResult/HotelOption)
# ---------------------------------------------------------------------------


def _make_booking_code(value: str, expires: str) -> SimpleNamespace:
    """Mirror the zeep shape: text is on ``_value_1`` and ``@ExpirationDate``
    is a sibling attribute."""
    return SimpleNamespace(_value_1=value, ExpirationDate=expires)


def _make_hotel_content_short(
    code: str = "JP046300",
    name: str = "APARTAMENTOS ALLSUN PIL-LARI PLAYA",
    category_type: str = "3est",
    category_name: str = "3 Stars",
    jpdcode: str = "JPD086855",
    street: str = "Calle Marbella 24",
) -> SimpleNamespace:
    return SimpleNamespace(
        Code=code,
        HotelName=name,
        HotelCategory=SimpleNamespace(Type=category_type, _value_1=category_name),
        HotelType=SimpleNamespace(Type="GEN", _value_1="General"),
        Zone=SimpleNamespace(JPDCode=jpdcode, Code="49435"),
        Address=SimpleNamespace(
            Address=street, Latitude="39.564713", Longitude="2.627979",
        ),
    )


def _make_cancellation_policy() -> SimpleNamespace:
    """Two-rule policy, matching the real example at lines 2701-2708."""
    rules = [
        SimpleNamespace(
            **{
                "From": "0", "To": "3",
                "DateFrom": "2019-11-17", "DateFromHour": "00:00",
                "DateTo": "2019-11-21", "DateToHour": "00:00",
                "Type": "V", "FixedPrice": "0", "PercentPrice": "100",
                "Nights": "0", "ApplicationTypeNights": "Average",
            }
        ),
        SimpleNamespace(
            **{
                "From": "4", "To": "7",
                "DateFrom": "2019-11-13", "DateFromHour": "00:00",
                "DateTo": "2019-11-17", "DateToHour": "00:00",
                "Type": "V", "FixedPrice": "0", "PercentPrice": "25",
                "Nights": "0", "ApplicationTypeNights": "Average",
            }
        ),
    ]
    return SimpleNamespace(
        CurrencyCode="EUR",
        Description="Cancelling 100% then 25% then 0%",
        FirstDayCostCancellation=SimpleNamespace(Hour="00:00", _value_1="2019-11-13"),
        PolicyRules=SimpleNamespace(Rule=rules),
    )


def _make_required_fields() -> SimpleNamespace:
    """Mirror the real HotelRequiredFields template (lines 2650-2700):
    two pax (one with full contact info, one with only age), a holder
    pointing at pax 1, and an Elements/HotelElement with BookingCode +
    HotelBookingInfo(Start/End/HotelCode)."""
    pax1 = SimpleNamespace(
        IdPax="1",
        Name="Holder Name", Surname="Holder Surname",
        PhoneNumbers=SimpleNamespace(PhoneNumber="000000000"),
        Address="Address", City="City", Country="Country",
        PostalCode="00000", Age="30",
    )
    pax2 = SimpleNamespace(IdPax="2", Age="30")
    holder = SimpleNamespace(RelPax=SimpleNamespace(IdPax="1"))
    hotel_element = SimpleNamespace(
        BookingCode="ya79dM4dS6R6...",
        HotelBookingInfo=SimpleNamespace(
            Start="2019-11-20", End="2019-11-22",
            HotelCode="JP046300",
        ),
    )
    return SimpleNamespace(
        HotelBooking=SimpleNamespace(
            Paxes=SimpleNamespace(Pax=[pax1, pax2]),
            Holder=holder,
            Elements=SimpleNamespace(HotelElement=hotel_element),
        )
    )


def _make_booking_rules_option(
    *,
    status: str = "OK",
    rate_plan_code: str = "RPC_NEW",
    booking_code: str = "BC_ABC123",
    expires: str = "2019-10-03T09:46:30+02:00",
    gross: str = "1003.57",
    currency: str = "EUR",
    include_optional_elements: bool = True,
    include_cancellation: bool = True,
    include_hotel_content: bool = True,
) -> SimpleNamespace:
    price_info = SimpleNamespace(
        Board=_make_board("AD", "Bed & Breakfast"),
        HotelRooms=_make_hotel_rooms(["Single", "Double"]),
        Prices=_make_prices(currency, gross),
        AdditionalElements=SimpleNamespace(
            HotelOffers=SimpleNamespace(
                HotelOffer=[SimpleNamespace(
                    Code="843", Category="GEN", Begin="", End="",
                    RoomCategory="", Name="5% discount",
                    Description="Early bird",
                )]
            ),
            HotelSupplements=SimpleNamespace(
                HotelSupplement=[SimpleNamespace(
                    Code="SUP1", Name="Late checkout",
                    Description="Until 18:00", DirectPayment="false",
                )]
            ),
        ),
        HotelContent=_make_hotel_content_short() if include_hotel_content else None,
    )
    optional = None
    if include_optional_elements:
        optional = SimpleNamespace(
            Comments=SimpleNamespace(
                Comment=[
                    SimpleNamespace(Type="HOT", _value_1="Important hotel info"),
                    SimpleNamespace(Type="GEN", _value_1="General info"),
                ]
            ),
            HotelSupplements=SimpleNamespace(
                HotelSupplement=[SimpleNamespace(
                    Code="OPT1", Name="Airport pickup",
                    Description="Per car", DirectPayment="true",
                    RatePlanCode="RPC_SUP",
                )]
            ),
            Preferences=SimpleNamespace(
                Preference=[SimpleNamespace(
                    Code="HIFLOOR",
                    Description=SimpleNamespace(_value_1="High floor"),
                )]
            ),
            AllowedCreditCards=SimpleNamespace(
                CreditCard=[SimpleNamespace(Code="VISA", _value_1="Visa")]
            ),
        )
    return SimpleNamespace(
        Status=status,
        RatePlanCode=rate_plan_code,
        BookingCode=_make_booking_code(booking_code, expires),
        HotelRequiredFields=_make_required_fields(),
        CancellationPolicy=_make_cancellation_policy() if include_cancellation else None,
        PriceInformation=price_info,
        OptionalElements=optional,
    )


def _make_booking_rules_response(
    options: list[SimpleNamespace] | None,
    warnings: list[tuple[str, str]] | None = None,
) -> SimpleNamespace:
    if options is None:
        results = None
    else:
        hr = SimpleNamespace(
            HotelOptions=SimpleNamespace(HotelOption=options if len(options) != 1 else options[0])
        )
        results = SimpleNamespace(HotelResult=hr)
    warnings_node = None
    if warnings:
        warnings_node = SimpleNamespace(
            Warning=[SimpleNamespace(Code=c, Text=t) for c, t in warnings]
        )
    return SimpleNamespace(Results=results, Warnings=warnings_node)


def test_serialize_booking_rules_extracts_booking_code_and_expiry():
    """The critical handle: ``BookingCode`` + ``@ExpirationDate``. Without
    these the agent cannot proceed to HotelBooking (docs §HotelBookingRules
    Response, 10-min TTL)."""
    opt = _make_booking_rules_option(
        booking_code="ya79dM4dS6R6...", expires="2019-10-03T09:46:30+02:00",
    )
    response = _make_booking_rules_response([opt])

    rules = serialize_booking_rules(response)

    assert rules["booking_code"] == "ya79dM4dS6R6..."
    assert rules["booking_code_expires_at"] == "2019-10-03T09:46:30+02:00"
    assert rules["valid"] is True
    assert rules["status"] == "OK"
    # Docs: HotelOption/@RatePlanCode is the updated code; always prefer it.
    assert rules["rate_plan_code"] == "RPC_NEW"


def test_serialize_booking_rules_surfaces_prices_and_board():
    opt = _make_booking_rules_option(gross="1003.57", currency="EUR")
    rules = serialize_booking_rules(_make_booking_rules_response([opt]))

    assert rules["total_price"] == "1003.57"
    assert rules["nett_price"] == "1003.57"
    assert rules["currency"] == "EUR"
    assert rules["board"] == {"type": "AD", "name": "Bed & Breakfast"}
    assert len(rules["rooms"]) == 2


def test_serialize_booking_rules_parses_cancellation_policy():
    opt = _make_booking_rules_option()
    rules = serialize_booking_rules(_make_booking_rules_response([opt]))

    cp = rules["cancellation"]
    assert cp is not None
    assert cp["currency"] == "EUR"
    assert cp["first_day_cost_date"] == "2019-11-13"
    assert cp["first_day_cost_hour"] == "00:00"
    assert len(cp["rules"]) == 2
    # Docs: attribute is @PercentPrice, not @Percent. Bug fix in §11.3.
    assert cp["rules"][0]["percent_price"] == "100"
    assert cp["rules"][1]["from_days"] == 4
    assert cp["rules"][1]["to_days"] == 7
    # Legacy flat string still populated for the existing agent tool.
    assert "Cancelling" in rules["cancellation_policy"]


def test_serialize_booking_rules_surfaces_offers_and_supplements():
    """Offers & supplements come from two distinct places: the price
    bundle (``PriceInformation/AdditionalElements``) and the optional
    add-ons (``OptionalElements/HotelSupplements``). Both must be
    surfaced separately — one is already included in the total, the
    other requires a second BookingRules round-trip to add."""
    opt = _make_booking_rules_option()
    rules = serialize_booking_rules(_make_booking_rules_response([opt]))

    assert len(rules["offers"]) == 1
    assert rules["offers"][0]["code"] == "843"
    assert len(rules["supplements"]) == 1
    assert rules["supplements"][0]["code"] == "SUP1"
    assert len(rules["optional_supplements"]) == 1
    assert rules["optional_supplements"][0]["code"] == "OPT1"


def test_serialize_booking_rules_extracts_hotel_content():
    """``PriceInformation/HotelContent`` is the trimmed shape (HotelName,
    HotelCategory, Address/Address, Zone/@JPDCode)."""
    opt = _make_booking_rules_option()
    rules = serialize_booking_rules(_make_booking_rules_response([opt]))

    hc = rules["hotel_content"]
    assert hc["code"] == "JP046300"
    assert hc["name"] == "APARTAMENTOS ALLSUN PIL-LARI PLAYA"
    assert hc["category"] == "3 Stars"
    assert hc["category_type"] == "3est"
    assert hc["type"] == "General"
    assert hc["jpdcode"] == "JPD086855"
    # The real XML nests ``<Address><Address>Calle Marbella 24</Address></Address>``
    # — parser must walk the inner ``Address`` element.
    assert hc["address"] == "Calle Marbella 24"


def test_serialize_booking_rules_required_fields_captures_pax_template():
    """``HotelRequiredFields`` is a TEMPLATE of which fields are mandatory
    per-pax. The HotelBooking builder (§11.8) uses this to validate/collect
    guest info — missing fields = we must ask the user."""
    opt = _make_booking_rules_option()
    rules = serialize_booking_rules(_make_booking_rules_response([opt]))

    rf = rules["required_fields"]
    assert rf["has_hotel_element"] is True
    assert rf["has_booking_code"] is True
    assert rf["hotel_codes"] == ["JP046300"]
    assert rf["check_in"] == "2019-11-20"
    assert rf["check_out"] == "2019-11-22"
    assert rf["holder"]["rel_pax_ids"] == ["1"]

    by_id = {p["id_pax"]: p for p in rf["paxes"]}
    # Pax 1 has full contact info; every child element surfaces as a field.
    assert "Name" in by_id["1"]["fields"]
    assert "PhoneNumbers" in by_id["1"]["fields"]
    assert "Address" in by_id["1"]["fields"]
    assert "Age" in by_id["1"]["fields"]
    # Pax 2 only has Age — no other fields must be required.
    assert by_id["2"]["fields"] == ["Age"]


def test_serialize_booking_rules_extracts_comments_and_preferences():
    opt = _make_booking_rules_option()
    rules = serialize_booking_rules(_make_booking_rules_response([opt]))

    assert len(rules["comments"]) == 2
    assert rules["comments"][0] == {"type": "HOT", "text": "Important hotel info"}
    # Legacy ``remarks`` joins all comments — keeps the existing agent tool
    # rendering meaningful content.
    assert "Important hotel info" in rules["remarks"]
    assert "General info" in rules["remarks"]

    assert rules["preferences"] == [{"code": "HIFLOOR", "description": "High floor"}]
    assert rules["allowed_credit_cards"] == [{"code": "VISA", "name": "Visa"}]


def test_serialize_booking_rules_flags_price_changed_from_warnings():
    """When Juniper regenerates the price (and RatePlanCode) it emits a
    ``warnPriceChanged`` warning. The client layer (§11.6) will raise
    ``PriceChangedError`` — the serializer only surfaces the flag + the
    new rate plan code."""
    opt = _make_booking_rules_option(rate_plan_code="RPC_UPDATED", gross="1100.00")
    response = _make_booking_rules_response(
        [opt], warnings=[("warnPriceChanged", "Price changed")]
    )
    rules = serialize_booking_rules(response)

    assert rules["price_changed"] is True
    assert rules["rate_plan_code"] == "RPC_UPDATED"
    assert rules["total_price"] == "1100.00"
    assert "warnPriceChanged" in rules["warning_codes"]


def test_serialize_booking_rules_flags_status_changed():
    opt = _make_booking_rules_option()
    response = _make_booking_rules_response(
        [opt], warnings=[("warnStatusChanged", "Availability changed")]
    )
    rules = serialize_booking_rules(response)
    assert rules["status_changed"] is True


def test_serialize_booking_rules_rq_option_marks_invalid():
    """Per docs the @Status may be RQ (on-request) — HotelBookingRules
    must not treat this as valid; the BookingCode would then be useless
    for HotelBooking."""
    opt = _make_booking_rules_option(status="RQ")
    rules = serialize_booking_rules(_make_booking_rules_response([opt]))
    assert rules["valid"] is False
    assert rules["status"] == "RQ"


def test_serialize_booking_rules_empty_response():
    """No ``Results`` at all — every field at its zero-value, no
    AttributeError. Client layer decides whether to raise based on the
    warnings."""
    rules = serialize_booking_rules(_make_booking_rules_response(None))
    assert rules["valid"] is False
    assert rules["status"] == ""
    assert rules["booking_code"] == ""
    assert rules["booking_code_expires_at"] == ""
    assert rules["rooms"] == []
    assert rules["offers"] == []
    assert rules["optional_supplements"] == []
    assert rules["comments"] == []
    assert rules["hotel_content"]["code"] == ""
    assert rules["required_fields"]["paxes"] == []


def test_serialize_booking_rules_tolerates_missing_optional_elements():
    """``OptionalElements`` and ``CancellationPolicy`` are both marked
    ``Y`` (optional) in the docs — serializer must not crash without them."""
    opt = _make_booking_rules_option(
        include_optional_elements=False,
        include_cancellation=False,
        include_hotel_content=False,
    )
    rules = serialize_booking_rules(_make_booking_rules_response([opt]))

    assert rules["valid"] is True
    assert rules["comments"] == []
    assert rules["preferences"] == []
    assert rules["allowed_credit_cards"] == []
    assert rules["cancellation"] is None
    assert rules["cancellation_policy"] == ""
    assert rules["hotel_content"]["code"] == ""
    assert rules["remarks"] == ""


def test_serialize_booking_rules_tolerates_single_option_not_wrapped():
    """Zeep returns a bare node when there's only one HotelOption."""
    opt = _make_booking_rules_option(rate_plan_code="RPC_SOLO")
    response = _make_booking_rules_response([opt])  # helper unwraps to bare node
    rules = serialize_booking_rules(response)
    assert rules["rate_plan_code"] == "RPC_SOLO"
    assert rules["booking_code"] == "BC_ABC123"


def test_serialize_booking_rules_booking_code_as_bare_string():
    """Some suppliers/responses place BookingCode as a plain string (no
    ExpirationDate attribute). Parser must still recover the value."""
    opt = _make_booking_rules_option()
    opt.BookingCode = "BARE_STRING_BOOKING_CODE"
    rules = serialize_booking_rules(_make_booking_rules_response([opt]))
    assert rules["booking_code"] == "BARE_STRING_BOOKING_CODE"
    assert rules["booking_code_expires_at"] == ""


def test_serialize_booking_rules_picks_ok_when_rq_comes_first():
    """Supplier may return a mix of OK and RQ options — prefer OK."""
    rq_opt = _make_booking_rules_option(status="RQ", rate_plan_code="RPC_RQ")
    ok_opt = _make_booking_rules_option(status="OK", rate_plan_code="RPC_OK")
    response = _make_booking_rules_response([rq_opt, ok_opt])
    rules = serialize_booking_rules(response)
    assert rules["valid"] is True
    assert rules["rate_plan_code"] == "RPC_OK"
    assert rules["raw_options"] == 2


# ---------------------------------------------------------------------------
# serialize_booking / serialize_read_booking — §11.7
# (Reservations/Reservation/Items/HotelItem per docs lines 3478-3726)
# ---------------------------------------------------------------------------


def _make_pax(
    id_pax: str,
    name: str,
    surname: str,
    *,
    email: str = "",
    age: str = "",
    phone: str = "",
    document: tuple[str, str] | None = None,
    nationality: str = "",
    city: str = "",
    country: str = "",
) -> SimpleNamespace:
    """Mirror the zeep shape of ``Pax``. Fields omitted from the call are
    left as ``None`` so parsers can distinguish absent from empty."""
    phone_list = (
        [SimpleNamespace(Type="TFN", _value_1=phone)] if phone else []
    )
    doc_node = (
        SimpleNamespace(Type=document[0], _value_1=document[1]) if document else None
    )
    return SimpleNamespace(
        IdPax=id_pax,
        Name=SimpleNamespace(_value_1=name),
        Surname=SimpleNamespace(_value_1=surname),
        Age=SimpleNamespace(_value_1=age) if age else None,
        Email=SimpleNamespace(_value_1=email) if email else None,
        Address=None,
        City=SimpleNamespace(_value_1=city) if city else None,
        Country=SimpleNamespace(_value_1=country) if country else None,
        PostalCode=None,
        Nationality=SimpleNamespace(_value_1=nationality) if nationality else None,
        Document=doc_node,
        PhoneNumbers=SimpleNamespace(PhoneNumber=phone_list) if phone_list else None,
    )


def _make_hotel_item(
    *,
    item_id: str = "148012",
    status: str = "OK",
    start: str = "2019-11-20",
    end: str = "2019-11-22",
    gross: str = "1003.57",
    currency: str = "EUR",
    hotel_code: str = "JP046300",
    hotel_name: str = "APARTAMENTOS ALLSUN PIL-LARI PLAYA",
    category_type: str = "3est",
    category_name: str = "3 Stars",
    address: str = "Calle Marbella 24",
    board_code: str = "AD",
    board_name: str = "Bed & Breakfast",
    include_external_info: bool = True,
    include_cancellation: bool = True,
    include_additional: bool = True,
) -> SimpleNamespace:
    total_fix = SimpleNamespace(
        Gross=gross, Nett=gross,
        Service=SimpleNamespace(Amount="912.34"),
        ServiceTaxes=SimpleNamespace(Included="false", Amount="91.23"),
    )
    prices = SimpleNamespace(
        Price=[SimpleNamespace(Type="S", Currency=currency, TotalFixAmounts=total_fix)]
    )

    external_info = None
    if include_external_info:
        external_info = SimpleNamespace(
            Supplier=SimpleNamespace(Code="SUP-42", IntCode=None),
            ExternalLocator=SimpleNamespace(_value_1="HTL-CONF-XYZ"),
            ExternalCancellationLocator=None,
            HotelConfirmationNumber=SimpleNamespace(_value_1="HCN-123"),
            ExternalTransactionIDS=SimpleNamespace(
                ExternalTransactionID=[
                    SimpleNamespace(Type="CONFIRM", Value="txn-conf-1"),
                ]
            ),
        )

    cancellation = None
    if include_cancellation:
        cancellation = SimpleNamespace(
            CurrencyCode="EUR",
            Description=SimpleNamespace(
                _value_1="* Cancelling from 17/11 at 00:00 to 21/11 at 00:00: 100% of expenses"
            ),
            FirstDayCostCancellation=SimpleNamespace(_value_1="2019-11-13", Hour="00:00"),
            PolicyRules=SimpleNamespace(Rule=[
                SimpleNamespace(
                    **{
                        "From": "0", "To": "3",
                        "DateFrom": "2019-11-17", "DateFromHour": "00:00",
                        "DateTo": "2019-11-21", "DateToHour": "00:00",
                        "Type": "V", "FixedPrice": "0", "PercentPrice": "100",
                        "Nights": "0", "ApplicationTypeNights": "Average",
                    }
                ),
            ]),
        )

    additional = None
    if include_additional:
        additional = SimpleNamespace(
            HotelOffers=SimpleNamespace(HotelOffer=[
                SimpleNamespace(
                    Code="843", Type="M",
                    Name=SimpleNamespace(_value_1="[2019] 5% discount"),
                    Description=SimpleNamespace(_value_1="Offer description"),
                )
            ]),
            HotelSupplements=None,
        )

    return SimpleNamespace(
        ItemId=item_id,
        Status=status,
        Start=start,
        End=end,
        ExternalInfo=external_info,
        TaxReference=None,
        Prices=prices,
        CancellationPolicy=cancellation,
        Comments=SimpleNamespace(Comment=[
            SimpleNamespace(Type="ELE", _value_1="SPECIFIC HOTEL/SUPPLIER COMMENTS"),
        ]),
        HotelInfo=SimpleNamespace(
            Code=hotel_code,
            JPCode=hotel_code,
            JPDCode="JPD000004",
            DestinationZone="2",
            Name=SimpleNamespace(_value_1=hotel_name),
            HotelCategory=SimpleNamespace(Type=category_type, _value_1=category_name),
            Address=SimpleNamespace(_value_1=address),
        ),
        Board=SimpleNamespace(Type=board_code, _value_1=board_name),
        HotelRooms=SimpleNamespace(HotelRoom=[
            SimpleNamespace(
                Source="1", Code=None,
                Name=SimpleNamespace(_value_1="Single"),
                Description=None,
                RoomCategory=SimpleNamespace(Type="1", _value_1="Category 1"),
                RelPaxes=SimpleNamespace(RelPax=[SimpleNamespace(IdPax="1")]),
            ),
        ]),
        AdditionalElements=additional,
    )


def _make_reservation(
    *,
    locator: str = "TQ1TBG",
    status: str = "PAG",
    external_ref: str = "YOUR_OWN_REFERENCE_123",
    holder_id: str = "4",
    hotel_item: SimpleNamespace | None = None,
    paxes: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    default_paxes = paxes if paxes is not None else [
        _make_pax("1", "Holder", "Name", email="holder@yourdomain.com", age="50", phone="+34600555999"),
        _make_pax("2", "Second", "Pax", age="30"),
        _make_pax("3", "Child", "Pax", age="8"),
        # Holder is cloned into a separate Pax per docs line 3492.
        _make_pax(
            holder_id, "Holder", "Name",
            email="holder@yourdomain.com", age="50",
            phone="+34600555999",
            document=("DNI", "43258752A"),
            nationality="ES",
        ),
    ]
    return SimpleNamespace(
        Locator=locator,
        Status=status,
        Language="en",
        PaymentDestination=None,
        ExternalBookingReference=SimpleNamespace(_value_1=external_ref),
        Holder=SimpleNamespace(RelPax=SimpleNamespace(IdPax=holder_id)),
        Paxes=SimpleNamespace(Pax=default_paxes),
        Comments=SimpleNamespace(Comment=[
            SimpleNamespace(Type="RES", _value_1="GENERAL BOOKING COMMENTS"),
        ]),
        AgenciesData=SimpleNamespace(AgencyData=[
            SimpleNamespace(
                ReferencedAgency=SimpleNamespace(_value_1="false"),
                AgencyCode=SimpleNamespace(_value_1="123"),
                AgencyName=SimpleNamespace(_value_1="Test XML Juniper"),
                AgencyHandledBy=SimpleNamespace(_value_1="XML Agent"),
                AgencyEmail=SimpleNamespace(_value_1="noreply@ejuniper.com"),
                AgencyReference=SimpleNamespace(_value_1=external_ref),
            ),
        ]),
        Items=SimpleNamespace(HotelItem=[hotel_item or _make_hotel_item()]),
    )


def _make_booking_response(
    reservations: list[SimpleNamespace] | None,
    warnings: list[tuple[str, str]] | None = None,
) -> SimpleNamespace:
    """Build a BookingRS mirror. ``reservations=None`` → no ``Reservations``
    node at all; ``[]`` → empty container; single item → unwrapped by zeep."""
    if reservations is None:
        results = None
    elif len(reservations) == 1:
        results = SimpleNamespace(Reservation=reservations[0])
    else:
        results = SimpleNamespace(Reservation=reservations)
    warnings_node = (
        SimpleNamespace(Warning=[SimpleNamespace(Code=c, Text=t) for c, t in warnings])
        if warnings else None
    )
    return SimpleNamespace(Reservations=results, Warnings=warnings_node)


# ---------------- Happy path ----------------


def test_serialize_booking_full_confirmed_response():
    """Full official BookingRS sample (docs lines 3596-3726) round-trips
    through the serializer with all legacy flat keys + structured fields
    populated."""
    response = _make_booking_response([_make_reservation()])
    booking = serialize_booking(response)

    # Legacy flat keys — what agent/tools/book_hotel.py consumes.
    assert booking["booking_id"] == "TQ1TBG"
    assert booking["status"] == "confirmed"
    assert booking["hotel_name"] == "APARTAMENTOS ALLSUN PIL-LARI PLAYA"
    assert booking["check_in"] == "2019-11-20"
    assert booking["check_out"] == "2019-11-22"
    assert booking["total_price"] == "1003.57"
    assert booking["currency"] == "EUR"
    assert booking["guest_name"] == "Holder Name"

    # Structured identifiers.
    assert booking["raw_status"] == "PAG"
    assert booking["status_semantic"] == "confirmed"
    assert booking["external_booking_reference"] == "YOUR_OWN_REFERENCE_123"
    assert booking["raw_reservations"] == 1

    # Holder resolved to the matching Pax.
    holder = booking["holder"]
    assert holder["rel_pax_id"] == "4"
    assert holder["pax"]["name"] == "Holder"
    assert holder["pax"]["email"] == "holder@yourdomain.com"
    assert holder["pax"]["document"] == {"type": "DNI", "value": "43258752A"}
    assert holder["pax"]["phones"] == [{"type": "TFN", "number": "+34600555999"}]

    # Paxes.
    assert [p["id_pax"] for p in booking["paxes"]] == ["1", "2", "3", "4"]

    # Comments + agencies.
    assert booking["comments"] == [{"type": "RES", "text": "GENERAL BOOKING COMMENTS"}]
    assert len(booking["agencies_data"]) == 1
    assert booking["agencies_data"][0]["agency_name"] == "Test XML Juniper"
    assert booking["agencies_data"][0]["referenced_agency"] is False


def test_serialize_booking_hotel_item_structured():
    """The full HotelItem[0] carries supplier locators, category, rooms,
    board, prices, cancellation, and offers."""
    response = _make_booking_response([_make_reservation()])
    item = serialize_booking(response)["hotel_item"]

    assert item["item_id"] == "148012"
    assert item["status"] == "OK"
    assert item["check_in"] == "2019-11-20"
    assert item["check_out"] == "2019-11-22"

    # HotelInfo has the identifier triplet + address.
    assert item["hotel_info"]["jpcode"] == "JP046300"
    assert item["hotel_info"]["jpdcode"] == "JPD000004"
    assert item["hotel_info"]["destination_zone"] == "2"
    assert item["hotel_info"]["category"] == "3 Stars"
    assert item["hotel_info"]["address"] == "Calle Marbella 24"

    # Board / Rooms.
    assert item["board"]["type"] == "AD"
    assert item["board"]["name"] == "Bed & Breakfast"
    assert item["rooms"][0]["rel_pax_ids"] == ["1"]
    assert item["rooms"][0]["name"] == "Single"

    # Prices.
    assert item["prices"]["total_price"] == "1003.57"
    assert item["prices"]["currency"] == "EUR"

    # Cancellation + offers.
    assert item["cancellation"]["currency"] == "EUR"
    assert item["offers"][0]["code"] == "843"
    assert item["offers"][0]["name"] == "[2019] 5% discount"

    # ExternalInfo surfaces the supplier locator so ops can correlate
    # with the hotel-chain's reservation number.
    assert item["external_info"]["supplier_code"] == "SUP-42"
    assert item["external_info"]["external_locator"] == "HTL-CONF-XYZ"
    assert item["external_info"]["hotel_confirmation_number"] == "HCN-123"
    assert item["external_info"]["transaction_ids"] == [
        {"type": "CONFIRM", "value": "txn-conf-1"},
    ]


# ---------------- Status normalisation ----------------


def test_serialize_booking_status_normalisation_confirmed_paid():
    """PAG → confirmed (paid)."""
    response = _make_booking_response([_make_reservation(status="PAG")])
    booking = serialize_booking(response)
    assert booking["raw_status"] == "PAG"
    assert booking["status_semantic"] == "confirmed"
    assert booking["status"] == "confirmed"


def test_serialize_booking_status_normalisation_confirmed_unpaid():
    """CON → confirmed (unpaid)."""
    response = _make_booking_response([_make_reservation(status="CON")])
    assert serialize_booking(response)["status_semantic"] == "confirmed"


def test_serialize_booking_status_normalisation_cancelled_cac_and_can():
    """Both CAC and CAN map to cancelled per docs line 3484 (suppliers use
    either spelling)."""
    for raw in ("CAC", "CAN"):
        response = _make_booking_response([_make_reservation(status=raw)])
        booking = serialize_booking(response)
        assert booking["raw_status"] == raw
        assert booking["status_semantic"] == "cancelled"
        assert booking["status"] == "cancelled"


def test_serialize_booking_status_normalisation_pending():
    """PRE / PDI / TAR → pending."""
    for raw in ("PRE", "PDI", "TAR"):
        response = _make_booking_response([_make_reservation(status=raw)])
        assert serialize_booking(response)["status_semantic"] == "pending"


def test_serialize_booking_status_normalisation_quotation():
    """QUO → quotation (distinct from pending — supplier requires WS
    payment before confirmation)."""
    response = _make_booking_response([_make_reservation(status="QUO")])
    assert serialize_booking(response)["status_semantic"] == "quotation"


def test_serialize_booking_status_normalisation_unknown_falls_back():
    """Unknown status code → ``unknown`` semantic, raw preserved. Prevents
    the old bug where any unrecognised code silently aliased to
    'confirmed'."""
    response = _make_booking_response([_make_reservation(status="ZZZ")])
    booking = serialize_booking(response)
    assert booking["raw_status"] == "ZZZ"
    assert booking["status_semantic"] == "unknown"
    # The ``status`` legacy key falls back to the semantic value which is
    # "unknown" — NOT "confirmed", NOT raw.
    assert booking["status"] == "unknown"


# ---------------- Edge cases ----------------


def test_serialize_booking_empty_response_returns_safe_defaults():
    """Missing ``Reservations`` (shouldn't happen in practice but might on
    fault responses): return an empty-but-shaped dict so callers don't
    KeyError."""
    response = _make_booking_response(None, warnings=[("warnSomething", "x")])
    booking = serialize_booking(response)
    assert booking["booking_id"] == ""
    assert booking["status"] == ""
    assert booking["hotel_name"] == ""
    assert booking["total_price"] == "0"
    assert booking["currency"] == "EUR"
    assert booking["paxes"] == []
    assert booking["hotel_item"] == {}
    # Warnings still captured so the caller can still diagnose.
    assert booking["warning_codes"] == ["warnSomething"]


def test_serialize_booking_single_reservation_unwrapped_by_zeep():
    """Zeep returns ``Reservation`` as a bare node when only one is
    present — serializer must detect that case."""
    reservation = _make_reservation()
    # Simulate zeep unwrapping: Reservations.Reservation is a single node, not a list.
    response = SimpleNamespace(
        Reservations=SimpleNamespace(Reservation=reservation),
        Warnings=None,
    )
    booking = serialize_booking(response)
    assert booking["booking_id"] == "TQ1TBG"
    assert booking["raw_reservations"] == 1


def test_serialize_booking_multi_reservation_returns_first_and_records_total():
    """Multi-reservation responses (rare): first wins, ``raw_reservations``
    carries the total for diagnostics."""
    response = _make_booking_response([
        _make_reservation(locator="FIRST"),
        _make_reservation(locator="SECOND"),
    ])
    booking = serialize_booking(response)
    assert booking["booking_id"] == "FIRST"
    assert booking["raw_reservations"] == 2


def test_serialize_booking_fallback_guest_name_when_no_holder():
    """No Holder node → fall back to first Pax's name so ``guest_name``
    is never empty when the booking has at least one pax."""
    reservation = _make_reservation()
    reservation.Holder = None
    response = _make_booking_response([reservation])
    booking = serialize_booking(response)
    assert booking["guest_name"] == "Holder Name"
    assert booking["holder"]["rel_pax_id"] == ""
    assert booking["holder"]["pax"] is None


def test_serialize_booking_cancellation_response_maps_status():
    """CancelBooking response has ``Reservation/@Status=CAC`` + a
    ``warnCancelled*`` warning. Same serializer handles it (docs lines
    3976-4025)."""
    response = _make_booking_response(
        [_make_reservation(status="CAC")],
        warnings=[("warnCancelledAndCancellationCostRetrieved", "Reservation was cancelled.")],
    )
    booking = serialize_booking(response)
    assert booking["status_semantic"] == "cancelled"
    assert "warnCancelledAndCancellationCostRetrieved" in booking["warning_codes"]


# ---------------- serialize_read_booking delegation ----------------


def test_serialize_read_booking_delegates_to_serialize_booking():
    """Per docs line 3758 — ReadBookingResponse shape is IDENTICAL to
    HotelBookingResponse. Serializer must produce the exact same dict to
    avoid subtle field-name drift between the two endpoints."""
    response = _make_booking_response([_make_reservation(locator="READ-1")])
    assert serialize_read_booking(response) == serialize_booking(response)


def test_serialize_read_booking_handles_missing_fields_like_serialize_booking():
    """Empty response parity between the two entry points."""
    response = _make_booking_response(None)
    assert serialize_read_booking(response) == serialize_booking(response)


# ---------------- HotelItem extraction edge cases ----------------


def test_serialize_booking_hotel_item_tolerates_missing_optional_blocks():
    """``ExternalInfo`` / ``CancellationPolicy`` / ``AdditionalElements``
    are all optional per docs (Y) — their absence must not crash the
    serializer."""
    item = _make_hotel_item(
        include_external_info=False,
        include_cancellation=False,
        include_additional=False,
    )
    reservation = _make_reservation(hotel_item=item)
    response = _make_booking_response([reservation])
    booking = serialize_booking(response)

    assert booking["hotel_item"]["external_info"]["external_locator"] == ""
    assert booking["hotel_item"]["cancellation"] is None
    assert booking["hotel_item"]["offers"] == []
    # Legacy fields still work.
    assert booking["hotel_name"] == "APARTAMENTOS ALLSUN PIL-LARI PLAYA"
    assert booking["total_price"] == "1003.57"


def test_serialize_booking_hotel_item_status_ca_on_cancellation():
    """Item @Status transitions from OK to CA on cancellation (docs line
    3516). Serializer preserves the raw value in ``hotel_item.status``."""
    item = _make_hotel_item(status="CA")
    response = _make_booking_response([_make_reservation(status="CAC", hotel_item=item)])
    booking = serialize_booking(response)
    assert booking["hotel_item"]["status"] == "CA"
    assert booking["status_semantic"] == "cancelled"
