"""Serialize Juniper SOAP responses to Python dicts for LLM consumption and API output.

Juniper's availability response is **deeply nested** (per official docs
`doc/juniper-hotel-api.md` §HotelAvail Response and
``uploads/hotel-api-0.md`` lines 1474-1644):

    AvailabilityRS
    └── Results
        └── HotelResult(list)        # one per hotel
            ├── @JPCode / @Code / @JPDCode / @DestinationZone / @BestDeal
            ├── HotelInfo            # only if AdvancedOptions/ShowHotelInfo=true
            │   ├── Name / Address / Latitude / Longitude
            │   └── HotelCategory(@Type, text="3 Stars")
            └── HotelOptions
                └── HotelOption(list) # one per (board × rooms) combination
                    ├── @RatePlanCode / @Status (OK|RQ) / @NonRefundable
                    ├── Board(@Type, text)
                    ├── Prices/Price(@Currency)/TotalFixAmounts(@Gross, @Nett)
                    ├── HotelRooms/HotelRoom(list)
                    └── AdditionalElements (HotelOffers / HotelSupplements)

``serialize_hotel_avail`` expands each **HotelResult × HotelOption** pair into
a single flat dict — every combination becomes its own candidate for
downstream LLM presentation, HotelCheckAvail, HotelBookingRules, etc.

All low-level zeep helpers and sub-structure parsers live in
``_parsers.py`` (extracted in §11.3). This module only wires them together
into the operation-specific serializers.
"""

from typing import Any

from juniper_ai.app.juniper._parsers import (
    attr,
    bool_attr,
    iter_list,
    normalise_reservation_status,
    parse_agencies_data,
    parse_allowed_credit_cards,
    parse_board,
    parse_booking_code,
    parse_cancellation_policy,
    parse_comments,
    parse_holder_reservation,
    parse_hotel_content_short,
    parse_hotel_info,
    parse_hotel_item,
    parse_offers,
    parse_paxes_reservation,
    parse_preferences,
    parse_prices,
    parse_required_fields,
    parse_reservation_comments,
    parse_rooms,
    parse_supplements,
    parse_warnings,
    resolve_child,
    text,
    warning_codes,
)

# Keep the legacy underscore-prefixed names importable for any callers that
# reached into this module before §11.3. New code should import from
# ``_parsers`` directly.
_iter_list = iter_list
_text = text
_attr = attr
_bool_attr = bool_attr
_parse_hotel_info = parse_hotel_info
_parse_board = parse_board
_parse_prices = parse_prices
_parse_rooms = parse_rooms
_parse_cancellation = parse_cancellation_policy
_parse_offers = parse_offers
_parse_supplements = parse_supplements


# ---------------------------------------------------------------------------
# HotelAvail serializer
# ---------------------------------------------------------------------------


def serialize_hotel_avail(response: Any) -> list[dict]:
    """Convert ``HotelAvailResponse`` / ``AvailabilityRS`` into a flat list of
    candidate combinations.

    Each result is a **(HotelResult × HotelOption) pair** — a hotel with two
    board plans therefore produces two rows. The merge key in
    ``JuniperClient.hotel_avail`` is ``rate_plan_code``, which is unique per
    HotelOption, so this expansion does not create false duplicates.

    The returned dicts contain both backward-compatible keys (``name`` /
    ``rate_plan_code`` / ``total_price`` / ``currency`` / ``board_type`` /
    ``city`` / ``room_type`` / ``cancellation_policy``) and richer structured
    fields (``rooms`` / ``cancellation`` / ``offers`` / ``category_type``
    / ``status`` / ``non_refundable`` / ``nett_price`` / …) for future tools.
    """
    if response is None:
        return []

    # Response-level warnings (e.g. ``warnObsoleteJPCode``) are parsed once
    # and echoed on every row so downstream tools can audit without passing
    # the raw response around.
    warnings = parse_warnings(response)
    warn_codes = warning_codes(warnings)

    # Juniper's UAT WSDL binds ``<Results>`` using xs:any, so zeep packs
    # ``<HotelResult>`` children into ``Results._value_1`` instead of a
    # named ``Results.HotelResult`` attribute (2026-04-23 diagnosis — see
    # ``doc/refactor-juniper-hotelcodes.md`` §10). ``resolve_child`` tries
    # the named-attr path first and falls back to the xs:any list, so
    # both shapes (and the direct ``response.HotelResult`` legacy shape)
    # work transparently without touching the downstream parsing.
    results_node = getattr(response, "Results", None)
    if results_node is not None:
        hotel_results = resolve_child(results_node, "HotelResult")
    else:
        hotel_results = resolve_child(response, "HotelResult")

    out: list[dict] = []
    for hr in hotel_results:
        jpcode = attr(hr, "JPCode") or attr(hr, "Code")
        code = attr(hr, "Code")
        jpdcode = attr(hr, "JPDCode")
        destination_zone = attr(hr, "DestinationZone")
        best_deal = bool_attr(hr, "BestDeal")
        info = parse_hotel_info(getattr(hr, "HotelInfo", None))

        options_wrapper = getattr(hr, "HotelOptions", None)
        # ``HotelOptions`` may itself use xs:any (symmetry with
        # ``Results``). Use ``resolve_child`` for the same reason.
        options = resolve_child(options_wrapper, "HotelOption")
        if not options:
            continue

        for opt in options:
            additional = getattr(opt, "AdditionalElements", None)
            prices = parse_prices(getattr(opt, "Prices", None))
            board = parse_board(getattr(opt, "Board", None))
            rooms = parse_rooms(getattr(opt, "HotelRooms", None))
            cancellation = parse_cancellation_policy(getattr(opt, "CancellationPolicy", None))
            offers = parse_offers(additional)
            supplements = parse_supplements(additional)

            first_room = rooms[0] if rooms else {}
            cancel_desc = (cancellation or {}).get("description", "") or ""
            # ``NonRefundable`` is authoritative when present but optional on
            # some supplier connections — preserve the tri-state (True /
            # False / None=unknown) so callers don't mistake "missing" for
            # "refundable".
            raw_nonref = getattr(opt, "NonRefundable", None)
            non_refundable = bool_attr(opt, "NonRefundable")
            refundable = (not non_refundable) if raw_nonref is not None else None

            out.append({
                "hotel_code": jpcode,
                "name": info["name"],
                "category": info["category"],
                "address": info["address"],
                "city": "",
                "rate_plan_code": attr(opt, "RatePlanCode"),
                "total_price": prices["total_price"],
                "currency": prices["currency"] or "EUR",
                "board_type": board["type"],
                "room_type": first_room.get("category_type", ""),
                "cancellation_policy": cancel_desc,
                "code": code,
                "jpcode": jpcode,
                "jpdcode": jpdcode,
                "destination_zone": destination_zone,
                "best_deal": best_deal,
                "latitude": info["latitude"],
                "longitude": info["longitude"],
                "category_type": info["category_type"],
                "board_name": board["name"],
                "status": attr(opt, "Status"),
                "non_refundable": non_refundable,
                # Derived: authoritative refundability signal for callers
                # (sandbox / tools). ``cancellation.rules`` carries the
                # per-window breakdown for UIs that need the fine print.
                "refundable": refundable,
                "package_contract": bool_attr(opt, "PackageContract"),
                "nett_price": prices["nett_price"],
                "service": prices["service"],
                "service_taxes": prices["service_taxes"],
                "taxes_included": prices["taxes_included"],
                "rooms": rooms,
                "cancellation": cancellation,
                "offers": offers,
                "supplements": supplements,
                "warnings": warnings,
                "warning_codes": sorted(warn_codes),
            })

    return out


def serialize_check_avail(response: Any) -> dict:
    """Convert ``HotelCheckAvailResponse`` / ``CheckAvailRS`` into a flat dict.

    Real XML (per official docs — see
    ``uploads/hotel-api-0.md`` lines 2511-2544 and ``doc/juniper-hotel-api.md``
    §HotelCheckAvail Response) nests candidates the same way HotelAvail does:

        CheckAvailRS
        ├── Warnings/Warning[*]       # warnPriceChanged / warnStatusChanged / warnCheckNotPossible
        └── Results
            └── HotelResult
                └── HotelOptions
                    └── HotelOption(list)   # may contain multiple re-priced combos
                        ├── @RatePlanCode   # ← NEW, use this for subsequent flow steps
                        ├── @Status (OK|RQ)
                        ├── Board(@Type, text)
                        ├── Prices/Price/TotalFixAmounts(@Gross, @Nett)
                        └── HotelRooms/HotelRoom(list)

    Selection rule: among the returned options prefer ``@Status=OK`` and,
    if several match, take the one with the lowest gross price (mirrors
    Juniper's "best deal" behaviour). If no OK option exists we still return
    a ``@Status=RQ`` option's details so the client layer can decide whether
    to fall back.

    Returned dict (backward-compatible keys ``available`` / ``rate_plan_code``
    / ``total_price`` / ``currency`` / ``price_changed`` are retained, plus
    richer fields callers can opt into):

        {
          "available":      bool,       # True only when an OK option exists
          "rate_plan_code": str,        # NEW code from response (may be empty)
          "total_price":    str,        # gross total of picked option
          "currency":       str,
          "status":         "OK"|"RQ"|"",
          "price_changed":  bool,       # warnPriceChanged in Warnings
          "status_changed": bool,       # warnStatusChanged in Warnings
          "check_not_possible": bool,   # warnCheckNotPossible — supplier couldn't verify
          "board":          {type, name},
          "rooms":          [ {...} ],
          "nett_price":     str,
          "service":        str,
          "service_taxes":  str,
          "taxes_included": bool|None,
          "warnings":       [ {code, text} ],
          "warning_codes":  [ str, ... ],
          "raw_options":    int,        # how many HotelOption were in the response
        }
    """
    warnings = parse_warnings(response)
    warn_codes = warning_codes(warnings)

    # Response-level warnings always come back, even when the supplier can't
    # verify (``warnCheckNotPossible``) or only has RQ stock left. Callers
    # must be able to distinguish "offer still bookable" from "offer gone /
    # price moved" without inspecting raw XML.
    price_changed = "warnPriceChanged" in warn_codes
    status_changed = "warnStatusChanged" in warn_codes
    check_not_possible = "warnCheckNotPossible" in warn_codes

    # Same xs:any binding issue as HotelAvail / BookingRules — route
    # ``Results.HotelResult`` and ``HotelOptions.HotelOption`` through
    # ``resolve_child`` so the lxml and dict fallback paths both work
    # (see doc/refactor-juniper-serializers.md §11 UAT 2026-04-23).
    results_node = getattr(response, "Results", None) if response is not None else None
    hotel_results = resolve_child(results_node, "HotelResult") if results_node is not None else []
    if not hotel_results and response is not None:
        hotel_results = resolve_child(response, "HotelResult")
    hotel_result = hotel_results[0] if hotel_results else None

    options_wrapper = getattr(hotel_result, "HotelOptions", None) if hotel_result is not None else None
    options = resolve_child(options_wrapper, "HotelOption") if options_wrapper is not None else []

    # Selection: prefer Status=OK with lowest gross. Fall back to any option
    # (so callers see the RQ status when that's all the supplier has).
    picked = _pick_check_avail_option(options)

    if picked is None:
        return {
            "available": False,
            "rate_plan_code": "",
            "total_price": "0",
            "currency": "",
            "status": "",
            "price_changed": price_changed,
            "status_changed": status_changed,
            "check_not_possible": check_not_possible,
            "board": {"type": "", "name": ""},
            "rooms": [],
            "nett_price": "0",
            "service": "",
            "service_taxes": "",
            "taxes_included": None,
            "warnings": warnings,
            "warning_codes": sorted(warn_codes),
            "raw_options": len(options),
        }

    prices = parse_prices(getattr(picked, "Prices", None))
    board = parse_board(getattr(picked, "Board", None))
    rooms = parse_rooms(getattr(picked, "HotelRooms", None))
    status = attr(picked, "Status")

    return {
        # The new RatePlanCode from the response — NOT the one the caller
        # passed in. Docs §HotelCheckAvail Response explicitly: "use this
        # RatePlanCode in order to proceed with the booking flow".
        "rate_plan_code": attr(picked, "RatePlanCode"),
        "available": status == "OK",
        "status": status,
        "total_price": prices["total_price"],
        "currency": prices["currency"] or "EUR",
        "price_changed": price_changed,
        "status_changed": status_changed,
        "check_not_possible": check_not_possible,
        "board": board,
        "rooms": rooms,
        "nett_price": prices["nett_price"],
        "service": prices["service"],
        "service_taxes": prices["service_taxes"],
        "taxes_included": prices["taxes_included"],
        "warnings": warnings,
        "warning_codes": sorted(warn_codes),
        "raw_options": len(options),
    }


def _pick_check_avail_option(options: list[Any]) -> Any | None:
    """Select the best HotelOption from a CheckAvail response.

    Strategy: prefer ``@Status=OK`` and among those the lowest gross price
    (ties broken by the original order). If no OK options exist, return the
    first option so the caller still sees the RQ status. Empty list → None.
    """
    if not options:
        return None

    def gross_of(opt: Any) -> float:
        try:
            return float(parse_prices(getattr(opt, "Prices", None))["total_price"])
        except (TypeError, ValueError):
            return float("inf")

    ok_options = [o for o in options if attr(o, "Status") == "OK"]
    if ok_options:
        return min(ok_options, key=gross_of)
    return options[0]


def serialize_booking_rules(response: Any) -> dict:
    """Convert ``BookingRulesRS`` into a structured dict.

    Real XML structure (see ``uploads/hotel-api-0.md`` §HotelBookingRules
    Response, also the companion file
    ``agent-tools/3c188552-...txt`` lines 2644-2780)::

        BookingRulesRS
        └── Results
            └── HotelResult
                └── HotelOptions
                    └── HotelOption @Status [@RatePlanCode]
                        ├── BookingCode @ExpirationDate          (10-min TTL)
                        ├── HotelRequiredFields/HotelBooking/... (template)
                        ├── CancellationPolicy/{Description, PolicyRules}
                        ├── PriceInformation
                        │   ├── Board(@Type)
                        │   ├── HotelRooms/HotelRoom[*]                        │   ├── Prices/Price/TotalFixAmounts
                        │   ├── AdditionalElements
                        │   │   ├── HotelOffers/HotelOffer[*]                        │   │   └── HotelSupplements/HotelSupplement[*]
                        │   └── HotelContent/{HotelName, Address/Address,
                        │                     HotelCategory, HotelType, Zone}
                        └── OptionalElements
                            ├── Comments/Comment[*]   (CDATA, must be shown)
                            ├── HotelSupplements/HotelSupplement[*]  (optional)
                            ├── Preferences/Preference[*]
                            └── AllowedCreditCards/CreditCard[*]

    The returned dict preserves the legacy flat keys (``valid``,
    ``total_price``, ``currency``, ``cancellation_policy``, ``remarks``,
    ``booking_code``, ``booking_code_expires_at``, ``rate_plan_code``) so
    ``get_booking_rules`` in the agent tool layer keeps working, and adds
    structured fields needed by §11.8 (HotelBooking request builder) and the
    cancellation-policy UX.
    """
    warnings = parse_warnings(response)
    warn_codes = warning_codes(warnings)

    # Same xs:any binding issue as HotelAvail (see §11.4 / UAT 2026-04-23
    # diagnosis in doc/refactor-juniper-serializers.md): Juniper's WSDL
    # declares ``Results`` / ``HotelOptions`` as xs:any containers, so
    # zeep sometimes stashes ``<HotelResult>`` in ``Results._value_1``
    # instead of exposing it as a named attr. ``resolve_child`` falls
    # back to ``_value_1`` transparently and wraps lxml / dict payloads
    # so downstream ``getattr`` / :func:`attr` / :func:`text` keep working.
    results_node = getattr(response, "Results", None) if response is not None else None
    hotel_results = resolve_child(results_node, "HotelResult") if results_node is not None else []
    if not hotel_results and response is not None:
        hotel_results = resolve_child(response, "HotelResult")
    hotel_result = hotel_results[0] if hotel_results else None
    options_wrapper = getattr(hotel_result, "HotelOptions", None) if hotel_result is not None else None
    options = resolve_child(options_wrapper, "HotelOption") if options_wrapper is not None else []

    # Prefer the OK option; fall back to the first option if none are OK (so
    # the agent can still surface the warnings).
    opt = next((o for o in options if attr(o, "Status") == "OK"), options[0] if options else None)

    # --------- empty/failed response ---------
    if opt is None:
        return {
            # legacy flat keys
            "valid": False,
            "rate_plan_code": "",
            "total_price": "0",
            "currency": "",
            "cancellation_policy": "",
            "remarks": "",
            "booking_code": "",
            "booking_code_expires_at": "",
            # structured
            "status": "",
            "price_changed": "warnPriceChanged" in warn_codes,
            "status_changed": "warnStatusChanged" in warn_codes,
            "nett_price": "0",
            "service": "",
            "service_taxes": "",
            "taxes_included": None,
            "board": {"type": "", "name": ""},
            "rooms": [],
            "cancellation": None,
            "offers": [],
            "supplements": [],
            "optional_supplements": [],
            "comments": [],
            "preferences": [],
            "allowed_credit_cards": [],
            "hotel_content": parse_hotel_content_short(None),
            "required_fields": parse_required_fields(None),
            "warnings": warnings,
            "warning_codes": sorted(warn_codes),
            "raw_options": len(options),
        }

    status = attr(opt, "Status")

    # --------- BookingCode (critical, 10-min TTL) ---------
    bc = parse_booking_code(getattr(opt, "BookingCode", None))

    # --------- PriceInformation ---------
    price_info = getattr(opt, "PriceInformation", None)
    prices = parse_prices(getattr(price_info, "Prices", None) if price_info is not None else None)
    board = parse_board(getattr(price_info, "Board", None) if price_info is not None else None)
    rooms = parse_rooms(getattr(price_info, "HotelRooms", None) if price_info is not None else None)

    additional = getattr(price_info, "AdditionalElements", None) if price_info is not None else None
    offers = parse_offers(additional)
    # Supplements bundled inside the price (included in total)
    price_supplements = parse_supplements(additional)
    hotel_content = parse_hotel_content_short(
        getattr(price_info, "HotelContent", None) if price_info is not None else None
    )

    # --------- CancellationPolicy ---------
    cancellation = parse_cancellation_policy(getattr(opt, "CancellationPolicy", None))
    # Legacy flat string (joined description) — keep so the existing agent
    # tool keeps rendering something even if the caller has not yet upgraded.
    cancellation_text = cancellation.get("description", "") if cancellation else ""

    # --------- OptionalElements ---------
    optional_elements = getattr(opt, "OptionalElements", None)
    comments = parse_comments(optional_elements)
    # Optional supplements the caller can add via a second HotelBookingRules
    # request (distinct from the included-in-price supplements above).
    optional_supplements = parse_supplements(optional_elements)
    preferences = parse_preferences(optional_elements)
    allowed_cards = parse_allowed_credit_cards(optional_elements)
    # Legacy ``remarks`` collapses all hotel comments into one string.
    remarks = "\n\n".join(c["text"] for c in comments if c.get("text"))

    # --------- HotelRequiredFields (template) ---------
    required_fields = parse_required_fields(getattr(opt, "HotelRequiredFields", None))

    return {
        # ---- legacy flat keys (kept for backward compat) ----
        "valid": status == "OK",
        "rate_plan_code": attr(opt, "RatePlanCode"),
        "total_price": prices["total_price"],
        "currency": prices["currency"] or "EUR",
        "cancellation_policy": cancellation_text,
        "remarks": remarks,
        "booking_code": bc["value"],
        "booking_code_expires_at": bc["expires_at"],
        # ---- structured fields ----
        "status": status,
        "price_changed": "warnPriceChanged" in warn_codes,
        "status_changed": "warnStatusChanged" in warn_codes,
        "nett_price": prices["nett_price"],
        "service": prices["service"],
        "service_taxes": prices["service_taxes"],
        "taxes_included": prices["taxes_included"],
        "board": board,
        "rooms": rooms,
        "cancellation": cancellation,
        "offers": offers,
        "supplements": price_supplements,
        "optional_supplements": optional_supplements,
        "comments": comments,
        "preferences": preferences,
        "allowed_credit_cards": allowed_cards,
        "hotel_content": hotel_content,
        "required_fields": required_fields,
        "warnings": warnings,
        "warning_codes": sorted(warn_codes),
        "raw_options": len(options),
    }


def _empty_booking_result() -> dict:
    """Shape returned when the response carries no ``Reservations``.

    Keeps the legacy flat keys populated with safe defaults so downstream
    code that only reads ``booking_id`` / ``status`` / ``total_price``
    doesn't KeyError. Agent tools treat an empty ``booking_id`` as a
    failure signal.
    """
    return {
        # ---- legacy flat keys (agent/tools/book_hotel.py reads these) ----
        "booking_id": "",
        "status": "",
        "hotel_name": "",
        "check_in": "",
        "check_out": "",
        "total_price": "0",
        "currency": "EUR",
        "guest_name": "",
        # ---- structured fields ----
        "raw_status": "",
        "status_semantic": "",
        "payment_destination": False,
        "external_booking_reference": "",
        "holder": {"rel_pax_id": "", "pax": None},
        "paxes": [],
        "comments": [],
        "agencies_data": [],
        "hotel_item": {},
        "warnings": [],
        "warning_codes": [],
        "raw_reservations": 0,
    }


def serialize_booking(response: Any) -> dict:
    """Convert a ``HotelBookingResponse`` / ``ReadBookingResponse`` /
    ``CancelBookingResponse`` into a structured dict.

    The three responses share the ``Reservations/Reservation`` container
    (docs lines 3478-3726, 3762-3890, 3976-4025) so a single serializer
    covers all of them. ``serialize_read_booking`` delegates here.

    Output shape::

        {
          # ---- legacy flat keys (kept for backward compat with
          #      agent/tools/book_hotel.py + juniper/mock_client.py) ----
          "booking_id":   "TQ1TBG",      # Reservation/@Locator
          "status":       "confirmed",   # normalised semantic status
          "hotel_name":   "APARTAMENTOS ALLSUN PIL-LARI PLAYA",
          "check_in":     "2019-11-20",
          "check_out":    "2019-11-22",
          "total_price":  "1003.57",
          "currency":     "EUR",
          "guest_name":   "Holder Name Holder Surname",

          # ---- structured fields ----
          "raw_status":           "PAG",        # Reservation/@Status (Juniper code)
          "status_semantic":      "confirmed",  # same as ``status``, explicit alias
          "payment_destination":  False,        # Reservation/@PaymentDestination
          "external_booking_reference": "YOUR_OWN_REFERENCE_123",
          "holder":    {"rel_pax_id": "4", "pax": {... holder pax details ...}},
          "paxes":     [...],                   # full Reservation/Paxes
          "comments":  [{"type": "RES", "text": "..."}],
          "agencies_data": [...],
          "hotel_item":    {...},               # full HotelItem[0] structured
          "warnings":       [{"code", "text"}],
          "warning_codes":  ["warnCancelledAndCancellationCostRetrieved", ...],
          "raw_reservations": 1,
        }

    Multi-Reservation responses (rare — same locator rebooked) are
    handled by returning the first reservation and recording the total
    in ``raw_reservations`` as a diagnostic. TODO in §11.x if Juniper
    needs multi-reservation handling.
    """
    warnings = parse_warnings(response)
    warn_codes = warning_codes(warnings)

    # Normalise the Reservations/Reservation path. Both nodes can be
    # single children (zeep unwraps) or lists, AND both may use xs:any
    # binding like the availability responses (see UAT 2026-04-23) so
    # route through ``resolve_child`` for safety.
    reservations_wrapper = getattr(response, "Reservations", None) if response is not None else None
    reservation_list = resolve_child(reservations_wrapper, "Reservation")

    if not reservation_list:
        empty = _empty_booking_result()
        empty["warnings"] = warnings
        empty["warning_codes"] = sorted(warn_codes)
        return empty

    reservation = reservation_list[0]

    # ---- identifiers + status ----
    locator = attr(reservation, "Locator")
    raw_status = attr(reservation, "Status")
    semantic = normalise_reservation_status(raw_status)
    payment_destination = bool_attr(reservation, "PaymentDestination")
    external_ref = text(getattr(reservation, "ExternalBookingReference", None))

    # ---- paxes + holder ----
    paxes = parse_paxes_reservation(getattr(reservation, "Paxes", None))
    holder = parse_holder_reservation(getattr(reservation, "Holder", None), paxes)

    # ---- comments + agencies ----
    comments = parse_reservation_comments(getattr(reservation, "Comments", None))
    agencies = parse_agencies_data(getattr(reservation, "AgenciesData", None))

    # ---- HotelItem[0] ----
    items_wrapper = getattr(reservation, "Items", None)
    hotel_items = iter_list(
        getattr(items_wrapper, "HotelItem", None) if items_wrapper is not None else None
    )
    hotel_item = parse_hotel_item(hotel_items[0]) if hotel_items else {}

    # ---- legacy flat-key derivation ----
    hotel_info = hotel_item.get("hotel_info", {}) or {}
    prices = hotel_item.get("prices", {}) or {}
    # Guest name comes from the Holder pax (preferred) and falls back to
    # the first regular pax if no holder was supplied.
    holder_pax = holder.get("pax") if isinstance(holder, dict) else None
    if not holder_pax and paxes:
        holder_pax = paxes[0]
    guest_name = ""
    if holder_pax:
        parts = [holder_pax.get("name") or "", holder_pax.get("surname") or ""]
        guest_name = " ".join(p for p in parts if p).strip()

    return {
        # ---- legacy flat keys (kept for backward compat) ----
        "booking_id":   locator,
        "status":       semantic or raw_status,
        "hotel_name":   hotel_info.get("name", ""),
        "check_in":     hotel_item.get("check_in", ""),
        "check_out":    hotel_item.get("check_out", ""),
        "total_price":  prices.get("total_price", "0"),
        "currency":     prices.get("currency") or "EUR",
        "guest_name":   guest_name,
        # ---- structured fields ----
        "raw_status":   raw_status,
        "status_semantic": semantic,
        "payment_destination": payment_destination,
        "external_booking_reference": external_ref,
        "holder":       holder,
        "paxes":        paxes,
        "comments":     comments,
        "agencies_data": agencies,
        "hotel_item":   hotel_item,
        "warnings":     warnings,
        "warning_codes": sorted(warn_codes),
        "raw_reservations": len(reservation_list),
    }


def serialize_read_booking(response: Any) -> dict:
    """Convert ``ReadBookingResponse`` to a dict.

    Per docs line 3758: "*It returns the same information as the response
    of HotelBooking*". We delegate entirely to :func:`serialize_booking`
    so any future bug fix flows to both endpoints.
    """
    return serialize_booking(response)


def hotels_to_llm_summary(hotels: list[dict]) -> str:
    """Format hotel list for LLM context (one line per candidate).

    Accepts both new-shape dicts (with ``board_name`` / ``status`` /
    ``jpdcode``) and legacy/mock dicts (flat ``board_type`` / ``city``).
    """
    if not hotels:
        return "No hotels found matching the criteria."

    lines: list[str] = []
    for i, h in enumerate(hotels, 1):
        name = h.get("name") or h.get("hotel_code") or "(unknown hotel)"
        category = h.get("category") or h.get("category_type") or ""
        price = h.get("total_price") or "0"
        currency = h.get("currency") or "EUR"
        board = h.get("board_name") or h.get("board_type") or ""
        location = h.get("city") or h.get("jpdcode") or ""
        rpc = h.get("rate_plan_code") or ""
        status = (h.get("status") or "").upper()

        line = f"{i}. {name}"
        if category:
            line += f" ({category})"
        line += f" - {price} {currency}"
        if board:
            line += f" | {board}"
        if location:
            line += f" | {location}"
        if rpc:
            line += f" | rate_plan_code: {rpc}"
        if status == "RQ":
            line += " | on request"
        lines.append(line)
    return "\n".join(lines)
