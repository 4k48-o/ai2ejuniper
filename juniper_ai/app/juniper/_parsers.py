"""Shared parsers for Juniper SOAP responses.

Juniper's WebServiceJP returns deeply nested responses (``Results`` →
``HotelResult`` → ``HotelOptions`` → ``HotelOption`` → ``Board`` / ``Prices``
/ ``HotelRooms`` / ``CancellationPolicy`` / ``AdditionalElements``). The
same sub-structures appear across ``HotelAvail`` / ``HotelCheckAvail`` /
``HotelBookingRules`` / ``HotelBooking`` / ``ReadBooking`` — keeping the
parsing logic in **one** place means every refactor tick (§11.1 / §11.4 /
§11.5 / §11.7) benefits from the same bug fixes.

Zeep shape quirks handled here:

* Single child vs. list: zeep returns a single ``HotelOption`` directly (not
  wrapped in a list) when there is only one. :func:`iter_list` normalises.
* Text vs. attribute: a node like ``<HotelCategory Type="4est">4 Stars</...>``
  has both. Use :func:`text` for the inner text and :func:`attr` for
  attributes — never ``str(node)``.
* Boolean attributes come through as ``"true"`` / ``"false"`` strings.

The low-level zeep helpers are underscore-prefixed (``_iter_list`` etc.) but
re-exported without the underscore (``iter_list`` etc.) for call-sites that
want readable imports. Callers should prefer the unprefixed aliases.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Zeep-shape helpers
# ---------------------------------------------------------------------------


def iter_list(node: Any) -> list[Any]:
    """Normalise a zeep child into a Python list.

    - ``None`` → ``[]``
    - ``list`` / ``tuple`` → filtered list (drops ``None``)
    - single node / scalar → ``[node]``
    """
    if node is None:
        return []
    if isinstance(node, (list, tuple)):
        return [x for x in node if x is not None]
    return [node]


# ---------------------------------------------------------------------------
# xs:any / ``_value_1`` unwrapping
# ---------------------------------------------------------------------------
#
# Juniper's real UAT response binds ``<Results>`` / some other wrappers
# using ``xs:any`` (or an equivalent xs:choice wildcard), so zeep packs
# the actual named children (``<HotelResult>``, ``<Warning>``, …) into a
# plain list on ``parent._value_1`` rather than exposing them as named
# attributes. Observed on 2026-04-23 UAT smoke test (see
# ``doc/refactor-juniper-hotelcodes.md`` §10 debugging note):
#
#     AvailabilityRS.Results = JP_Results(_value_1=list[1], __values__keys=['_value_1'])
#     AvailabilityRS.Results.HotelResult = None          # named attr empty
#     AvailabilityRS.Results._value_1    = [<lxml HotelResult>]   # data lives here
#
# The items in ``_value_1`` can be any of:
#
# 1. ``lxml.etree._Element`` — bare XML element (most common case when
#    zeep has no schema binding for the child).
# 2. ``zeep.objects.AnyObject`` — some zeep versions wrap the element and
#    put the parsed object on ``.value``.
# 3. A regular zeep complex value with named attributes — happens when
#    the WSDL declared the child type explicitly and zeep managed to
#    bind it despite the xs:any container.
#
# We normalise all three into something the existing parsers can read
# via ``getattr(node, "AttrOrChild", ...)`` by wrapping lxml elements in
# :class:`_LXMLProxy`.


def _is_lxml_element(x: Any) -> bool:
    """Duck-type check for an lxml ``_Element``.

    Zeep can hand us lxml elements from three places: ``lxml.etree`` (the
    canonical module), ``lxml.objectify`` (element classes live in
    ``lxml.objectify``), and ``zeep.xsd.types.any.AnyObject`` wrappers
    whose ``.value`` is an lxml element. Rather than listing module
    prefixes, we duck-type: an object is "lxml-element-like" if it
    exposes the full ``.tag`` / ``.attrib`` / ``.text`` / iter-children
    protocol. This intentionally excludes our own :class:`_LXMLProxy`
    (which has ``.tag`` only via ``__getattr__``) via the explicit
    ``__iter__`` check — proxies are not iterable as element children.
    """
    if x is None:
        return False
    if isinstance(x, _LXMLProxy):
        return False
    # Must have the full lxml element protocol.
    if not (hasattr(x, "tag") and hasattr(x, "attrib") and hasattr(x, "text")):
        return False
    # Must be iterable over child elements (lxml elements yield children).
    # A zeep ComplexValue would have ``.tag`` via __getattr__ only when
    # the underlying XSD defines a Tag attribute — extremely rare — and
    # would not be iterable in the lxml sense.
    try:
        iter(x)
    except TypeError:
        return False
    # Reject our own proxy / strings / bytes.
    if isinstance(x, (str, bytes)):
        return False
    return True


class _LXMLProxy:
    """Lightweight attribute-access proxy over an lxml ``_Element``.

    Mimics just enough of zeep's object semantics for
    :func:`attr` / :func:`text` / :func:`iter_list` and the downstream
    parsers to keep working without a dedicated lxml code path.

    ``getattr(proxy, name)`` resolution order:

    1. XML attribute value → ``str``.
    2. Exactly one matching child with only text → that text (``str``).
    3. Exactly one matching child with attrs or nested children →
       a nested :class:`_LXMLProxy`.
    4. Multiple matching children → ``list[_LXMLProxy]``.
    5. Nothing → ``None``.

    Supports ``_value_1`` (element text content) to stay compatible with
    the :func:`text` helper, which reads that attribute for "text +
    attrs" elements like ``<Board Type="SA">Room Only</Board>``.
    """

    __slots__ = ("_el",)

    def __init__(self, el: Any) -> None:
        self._el = el

    def __repr__(self) -> str:
        from lxml import etree  # local import keeps module import-time light

        tag = etree.QName(self._el.tag).localname
        attrs = " ".join(f"{k}={v!r}" for k, v in self._el.attrib.items())
        return f"<{tag} {attrs}>" if attrs else f"<{tag}>"

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        el = object.__getattribute__(self, "_el")

        if name == "_value_1":
            return el.text or ""
        if name == "_el":
            return el

        if name in el.attrib:
            return el.attrib[name]

        from lxml import etree

        children = [c for c in el if etree.QName(c.tag).localname == name]
        if not children:
            return None
        if len(children) == 1:
            c = children[0]
            if len(c) == 0 and not c.attrib:
                return c.text or ""
            return _LXMLProxy(c)
        return [_LXMLProxy(c) for c in children]


class _DictProxy:
    """Lightweight attribute-access proxy over a plain ``dict``.

    Zeep — when bound against a WSDL that declares xs:any on containers
    like ``<Results>`` / ``<HotelOptions>`` — sometimes deserialises the
    unknown children into *plain Python dicts* (observed on
    ``JP_AvailResponseRS``: ``Results._value_1[0] = builtins.dict()``).
    A dict is neither an lxml element nor a zeep ComplexValue, so the
    downstream parsers (which rely on ``getattr(node, name)``) can't see
    through it.

    This proxy adapts the dict so every existing ``attr()`` / ``text()``
    / serializer call keeps working:

    * ``getattr(proxy, name)`` → ``self._d[name]`` (nested dicts are
      lazy-wrapped; nested lists map to ``list[_DictProxy | str | ...]``).
    * ``getattr(proxy, "_value_1")`` — used by :func:`text` for
      "text + attrs" nodes — returns the ``_value_1`` key if present,
      else ``""``. Zeep typically stores element text at this key.
    * Unknown attributes → ``None`` (matches ``_LXMLProxy`` semantics).

    Note we intentionally do NOT try to distinguish XML attributes from
    child elements — Juniper's responses never collide on names, and
    the downstream ``attr()`` / ``text()`` helpers already fall back
    between the two.
    """

    __slots__ = ("_d",)

    def __init__(self, d: dict) -> None:
        self._d = d

    def __repr__(self) -> str:
        keys = list(self._d.keys())[:6]
        return f"_DictProxy(keys={keys})"

    @staticmethod
    def _wrap_value(v: Any) -> Any:
        if isinstance(v, dict):
            return _DictProxy(v)
        if isinstance(v, list):
            return [_DictProxy._wrap_value(x) for x in v]
        if _is_lxml_element(v):
            return _LXMLProxy(v)
        return v

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") or name == "_d":
            raise AttributeError(name)
        d = object.__getattribute__(self, "_d")
        if name in d:
            return _DictProxy._wrap_value(d[name])
        # ``_value_1`` is zeep's canonical element-text key; return empty
        # string (not None) to stay compatible with ``text()`` which
        # does ``str(x).strip()``.
        if name == "_value_1":
            return d.get("_value_1", "") or ""
        return None

    # Makes ``iter_list(_DictProxy)`` treat it as a single item, not a
    # dict-of-key-value-pairs.
    def __iter__(self):
        raise TypeError("_DictProxy is not iterable; use getattr for named access")

    def keys(self):  # noqa: D401 — compat with dict-like introspection
        """Return the underlying dict's keys (for debug / tests)."""
        return self._d.keys()


def unwrap_xs_any_item(item: Any) -> Any:
    """Normalise a single item from ``parent._value_1`` to something the
    rest of the parser code can read via ``getattr``.

    * ``lxml.etree._Element`` → wrapped in :class:`_LXMLProxy`.
    * zeep ``AnyObject`` (has ``.value``) → the inner value (itself
      recursively unwrapped).
    * plain ``dict`` → wrapped in :class:`_DictProxy` (zeep's fallback
      deserialisation for xs:any children without an explicit schema).
    * anything else → passed through unchanged (already zeep-object-like).
    """
    if item is None:
        return None
    # Peel zeep AnyObject(value=...) wrappers before shape-typing.
    inner = getattr(item, "value", None)
    if inner is not None and inner is not item:
        item = inner
    if _is_lxml_element(item):
        return _LXMLProxy(item)
    if isinstance(item, dict):
        return _DictProxy(item)
    return item


_BUSINESS_MARKERS = {
    "HotelResult":  ("JPCode", "HotelInfo", "HotelOptions"),
    "HotelOption":  ("RatePlanCode", "Board", "Prices"),
    "HotelOffer":   ("Code", "Name"),
    "Warning":      ("Code", "Text"),
    "Reservation":  ("Locator", "Holder", "Items"),
    "Zone":         ("JPDCode", "Code", "Name"),
}


def _looks_like_target(item: Any, child_name: str) -> bool:
    """Heuristic: does ``item`` *look like* it is already a ``child_name``
    node (rather than a wrapper whose child we still need to drill into)?

    Used as a last-resort fallback inside :func:`iter_xs_any_children`
    when neither ``_LXMLProxy`` tag match nor named-attr drill-down
    succeeds: we peek for a business-level marker attribute that's
    uniquely part of ``child_name`` (e.g. ``JPCode`` on a HotelResult).
    """
    if item is None:
        return False
    markers = _BUSINESS_MARKERS.get(child_name)
    if not markers:
        return False
    return any(getattr(item, m, None) is not None for m in markers)


def iter_xs_any_children(parent: Any, child_name: str) -> list[Any]:
    """Return all ``child_name`` children that zeep stashed in
    ``parent._value_1`` when the WSDL uses xs:any.

    Resolution order for each item in ``parent._value_1``:

    1. :func:`unwrap_xs_any_item` → unwraps zeep ``AnyObject.value`` and
       wraps lxml elements in :class:`_LXMLProxy`.
    2. If it's a :class:`_LXMLProxy` whose tag matches → accept.
    3. If ``getattr(item, child_name)`` is non-None → accept that
       attribute (xs:any wrapper that itself nests named children).
    4. If it "looks like" a ``child_name`` via business markers
       (``JPCode`` for HotelResult, ``RatePlanCode`` for HotelOption,
       …) → accept item directly.
    5. Otherwise → drop the item and log once at DEBUG so we can see
       the unexpected shape in :mod:`juniper_ai.app.juniper.client`
       when ``JUNIPER_DEBUG_RAW_RESPONSE=1``.
    """
    if parent is None:
        return []
    value_1 = getattr(parent, "_value_1", None)
    items = iter_list(value_1)
    if not items:
        return []
    from lxml import etree

    out: list[Any] = []
    unmatched: list[str] = []
    for raw in items:
        item = unwrap_xs_any_item(raw)
        if item is None:
            continue
        if isinstance(item, _LXMLProxy):
            if etree.QName(item._el.tag).localname == child_name:
                out.append(item)
            else:
                unmatched.append(
                    f"LXMLProxy(tag={etree.QName(item._el.tag).localname})"
                )
            continue
        direct = getattr(item, child_name, None)
        if direct is not None:
            out.extend(iter_list(direct))
            continue
        if _looks_like_target(item, child_name):
            out.append(item)
            continue
        unmatched.append(f"{type(item).__module__}.{type(item).__name__}")
    if unmatched and not out:
        # Visible enough to spot in a normal sandbox run, quiet enough to
        # not spam production. Downgraded to DEBUG once we have coverage
        # for the specific shape.
        logger.warning(
            "iter_xs_any_children(%s): dropped %d item(s) with no match; "
            "types=%s — add a case in _parsers._BUSINESS_MARKERS or "
            "unwrap_xs_any_item to handle this shape.",
            child_name, len(unmatched), unmatched[:5],
        )
    return out


def resolve_child(parent: Any, child_name: str) -> list[Any]:
    """Return ``parent.<child_name>`` normalised to a list, with a
    transparent fallback to :func:`iter_xs_any_children` when zeep's
    named binding is empty (the xs:any case).

    This is the recommended entry point for any serializer that walks a
    response element whose WSDL type is suspected to use xs:any wildcard
    children (``<Results>`` / ``<Warnings>`` / ``<HotelOptions>`` on
    Juniper).
    """
    if parent is None:
        return []
    named = iter_list(getattr(parent, child_name, None))
    if named:
        return named
    return iter_xs_any_children(parent, child_name)


def text(node: Any, default: str = "") -> str:
    """Read the text content of a zeep element.

    Handles:
    - native ``str`` / ``int`` / ``float`` → ``str(node)``
    - complex type with ``<elem Attr="...">text</elem>`` → ``node._value_1``
    - everything else → ``default``
    """
    if node is None:
        return default
    if isinstance(node, (str, int, float)):
        return str(node)
    val = getattr(node, "_value_1", None)
    if val is not None:
        return str(val)
    return default


def attr(node: Any, name: str, default: str = "") -> str:
    """Read an attribute from a zeep node, returning ``default`` if absent."""
    if node is None:
        return default
    val = getattr(node, name, None)
    if val is None:
        return default
    return str(val)


def bool_attr(node: Any, name: str, default: bool = False) -> bool:
    """Read a boolean attribute; tolerates ``"true"`` / ``"false"`` strings."""
    if node is None:
        return default
    val = getattr(node, name, None)
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("true", "1", "yes")


def int_attr(node: Any, name: str, default: int | None = None) -> int | None:
    if node is None:
        return default
    val = getattr(node, name, None)
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


# Backwards-compatible underscore aliases for callers that already imported
# the internal names from serializers.py before the §11.3 extraction.
_iter_list = iter_list
_text = text
_attr = attr
_bool_attr = bool_attr
_int_attr = int_attr


# ---------------------------------------------------------------------------
# Warnings
# ---------------------------------------------------------------------------

# Codes the agent layer cares about. See ``uploads/hotel-api-0.md`` §Warnings.
# Used so callers can do ``"warnPriceChanged" in parse_warnings(r).codes``
# without string-matching free-form text.
KNOWN_WARNING_CODES = frozenset({
    "warnPriceChanged",
    "warnStatusChanged",
    "warnObsoleteJPCode",
    "warnHotelContent",
    "warnMaxFutureRates",
    "warnProcessExcededFutureRates",
    "warnNoDirectPaymentAvailable",
})


def parse_warnings(response: Any) -> list[dict]:
    """Extract ``Warnings/Warning[*]`` into ``[{"code": ..., "text": ...}]``.

    Returns an empty list when ``Warnings`` is absent. Non-recoverable errors
    live under ``Errors`` (handled separately by ``_raise_if_response_errors``
    in the client); this function is only for the advisory ``Warnings``
    container.
    """
    if response is None:
        return []
    warnings_node = getattr(response, "Warnings", None)
    if warnings_node is None:
        return []
    return [
        {"code": attr(w, "Code"), "text": attr(w, "Text")}
        for w in iter_list(getattr(warnings_node, "Warning", None))
    ]


def warning_codes(warnings: list[dict]) -> set[str]:
    """Reduce a parsed warnings list to a set of codes for membership checks."""
    return {w.get("code", "") for w in warnings if w.get("code")}


# ---------------------------------------------------------------------------
# Board / HotelInfo / Rooms
# ---------------------------------------------------------------------------


def parse_board(board_node: Any) -> dict:
    """Extract ``Board`` (``@Type`` attribute + text content).

    Example: ``<Board Type="SA">Room Only</Board>`` → ``{"type": "SA",
    "name": "Room Only"}``. Returns empty strings when absent so callers
    can safely concatenate.
    """
    if board_node is None:
        return {"type": "", "name": ""}
    return {
        "type": attr(board_node, "Type"),
        "name": text(board_node),
    }


def parse_hotel_info(info_node: Any) -> dict:
    """Extract ``HotelInfo`` into a flat dict.

    Only populated when the request included
    ``AdvancedOptions/ShowHotelInfo=true`` — see §11.2 for the client-side
    switch. Missing fields default to ``""`` so ``_ + _`` is safe.
    """
    if info_node is None:
        return {
            "name": "",
            "address": "",
            "category": "",
            "category_type": "",
            "latitude": "",
            "longitude": "",
        }
    cat_node = getattr(info_node, "HotelCategory", None)
    # HotelCategory may be a list if the API returns multiple — take the first.
    if isinstance(cat_node, (list, tuple)):
        cat_node = cat_node[0] if cat_node else None
    return {
        "name": text(getattr(info_node, "Name", None)),
        "address": text(getattr(info_node, "Address", None)),
        "category": text(cat_node),
        "category_type": attr(cat_node, "Type"),
        "latitude": text(getattr(info_node, "Latitude", None)),
        "longitude": text(getattr(info_node, "Longitude", None)),
    }


def parse_rooms(hotel_rooms_node: Any) -> list[dict]:
    """Extract ``HotelRooms/HotelRoom[*]`` into a list of room dicts."""
    if hotel_rooms_node is None:
        return []
    rooms = iter_list(getattr(hotel_rooms_node, "HotelRoom", None))
    out: list[dict] = []
    for r in rooms:
        room_cat = getattr(r, "RoomCategory", None)
        occ = getattr(r, "RoomOccupancy", None)
        out.append({
            "name": text(getattr(r, "Name", None)),
            "category_type": attr(room_cat, "Type"),
            "category_name": text(room_cat),
            "units": int_attr(r, "Units", 0) or 0,
            "source": int_attr(r, "Source", 0) or 0,
            "avail_rooms": int_attr(r, "AvailRooms"),
            "occupancy": int_attr(occ, "Occupancy"),
            "adults": int_attr(occ, "Adults"),
            "children": int_attr(occ, "Children"),
        })
    return out


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------


def parse_prices(prices_node: Any) -> dict:
    """Extract the first ``Price`` of ``Prices`` and its ``TotalFixAmounts``.

    Juniper may return multiple ``Price`` blocks (sale / cost / agency); the
    agent layer only cares about the primary total that the customer pays.
    Shape matches the XML contract in
    ``uploads/hotel-api-0.md`` lines 43-50.
    """
    price_list = iter_list(getattr(prices_node, "Price", None)) if prices_node is not None else []
    if not price_list:
        return {
            "currency": "",
            "total_price": "0",
            "nett_price": "0",
            "service": "",
            "service_taxes": "",
            "taxes_included": None,
        }
    price = price_list[0]
    total_fix = getattr(price, "TotalFixAmounts", None)
    service = getattr(total_fix, "Service", None) if total_fix is not None else None
    svc_taxes = getattr(total_fix, "ServiceTaxes", None) if total_fix is not None else None
    return {
        "currency": attr(price, "Currency"),
        "total_price": attr(total_fix, "Gross", "0") or "0",
        "nett_price": attr(total_fix, "Nett", "0") or "0",
        "service": attr(service, "Amount"),
        "service_taxes": attr(svc_taxes, "Amount"),
        "taxes_included": bool_attr(svc_taxes, "Included") if svc_taxes is not None else None,
    }


# ---------------------------------------------------------------------------
# CancellationPolicy
# ---------------------------------------------------------------------------


def parse_cancellation_policy(node: Any) -> dict | None:
    """Parse ``CancellationPolicy`` into a structured dict.

    XML contract (sample from ``agent-tools/3c188552-...txt`` lines 2701-2709):

        <CancellationPolicy CurrencyCode="EUR">
          <FirstDayCostCancellation Hour="00:00">2019-11-13</FirstDayCostCancellation>
          <PolicyRules>
            <Rule From="0" To="3"
                  DateFrom="2019-11-17" DateFromHour="00:00"
                  DateTo="2019-11-21"   DateToHour="00:00"
                  Type="V"
                  FixedPrice="0" PercentPrice="100"
                  Nights="0" ApplicationTypeNights="Average"/>
          </PolicyRules>
        </CancellationPolicy>

    Rule attribute notes (from the official docs — these trip up first-time
    integrators):

    * ``@PercentPrice`` (NOT ``@Percent``) is the cancellation-fee percentage.
    * ``@From`` / ``@To`` are counted in **days** (From = days remaining
      before the ApplicationDate, To = upper bound of the window).
    * ``@Type`` — ``S`` = fixed schedule / ``V`` = per check-in date /
      ``R`` = per reservation date.
    * ``@Nights`` + ``@ApplicationTypeNights`` — used when the policy
      charges N nights' worth (``Average`` / ``FirstNight`` /
      ``MostExpensiveNight``).
    * ``@FirstNightPrice`` / ``@MostExpensiveNightPrice`` — set only when the
      application type requires them.

    Returns ``None`` when the node is absent (the common case on Avail: only
    returned when ``AdvancedOptions/ShowCancellationPolicies=true`` AND the
    supplier is a directly contracted hotel).
    """
    if node is None:
        return None
    first_day = getattr(node, "FirstDayCostCancellation", None)
    rules_wrapper = getattr(node, "PolicyRules", None)
    rules_nodes = iter_list(getattr(rules_wrapper, "Rule", None)) if rules_wrapper is not None else []
    rules = [
        {
            "type": attr(r, "Type"),
            "from_days": int_attr(r, "From"),
            "to_days": int_attr(r, "To"),
            "date_from": attr(r, "DateFrom"),
            "date_from_hour": attr(r, "DateFromHour"),
            "date_to": attr(r, "DateTo"),
            "date_to_hour": attr(r, "DateToHour"),
            "fixed_price": attr(r, "FixedPrice"),
            "percent_price": attr(r, "PercentPrice"),
            "nights": int_attr(r, "Nights"),
            "application_type_nights": attr(r, "ApplicationTypeNights"),
            "first_night_price": attr(r, "FirstNightPrice"),
            "most_expensive_night_price": attr(r, "MostExpensiveNightPrice"),
        }
        for r in rules_nodes
    ]
    return {
        "currency": attr(node, "CurrencyCode"),
        "first_day_cost_date": text(first_day),
        "first_day_cost_hour": attr(first_day, "Hour"),
        "description": text(getattr(node, "Description", None)),
        "rules": rules,
    }


# ---------------------------------------------------------------------------
# AdditionalElements — HotelOffers / HotelSupplements
# ---------------------------------------------------------------------------


def parse_offers(additional_node: Any) -> list[dict]:
    """Extract ``AdditionalElements/HotelOffers/HotelOffer[*]``."""
    if additional_node is None:
        return []
    wrapper = getattr(additional_node, "HotelOffers", None)
    offers = iter_list(getattr(wrapper, "HotelOffer", None)) if wrapper is not None else []
    return [
        {
            "code": attr(o, "Code"),
            "category": attr(o, "Category"),
            "begin": attr(o, "Begin"),
            "end": attr(o, "End"),
            "room_category": attr(o, "RoomCategory"),
            "name": text(getattr(o, "Name", None)),
            "description": text(getattr(o, "Description", None)),
        }
        for o in offers
    ]


def parse_supplements(additional_node: Any) -> list[dict]:
    """Extract ``AdditionalElements/HotelSupplements/HotelSupplement[*]``."""
    if additional_node is None:
        return []
    wrapper = getattr(additional_node, "HotelSupplements", None)
    items = iter_list(getattr(wrapper, "HotelSupplement", None)) if wrapper is not None else []
    return [
        {
            "code": attr(s, "Code"),
            "name": text(getattr(s, "Name", None)),
            "description": text(getattr(s, "Description", None)),
            "direct_payment": bool_attr(s, "DirectPayment"),
        }
        for s in items
    ]


# ---------------------------------------------------------------------------
# BookingRules-specific sub-structures
# ---------------------------------------------------------------------------


def parse_booking_code(node: Any) -> dict:
    """Extract ``HotelOption/BookingCode`` (``@ExpirationDate`` + text).

    ``BookingCode`` is the critical handle for HotelBooking — it has a
    10-minute TTL (per docs §HotelBookingRules Response). Returns empty
    strings when absent so callers can probe without None-guarding.
    """
    if node is None:
        return {"value": "", "expires_at": ""}
    # Some codes come through as a bare string (rare); ``_value_1`` only exists
    # on complex zeep nodes. Fall back to ``str(node)`` for the scalar case.
    value = text(node)
    if not value and isinstance(node, str):
        value = node
    return {
        "value": value,
        "expires_at": attr(node, "ExpirationDate"),
    }


def parse_hotel_content_short(node: Any) -> dict:
    """Extract ``PriceInformation/HotelContent`` (the trimmed form returned
    inside BookingRules — not the full HotelContent response).

    Real XML (see ``agent-tools/3c188552-...txt`` lines 2740-2753):

        <HotelContent Code="JP046300">
          <HotelName>APARTAMENTOS ALLSUN PIL-LARI PLAYA</HotelName>
          <Zone JPDCode="JPD086855" Code="49435"/>
          <HotelCategory Type="3est">3 Stars</HotelCategory>
          <HotelType Type="GEN">General</HotelType>
          <Address>
            <Address>Calle Marbella 24</Address>
            <Latitude>39.564713</Latitude>
            <Longitude>2.627979</Longitude>
          </Address>
        </HotelContent>

    Note: the ``Address/Address`` double-nesting mirrors the real XML — do
    not flatten at parse time.
    """
    if node is None:
        return {
            "code": "", "jpcode": "", "name": "",
            "category": "", "category_type": "",
            "type": "", "type_code": "",
            "jpdcode": "", "zone_code": "",
            "address": "", "latitude": "", "longitude": "",
        }
    zone = getattr(node, "Zone", None)
    category = getattr(node, "HotelCategory", None)
    hotel_type = getattr(node, "HotelType", None)
    address_node = getattr(node, "Address", None)
    # ``Address`` is itself a wrapper that contains another ``Address`` child
    # holding the street. Walk one level in.
    street = ""
    latitude = ""
    longitude = ""
    if address_node is not None:
        street = text(getattr(address_node, "Address", None))
        latitude = text(getattr(address_node, "Latitude", None))
        longitude = text(getattr(address_node, "Longitude", None))
    return {
        "code": attr(node, "Code"),
        "jpcode": attr(node, "JPCode") or attr(node, "Code"),
        "name": text(getattr(node, "HotelName", None)),
        "category": text(category),
        "category_type": attr(category, "Type"),
        "type": text(hotel_type),
        "type_code": attr(hotel_type, "Type"),
        "jpdcode": attr(zone, "JPDCode"),
        "zone_code": attr(zone, "Code"),
        "address": street,
        "latitude": latitude,
        "longitude": longitude,
    }


def parse_comments(optional_elements_node: Any) -> list[dict]:
    """Extract ``OptionalElements/Comments/Comment[*]`` — free-text hotel
    remarks (additional taxes, promo explanations, pool closures, ...).

    Per docs: "very important to show the same on your end as the mentioned
    may include additional taxes, additional considerations and/or
    additional features, among others...". CDATA content comes through as
    regular text.
    """
    if optional_elements_node is None:
        return []
    wrapper = getattr(optional_elements_node, "Comments", None)
    comments = iter_list(getattr(wrapper, "Comment", None)) if wrapper is not None else []
    return [
        {"type": attr(c, "Type"), "text": text(c)}
        for c in comments
    ]


def parse_preferences(optional_elements_node: Any) -> list[dict]:
    """Extract ``OptionalElements/Preferences/Preference[*]``
    (supplier-specific booking preferences, only populated on some suppliers)."""
    if optional_elements_node is None:
        return []
    wrapper = getattr(optional_elements_node, "Preferences", None)
    prefs = iter_list(getattr(wrapper, "Preference", None)) if wrapper is not None else []
    return [
        {
            "code": attr(p, "Code"),
            "description": text(getattr(p, "Description", None)),
        }
        for p in prefs
    ]


def parse_allowed_credit_cards(optional_elements_node: Any) -> list[dict]:
    """Extract ``OptionalElements/AllowedCreditCards/CreditCard[*]``
    (payment-in-destination bookings only)."""
    if optional_elements_node is None:
        return []
    wrapper = getattr(optional_elements_node, "AllowedCreditCards", None)
    cards = iter_list(getattr(wrapper, "CreditCard", None)) if wrapper is not None else []
    return [
        {"code": attr(c, "Code"), "name": text(c)}
        for c in cards
    ]


def parse_required_fields(node: Any) -> dict:
    """Extract ``HotelRequiredFields`` as a structured template.

    Per docs §Required fields (agent-tools lines 3013-3014):

        "You should consider mandatory all nodes and attributes that are
         returned in the HotelRequiredFields, whether they have a value or
         not. If a node is not returned it will not be necessary to send it
         when booking. Additionally, consider that the returned information
         is generic, and therefore not related: in any case you should not
         send this information when booking, but instead, you should create
         the request from scratch."

    We surface a pragmatic structured view the HotelBooking builder can
    inspect:

        {
          "paxes": [
            {"id_pax": "1", "fields": ["Name", "Surname", "PhoneNumber",
                                       "Address", "City", "Country",
                                       "PostalCode", "Age"]},
            {"id_pax": "2", "fields": ["Age"]},
          ],
          "holder": {"rel_pax_ids": ["1"]},
          "has_hotel_element":  bool,
          "has_booking_code":   bool,
          "hotel_codes":        ["JP046300"],  # from HotelBookingInfo/HotelCode
          "check_in":           "2019-11-20",  # HotelBookingInfo/@Start
          "check_out":          "2019-11-22",
        }
    """
    empty = {
        "paxes": [], "holder": {"rel_pax_ids": []},
        "has_hotel_element": False, "has_booking_code": False,
        "hotel_codes": [], "check_in": "", "check_out": "",
    }
    if node is None:
        return empty
    booking = getattr(node, "HotelBooking", None)
    if booking is None:
        return empty

    # ----- Paxes -----
    paxes_wrapper = getattr(booking, "Paxes", None)
    pax_nodes = iter_list(getattr(paxes_wrapper, "Pax", None)) if paxes_wrapper is not None else []
    paxes: list[dict] = []
    for p in pax_nodes:
        # Collect the names of child elements that are returned — each one
        # indicates a field the supplier requires for this pax.
        fields: list[str] = []
        for field_name in (
            "Name", "Surname", "Age", "PhoneNumbers", "PhoneNumber",
            "Address", "City", "Country", "PostalCode", "Email",
            "PassportNumber", "PassportCountry", "PassportExpirationDate",
            "Birthdate", "Nationality", "IdentificationDocument",
        ):
            if getattr(p, field_name, None) is not None:
                fields.append(field_name)
        paxes.append({
            "id_pax": attr(p, "IdPax"),
            "fields": fields,
        })

    # ----- Holder -----
    holder = getattr(booking, "Holder", None)
    rel_pax_ids: list[str] = []
    if holder is not None:
        rel_paxes = iter_list(getattr(holder, "RelPax", None))
        rel_pax_ids = [attr(rp, "IdPax") for rp in rel_paxes if attr(rp, "IdPax")]

    # ----- Elements -----
    elements = getattr(booking, "Elements", None)
    hotel_element = getattr(elements, "HotelElement", None) if elements is not None else None
    has_booking_code = False
    hotel_codes: list[str] = []
    check_in = ""
    check_out = ""
    if hotel_element is not None:
        has_booking_code = getattr(hotel_element, "BookingCode", None) is not None
        info_node = getattr(hotel_element, "HotelBookingInfo", None)
        if info_node is not None:
            check_in = attr(info_node, "Start")
            check_out = attr(info_node, "End")
            hc = getattr(info_node, "HotelCode", None)
            for c in iter_list(hc):
                code = text(c)
                if code:
                    hotel_codes.append(code)

    return {
        "paxes": paxes,
        "holder": {"rel_pax_ids": rel_pax_ids},
        "has_hotel_element": hotel_element is not None,
        "has_booking_code": has_booking_code,
        "hotel_codes": hotel_codes,
        "check_in": check_in,
        "check_out": check_out,
    }


# ---------------------------------------------------------------------------
# HotelBooking / ReadBooking / CancelBooking — shared Reservation shapes
# ---------------------------------------------------------------------------
#
# Official docs (``uploads/hotel-api-0.md`` lines 3478-3726 / 3762-3890 /
# 3976-4025) show ``BookingRS / ReadBookingRS / CancelRS`` all share the same
# ``Reservations/Reservation`` container. Parsing each sub-structure once
# here keeps §11.7 + future CancelBooking refactors aligned.


# Juniper Reservation @Status → normalised internal semantics.
# Source: docs §HotelBooking Response lines 3481-3488.
_RESERVATION_STATUS_MAP: dict[str, str] = {
    "PAG": "confirmed",   # Booking confirmed and paid
    "CON": "confirmed",   # Booking confirmed
    "CAC": "cancelled",   # Booking cancelled
    "CAN": "cancelled",   # Booking cancelled (alt. spelling per docs)
    "PRE": "pending",     # Booking on request
    "PDI": "pending",     # Booking on request (alt.)
    "QUO": "quotation",   # Quotation (WebService-paid bookings)
    "TAR": "pending",     # Pending credit card payment
}


def normalise_reservation_status(status: str) -> str:
    """Map Juniper's 3-letter Reservation status to internal semantics.

    Unknown codes fall back to ``"unknown"`` rather than silently aliasing
    to ``confirmed`` (the previous bug in ``serialize_booking`` defaulted
    to that, which caused cancelled bookings to show as confirmed).
    """
    if not status:
        return ""
    return _RESERVATION_STATUS_MAP.get(status.upper(), "unknown")


def parse_pax(pax_node: Any) -> dict:
    """Extract a single ``Pax`` into a flat contact dict.

    Shape matches docs §Pax (common/genericworkflow). Missing sub-elements
    are omitted from output so dict equality in tests is predictable.
    """
    phones_wrapper = getattr(pax_node, "PhoneNumbers", None)
    phone_nodes = iter_list(getattr(phones_wrapper, "PhoneNumber", None)) if phones_wrapper is not None else []
    phones = [
        {"type": attr(pn, "Type"), "number": text(pn)}
        for pn in phone_nodes if text(pn)
    ]
    doc_node = getattr(pax_node, "Document", None)
    document = None
    if doc_node is not None and text(doc_node):
        document = {"type": attr(doc_node, "Type"), "value": text(doc_node)}
    return {
        "id_pax": attr(pax_node, "IdPax"),
        "name": text(getattr(pax_node, "Name", None)),
        "surname": text(getattr(pax_node, "Surname", None)),
        "age": text(getattr(pax_node, "Age", None)),
        "email": text(getattr(pax_node, "Email", None)),
        "address": text(getattr(pax_node, "Address", None)),
        "city": text(getattr(pax_node, "City", None)),
        "country": text(getattr(pax_node, "Country", None)),
        "postal_code": text(getattr(pax_node, "PostalCode", None)),
        "nationality": text(getattr(pax_node, "Nationality", None)),
        "document": document,
        "phones": phones,
    }


def parse_paxes_reservation(paxes_node: Any) -> list[dict]:
    """Extract ``Reservation/Paxes/Pax[*]`` (the booked guests).

    Note: the response always includes the holder as an extra Pax (per
    docs line 3492), so ``len(paxes) == requested_paxes + 1`` on most
    suppliers.
    """
    if paxes_node is None:
        return []
    return [parse_pax(p) for p in iter_list(getattr(paxes_node, "Pax", None))]


def parse_holder_reservation(holder_node: Any, paxes: list[dict]) -> dict:
    """Resolve ``Reservation/Holder/RelPax/@IdPax`` → the matching Pax dict.

    Returns ``{"rel_pax_id": "4", "pax": {...}}`` so callers have direct
    access to the holder's name / email / phone without re-walking the
    Paxes list.
    """
    if holder_node is None:
        return {"rel_pax_id": "", "pax": None}
    rel_pax = getattr(holder_node, "RelPax", None)
    # Zeep returns a list when there are multiple RelPax; holders are
    # always single per docs but tolerate the list shape.
    if isinstance(rel_pax, (list, tuple)):
        rel_pax = rel_pax[0] if rel_pax else None
    id_pax = attr(rel_pax, "IdPax") if rel_pax is not None else ""
    matched = next((p for p in paxes if p.get("id_pax") == id_pax), None)
    return {"rel_pax_id": id_pax, "pax": matched}


def parse_reservation_comments(comments_node: Any) -> list[dict]:
    """Extract ``Reservation/Comments/Comment[*]`` — booking-level comments.

    Different from :func:`parse_comments` (which reads ``OptionalElements/
    Comments`` for HotelBookingRules). Reservation comments are typed:
    ``RES`` (general) or ``INT`` (internal).
    """
    if comments_node is None:
        return []
    return [
        {"type": attr(c, "Type"), "text": text(c)}
        for c in iter_list(getattr(comments_node, "Comment", None))
    ]


def parse_agencies_data(agencies_node: Any) -> list[dict]:
    """Extract ``AgenciesData/AgencyData[*]`` — agency account info.

    Useful for diagnostics (which Juniper account the booking came from)
    and for the reselling flow. Ignored by the AI-agent layer but kept
    in the serializer output for ops/support.
    """
    if agencies_node is None:
        return []
    out: list[dict] = []
    for a in iter_list(getattr(agencies_node, "AgencyData", None)):
        out.append({
            "referenced_agency": text(getattr(a, "ReferencedAgency", None)).lower() == "true",
            "agency_code": text(getattr(a, "AgencyCode", None)),
            "agency_name": text(getattr(a, "AgencyName", None)),
            "agency_handled_by": text(getattr(a, "AgencyHandledBy", None)),
            "agency_email": text(getattr(a, "AgencyEmail", None)),
            "agency_reference": text(getattr(a, "AgencyReference", None)),
        })
    return out


def parse_external_info(external_node: Any) -> dict:
    """Extract ``HotelItem/ExternalInfo`` — supplier-side identifiers.

    Critical for ops: the ``external_locator`` is the hotel-chain's own
    confirmation number, which is what the guest sees at check-in. The
    ``hotel_confirmation_number`` is typically provided by direct-connect
    suppliers.
    """
    if external_node is None:
        return {
            "supplier_code": "",
            "external_locator": "",
            "external_cancellation_locator": "",
            "hotel_confirmation_number": "",
            "transaction_ids": [],
        }
    supplier = getattr(external_node, "Supplier", None)
    tx_wrapper = getattr(external_node, "ExternalTransactionIDS", None)
    tx_ids = [
        {"type": attr(t, "Type"), "value": attr(t, "Value")}
        for t in iter_list(getattr(tx_wrapper, "ExternalTransactionID", None) if tx_wrapper is not None else None)
    ]
    return {
        "supplier_code": attr(supplier, "Code"),
        "external_locator": text(getattr(external_node, "ExternalLocator", None)),
        "external_cancellation_locator": text(getattr(external_node, "ExternalCancellationLocator", None)),
        "hotel_confirmation_number": text(getattr(external_node, "HotelConfirmationNumber", None)),
        "transaction_ids": tx_ids,
    }


def parse_hotel_info_reservation(info_node: Any) -> dict:
    """Extract ``HotelItem/HotelInfo`` — the *flat* variant Juniper returns
    inside Reservation responses.

    Distinct from :func:`parse_hotel_info` (used by HotelAvail) because
    this one carries the JPCode / JPDCode / DestinationZone attributes
    directly on ``HotelInfo`` (docs lines 3542-3554), whereas the
    availability-response ``HotelInfo`` lives one level deeper on
    ``HotelResult`` and doesn't always include them.
    """
    if info_node is None:
        return {
            "code": "", "jpcode": "", "jpdcode": "", "destination_zone": "",
            "name": "", "category": "", "category_type": "", "address": "",
        }
    cat_node = getattr(info_node, "HotelCategory", None)
    if isinstance(cat_node, (list, tuple)):
        cat_node = cat_node[0] if cat_node else None
    return {
        "code": attr(info_node, "Code"),
        "jpcode": attr(info_node, "JPCode") or attr(info_node, "Code"),
        "jpdcode": attr(info_node, "JPDCode"),
        "destination_zone": attr(info_node, "DestinationZone"),
        "name": text(getattr(info_node, "Name", None)),
        "category": text(cat_node),
        "category_type": attr(cat_node, "Type"),
        "address": text(getattr(info_node, "Address", None)),
    }


def parse_rooms_reservation(rooms_node: Any) -> list[dict]:
    """Extract ``HotelItem/HotelRooms/HotelRoom[*]``.

    Distinct from :func:`parse_rooms` because the reservation shape has
    ``RelPaxes/RelPax[@IdPax]`` (room-to-pax mapping) whereas the
    availability shape has ``RoomOccupancy``.
    """
    if rooms_node is None:
        return []
    rooms: list[dict] = []
    for r in iter_list(getattr(rooms_node, "HotelRoom", None)):
        room_cat = getattr(r, "RoomCategory", None)
        rel_paxes_wrapper = getattr(r, "RelPaxes", None)
        rel_pax_ids = [
            attr(rp, "IdPax")
            for rp in iter_list(getattr(rel_paxes_wrapper, "RelPax", None) if rel_paxes_wrapper is not None else None)
            if attr(rp, "IdPax")
        ]
        rooms.append({
            "source": attr(r, "Source"),
            "name": text(getattr(r, "Name", None)),
            "description": text(getattr(r, "Description", None)),
            "category_type": attr(room_cat, "Type"),
            "category_name": text(room_cat),
            "rel_pax_ids": rel_pax_ids,
        })
    return rooms


def parse_hotel_item(hotel_item_node: Any) -> dict:
    """Extract ``Reservation/Items/HotelItem`` into a structured dict.

    Shape follows docs §HotelBooking Response lines 3511-3586. All
    sub-parsers share ``_parsers.py`` helpers so future Avail /
    BookingRules tweaks flow through to Reservation parsing too.
    """
    if hotel_item_node is None:
        return {}
    price_info = hotel_item_node  # Prices live directly on HotelItem
    prices = parse_prices(getattr(price_info, "Prices", None))
    additional = getattr(hotel_item_node, "AdditionalElements", None)
    return {
        "item_id": attr(hotel_item_node, "ItemId"),
        "status": attr(hotel_item_node, "Status"),
        "check_in": attr(hotel_item_node, "Start"),
        "check_out": attr(hotel_item_node, "End"),
        "external_info": parse_external_info(getattr(hotel_item_node, "ExternalInfo", None)),
        "tax_reference": text(getattr(hotel_item_node, "TaxReference", None)),
        "hotel_info": parse_hotel_info_reservation(getattr(hotel_item_node, "HotelInfo", None)),
        "board": parse_board(getattr(hotel_item_node, "Board", None)),
        "rooms": parse_rooms_reservation(getattr(hotel_item_node, "HotelRooms", None)),
        "prices": prices,
        "cancellation": parse_cancellation_policy(getattr(hotel_item_node, "CancellationPolicy", None)),
        "comments": [
            {"type": attr(c, "Type"), "text": text(c)}
            for c in iter_list(getattr(getattr(hotel_item_node, "Comments", None), "Comment", None))
        ] if getattr(hotel_item_node, "Comments", None) is not None else [],
        "offers": parse_offers(additional),
        "supplements": parse_supplements(additional),
    }
