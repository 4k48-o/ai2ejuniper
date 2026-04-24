"""Juniper SOAP client wrapper with async-safe execution via asyncio.to_thread()."""

import asyncio
import logging
import time
from datetime import date, datetime, timezone
from typing import Any

from juniper_ai.app.config import settings
from juniper_ai.app.juniper.supplier import HotelSupplier
from juniper_ai.app.juniper.exceptions import (
    JuniperFaultError,
    NoResultsError,
    PriceChangedError,
    RoomUnavailableError,
    SOAPTimeoutError,
)
from juniper_ai.app.metrics import (
    record_hotel_avail_batch,
    record_hotel_avail_candidates,
)
from juniper_ai.app.juniper.serializers import (
    serialize_booking,
    serialize_booking_rules,
    serialize_check_avail,
    serialize_hotel_avail,
    serialize_read_booking,
)

logger = logging.getLogger(__name__)

# WebServiceJP.asmx exposes multiple SOAP ports; zeep's default `client.service` is not Avail/Static.
_JP_SERVICE = "WebServiceJP"
_STATIC_PORT = "StaticDataTransactions"
_AVAIL_PORT = "AvailTransactions"
_BOOK_PORT = "BookTransactions"
_CHECK_PORT = "CheckTransactions"

_STATIC_OPS = frozenset({
    "ZoneList",
    "HotelPortfolio",
    "HotelContent",
    "HotelCatalogueData",
    "GenericDataCatalogue",
    "HotelList",
})
_AVAIL_OPS = frozenset({
    "HotelAvail",
    "HotelAvailCalendar",
    "HotelFutureRates",
})
_BOOK_OPS = frozenset({
    "CancelBooking",
    "HotelBooking",
    "HotelConfirmModify",
    "HotelModify",
    "ReadBooking",
})
_CHECK_OPS = frozenset({
    "HotelBookingRules",
    "HotelCheckAvail",
})
_RQ_WRAPPERS: dict[str, str] = {
    "ZoneList": "ZoneListRQ",
    "HotelPortfolio": "HotelPortfolioRQ",
    "HotelContent": "HotelContentRQ",
    "HotelCatalogueData": "HotelCatalogueDataRQ",
    "GenericDataCatalogue": "GenericDataCatalogueRQ",
    "HotelList": "HotelListRQ",
    "HotelAvail": "HotelAvailRQ",
    "HotelAvailCalendar": "HotelAvailCalendarRQ",
    "HotelFutureRates": "HotelFutureRatesRQ",
    "HotelBookingRules": "HotelBookingRulesRQ",
    "HotelCheckAvail": "HotelCheckAvailRQ",
    "HotelBooking": "HotelBookingRQ",
    "ReadBooking": "ReadRQ",
    "CancelBooking": "CancelRQ",
    "HotelModify": "HotelModifyRQ",
    "HotelConfirmModify": "HotelConfirmModifyRQ",
}

SOAP_TIMEOUT = 30  # seconds
MAX_RETRIES = 2
RETRY_DELAYS = [1, 3]  # exponential backoff seconds


class JuniperClient(HotelSupplier):
    """Wraps zeep SOAP calls for the Juniper Hotel API."""

    def __init__(self):
        self._client = None
        self._initialized = False

    def _ensure_client(self):
        if self._initialized:
            return
        try:
            from requests import Session
            from zeep import Client
            from zeep.transports import Transport

            session = Session()
            session.headers.update({
                "Accept-Encoding": "gzip",
                "Content-Type": "text/xml;charset=UTF-8",
            })
            transport = Transport(timeout=SOAP_TIMEOUT, operation_timeout=SOAP_TIMEOUT, session=session)
            # Flicknmix / xml-uat: JP/WebServiceJP.asmx (supersedes legacy JP_HotelAvail.asmx path on other hosts)
            base = settings.juniper_api_url.rstrip("/")
            wsdl_url = f"{base}/webservice/JP/WebServiceJP.asmx?WSDL"
            self._client = Client(wsdl_url, transport=transport)
            self._initialized = True
            logger.info("Juniper SOAP client initialized: %s", settings.juniper_api_url)
        except Exception as e:
            logger.error("Failed to initialize Juniper SOAP client: %s", e)
            raise

    def _login_element(self) -> dict:
        return {"Email": settings.juniper_email, "Password": settings.juniper_password}

    @staticmethod
    def _base_header_fields() -> dict[str, str]:
        # Juniper WebServiceJP headers expected in each *RQ object.
        return {"Version": "1.1", "Language": "en"}

    @staticmethod
    def _operation_header_fields(operation_name: str) -> dict[str, Any]:
        # Some request types define TimeStamp and zeep needs an explicit datetime value.
        with_timestamp = {"HotelAvail", "HotelFutureRates", "HotelCheckAvail", "HotelBookingRules"}
        fields: dict[str, Any] = {}
        if operation_name in with_timestamp:
            fields["TimeStamp"] = datetime.now(timezone.utc)
        # ``@Context`` is an XML attribute on the *RQ wrapper element (not on
        # AdvancedOptions). Juniper's docs recommend sending it on every
        # HotelAvail; the supplier routes requests through different
        # availability pools based on this value (FULLAVAIL / SINGLEAVAIL /
        # CACHEROBOT / ...). See ``doc/juniper-hotel-api.md`` §Context.
        if operation_name == "HotelAvail" and settings.juniper_avail_context:
            fields["Context"] = settings.juniper_avail_context
        # HotelCheckAvail also accepts ``@Context`` on the RQ wrapper; docs
        # recommend SINGLEAVAIL or VALUATION for revalidation hits.
        if operation_name == "HotelCheckAvail" and settings.juniper_check_avail_context:
            fields["Context"] = settings.juniper_check_avail_context
        # HotelBookingRules @Context — docs recommend VALUATION / BOOKING /
        # PAYMENT so Juniper routes the call through the valuation pool
        # rather than the availability one (uploads/hotel-api-0.md line 2495).
        if operation_name == "HotelBookingRules" and settings.juniper_booking_rules_context:
            fields["Context"] = settings.juniper_booking_rules_context
        # IMPORTANT: ``JP_HotelBooking`` root element does **not** accept
        # ``@Context`` per the live UAT WSDL signature (surfaced as
        # ``got an unexpected keyword argument 'Context'`` during
        # 2026-04-23 end-to-end smoke). The ``settings.juniper_booking_context``
        # setting is kept as a no-op passthrough so existing .env snippets
        # don't explode, but we never inject it on the request. If Juniper
        # later extends the WSDL, flip the guard below back on.
        return fields

    @staticmethod
    def _build_search_segments_hotels(
        check_in: date | str | None,
        check_out: date | str | None,
        hotel_code: str | None,
    ) -> dict[str, Any] | None:
        """Build the shared ``SearchSegmentsHotels`` verification block.

        Used by both ``HotelCheckAvail`` and ``HotelBookingRules`` — Juniper
        cross-checks the ``RatePlanCode`` against ``@Start`` / ``@End`` +
        ``HotelCode`` and returns ``warnCheckNotPossible`` when they drift.

        Returns ``None`` when none of the inputs are supplied (caller then
        skips the node entirely, which Juniper accepts as a "no-verify" hit).

        Payload shape
        -------------
        ``SearchSegmentHotels`` is a ``JP_SearchSegmentHotels`` element that
        extends ``JP_SearchSegmentBase``. The base type carries ``Start`` /
        ``End`` both as an xs:date complexType **attribute** (what Juniper
        actually emits on the wire — ``<SearchSegmentHotels Start=".."
        End=".." />``) and as a free-form content model. Zeep therefore
        needs the values placed in two slots:

          * top-level ``Start`` / ``End`` keys → XML attributes
          * ``_value_1`` subdict             → base type content model

        Omitting either slot causes zeep's Date serializer to resolve the
        attribute to ``NotSet`` (a ``_StaticIdentity`` class) and crash
        with ``'_StaticIdentity' object has no attribute 'year'`` — this is
        the exact crash surfaced during UAT 2026-04-23 smoke testing of
        HotelCheckAvail. We mirror the shape proven in ``_hotel_avail_batch``
        (lines 675-679) which has been passing UAT since §11.1.
        """
        if not (check_in or check_out or hotel_code):
            return None

        segment_base: dict[str, Any] = {}
        if check_in:
            segment_base["Start"] = (
                check_in if isinstance(check_in, str) else check_in.strftime("%Y-%m-%d")
            )
        if check_out:
            segment_base["End"] = (
                check_out if isinstance(check_out, str) else check_out.strftime("%Y-%m-%d")
            )

        block: dict[str, Any] = {}
        if segment_base:
            block["SearchSegmentHotels"] = {
                "_value_1": dict(segment_base),
                **segment_base,
            }
        if hotel_code:
            block["HotelCodes"] = {"HotelCode": [hotel_code]}
        return block or None

    @staticmethod
    def _build_rel_paxes_dist(
        pax_ids: list[int],
        *,
        rel_paxes_dist: list[list[int]] | None = None,
    ) -> dict[str, Any]:
        """Build ``Elements/HotelElement/RelPaxesDist`` (room→pax mapping).

        Juniper requires a RelPaxesDist on every ``HotelBooking`` payload: each
        ``RelPaxDist`` block is one room, containing the IdPax values of every
        guest staying in that room (see ``doc/juniper-hotel-api.md`` §2,
        request table rows ``HotelElement/RelPaxesDist`` +
        ``RelPaxDist/RelPaxes``).

        Parameters
        ----------
        pax_ids:
            Full flat list of ``IdPax`` values present in the top-level
            ``Paxes`` block.
        rel_paxes_dist:
            Optional explicit room split — list-of-lists where each inner
            list is the IdPax roster of one room. Must cover ``pax_ids``
            exactly once.

        When ``rel_paxes_dist`` is ``None`` we default to a single room
        containing every pax (matches how 90% of bookings come in from the
        agent flow — one room, 1-4 guests — and matches the docs example at
        ``uploads/hotel-api-0.md`` §HotelBooking request example L889).
        """
        if rel_paxes_dist is None:
            rel_paxes_dist = [list(pax_ids)]

        rooms: list[dict[str, Any]] = []
        for room_pax_ids in rel_paxes_dist:
            if not room_pax_ids:
                raise ValueError(
                    "RelPaxesDist rooms cannot be empty — each RelPaxDist "
                    "must contain at least one RelPax/@IdPax."
                )
            rooms.append({
                "RelPaxes": {
                    "RelPax": [{"IdPax": int(pid)} for pid in room_pax_ids],
                },
            })

        return {"RelPaxDist": rooms}

    @staticmethod
    def _build_price_range(
        total_price: str | float | None,
        currency: str,
        tolerance_pct: float,
    ) -> dict[str, Any] | None:
        """Build ``HotelBookingInfo/Price/PriceRange`` with a tolerance band.

        Juniper rejects the booking if the server-side price falls outside
        ``[Minimum, Maximum]`` — this is how we defend against silent upward
        price drift between HotelBookingRules and HotelBooking. We always
        pass ``Minimum=0`` (downward drift is good for the guest; no reason
        to fail on it) and set ``Maximum = total * (1 + tolerance_pct)``.

        Returns ``None`` when ``total_price`` is missing / unparseable, so
        the caller can omit the node rather than send an all-zeros window
        that Juniper would reject.
        """
        if total_price in (None, ""):
            return None
        try:
            total = float(total_price)
        except (TypeError, ValueError):
            return None
        if total <= 0:
            return None
        maximum = total * (1.0 + max(0.0, float(tolerance_pct)))
        return {
            "PriceRange": {
                "Currency": currency or "EUR",
                "Minimum": f"{0.0:.2f}",
                "Maximum": f"{maximum:.2f}",
            },
        }

    # Juniper error codes that mean "no inventory for this query" rather
    # than "the request itself was malformed". These are expected outcomes
    # of availability searches (some JPCode batches will legitimately have
    # zero rooms) and MUST NOT abort a multi-batch search. Observed in UAT:
    # Palma returns 0 ``HotelOption``s silently, while Dubai returns the
    # same condition as ``<Errors><Error Code="NO_AVAIL_FOUND"/></Errors>``
    # — we normalise both to ``NoResultsError`` so the caller sees one
    # consistent error type and the ``_run_batch`` tolerance path works.
    _SOFT_NO_RESULT_CODES = frozenset({
        "NO_AVAIL_FOUND",  # HotelAvail / HotelCheckAvail — no rooms for the query
    })

    @classmethod
    def _raise_if_response_errors(cls, operation_name: str, response: Any) -> None:
        errors = getattr(response, "Errors", None)
        if not errors:
            return
        error_list = getattr(errors, "Error", None) or []
        if not isinstance(error_list, list):
            error_list = [error_list]
        if not error_list:
            return
        first = error_list[0]
        code = str(getattr(first, "Code", "SOAP_RESPONSE_ERROR") or "SOAP_RESPONSE_ERROR")
        text = str(getattr(first, "Text", "") or f"{operation_name} returned response errors")
        if code in cls._SOFT_NO_RESULT_CODES:
            # Convert to NoResultsError so the batch-level `_run_batch`
            # tolerance path (and any future soft-fail flow) can swallow
            # it without conflating it with hard request-shape errors
            # (REQ_PRACTICE, AUTH_FAILED, etc.) that must surface loudly.
            raise NoResultsError(f"{operation_name}: {code} — {text.strip() or 'no availability'}")
        raise JuniperFaultError(code, text)

    def _normalize_operation_kwargs(self, operation_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Convert legacy internal kwargs into WebServiceJP *RQ payload fields."""
        if operation_name == "ZoneList":
            return {"ZoneListRequest": kwargs.get("ZoneListRequest", {})}

        if operation_name == "HotelPortfolio":
            return kwargs

        if operation_name == "HotelContent":
            return {"HotelContentList": kwargs.get("HotelContentList", {})}

        if operation_name == "HotelCatalogueData":
            return {}

        if operation_name == "GenericDataCatalogue":
            return {"GenericDataCatalogueRequest": kwargs.get("GenericDataCatalogueRequest", {})}

        if operation_name == "HotelList":
            return {"HotelListRequest": kwargs.get("HotelListRequest", {})}

        if operation_name == "HotelAvail":
            payload = {
                "Paxes": kwargs.get("Paxes", {}),
                "HotelRequest": kwargs.get("HotelRequest", {}),
            }
            if "AdvancedOptions" in kwargs:
                payload["AdvancedOptions"] = kwargs["AdvancedOptions"]
            return payload

        if operation_name == "HotelCheckAvail":
            rate_plan_code = kwargs.get("RatePlanCode", "")
            request: dict[str, Any] = {"HotelOption": {"RatePlanCode": rate_plan_code}}
            # SearchSegmentsHotels verification block — optional but strongly
            # recommended so Juniper can confirm the code matches the
            # original search window. Passed through from hotel_check_avail.
            search_segments = kwargs.get("SearchSegmentsHotels")
            if search_segments:
                request["SearchSegmentsHotels"] = search_segments
            return {"HotelCheckAvailRequest": request}

        if operation_name == "HotelBookingRules":
            rate_plan_code = kwargs.get("RatePlanCode", "")
            request: dict[str, Any] = {"HotelOption": {"RatePlanCode": rate_plan_code}}
            # ``SearchSegmentsHotels`` is optional per docs but strongly
            # recommended — Juniper uses it to verify the RatePlanCode
            # still matches the original search (uploads/hotel-api-0.md
            # §HotelBookingRules Request lines 2501-2508). Passed through
            # from ``hotel_booking_rules()``.
            search_segments = kwargs.get("SearchSegmentsHotels")
            if search_segments:
                request["SearchSegmentsHotels"] = search_segments
            payload: dict[str, Any] = {"HotelBookingRulesRequest": request}
            if "AdvancedOptions" in kwargs:
                payload["AdvancedOptions"] = kwargs["AdvancedOptions"]
            return payload

        if operation_name == "HotelBooking":
            # Per ``doc/juniper-hotel-api.md`` §2 and
            # ``uploads/hotel-api-0.md`` HotelBookingRQ definition, the full
            # payload shape is:
            #
            #   Paxes/Pax[*]                                     (required)
            #   Holder/RelPax/@IdPax                             (required)
            #   ExternalBookingReference                         (optional)
            #   Comments/Comment[*]                              (optional)
            #   Elements/HotelElement/
            #     BookingCode                                    (required)
            #     RelPaxesDist/RelPaxDist[*]/RelPaxes/RelPax[*]  (required)
            #     HotelBookingInfo/
            #       @Start, @End                                 (required)
            #       Price/PriceRange/@Currency/@Minimum/@Maximum (required)
            #       HotelCode                                    (required)
            #
            # Missing any "required" field above causes Juniper to fail the
            # request with ``REQ_PRACTICE`` (same error class as the
            # ``DestinationZone`` issue from ticket 1096690).
            booking_code = kwargs.get("BookingCode", "")
            rate_plan_code = kwargs.get("RatePlanCode", "")

            hotel_element: dict[str, Any] = {
                "BookingCode": booking_code or rate_plan_code,
            }
            rel_paxes_dist = kwargs.get("RelPaxesDist")
            if rel_paxes_dist:
                hotel_element["RelPaxesDist"] = rel_paxes_dist

            hotel_booking_info = kwargs.get("HotelBookingInfo")
            if hotel_booking_info:
                hotel_element["HotelBookingInfo"] = hotel_booking_info

            payload: dict[str, Any] = {
                "Paxes": kwargs.get("Paxes", {}),
                "Elements": {"HotelElement": hotel_element},
            }
            holder = kwargs.get("Holder")
            if holder is not None:
                payload["Holder"] = holder

            external_ref = kwargs.get("ExternalBookingReference")
            if external_ref:
                payload["ExternalBookingReference"] = external_ref

            comments = kwargs.get("Comments")
            if comments:
                payload["Comments"] = comments
            return payload

        if operation_name == "ReadBooking":
            return {"ReadRequest": {"ReservationLocator": kwargs.get("Locator", "")}}

        if operation_name == "CancelBooking":
            payload: dict[str, Any] = {"CancelRequest": {"ReservationLocator": kwargs.get("Locator", "")}}
            if kwargs.get("OnlyCancellationFees") is not None:
                payload["CancelRequest"]["OnlyCancellationFees"] = kwargs["OnlyCancellationFees"]
            return payload

        if operation_name == "HotelModify":
            payload: dict[str, Any] = {"ReservationLocator": kwargs.get("Locator", "")}
            if kwargs.get("Start") or kwargs.get("End"):
                payload["SearchSementHotels"] = {
                    "Start": kwargs.get("Start"),
                    "End": kwargs.get("End"),
                }
            return payload

        if operation_name == "HotelConfirmModify":
            return {"ReservationLocator": kwargs.get("ModifyCode", "")}

        return kwargs

    @staticmethod
    def _parse_iso_date(value: str) -> date:
        return date.fromisoformat(value)

    @staticmethod
    def _port_for_operation(operation_name: str) -> str:
        if operation_name in _STATIC_OPS:
            return _STATIC_PORT
        if operation_name in _AVAIL_OPS:
            return _AVAIL_PORT
        if operation_name in _BOOK_OPS:
            return _BOOK_PORT
        if operation_name in _CHECK_OPS:
            return _CHECK_PORT
        raise ValueError(f"Unknown Juniper SOAP operation for port routing: {operation_name}")

    def _call_sync(self, operation_name: str, **kwargs) -> Any:
        """Synchronous SOAP call (runs in thread pool)."""
        self._ensure_client()
        try:
            port = self._port_for_operation(operation_name)
            service = self._client.bind(_JP_SERVICE, port)
            operation = getattr(service, operation_name)
            rq_wrapper = _RQ_WRAPPERS.get(operation_name)
            if not rq_wrapper:
                raise ValueError(f"No RQ wrapper configured for Juniper operation: {operation_name}")
            normalized = self._normalize_operation_kwargs(operation_name, kwargs)
            request_payload = {
                "Login": self._login_element(),
                **self._base_header_fields(),
                **self._operation_header_fields(operation_name),
                **normalized,
            }
            response = operation(**{rq_wrapper: request_payload})
            self._raise_if_response_errors(operation_name, response)
            return response
        except Exception as e:
            error_str = str(e).lower()
            if "timeout" in error_str:
                raise SOAPTimeoutError(f"{operation_name} timed out") from e
            if "fault" in error_str:
                raise JuniperFaultError("SOAP_FAULT", str(e)) from e
            raise

    async def _call_with_retry(self, operation_name: str, **kwargs) -> Any:
        """Call SOAP operation with retry logic, running in thread pool."""
        last_error = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                result = await asyncio.to_thread(self._call_sync, operation_name, **kwargs)
                return result
            except SOAPTimeoutError as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    delay = RETRY_DELAYS[attempt] if attempt < len(RETRY_DELAYS) else RETRY_DELAYS[-1]
                    logger.warning(
                        "SOAP timeout on %s (attempt %d/%d), retrying in %ds",
                        operation_name, attempt + 1, MAX_RETRIES + 1, delay,
                    )
                    await asyncio.sleep(delay)
        raise last_error

    # ---- Static data methods ----

    async def zone_list(self, product_type: str = "HOT") -> list[dict]:
        """Retrieve destination zones from ZoneList SOAP operation."""
        logger.info("ZoneList: product_type=%s", product_type)
        response = await self._call_with_retry(
            "ZoneList",
            ZoneListRequest={"ProductType": product_type},
        )
        zones = []
        zone_list = getattr(response, "ZoneList", None)
        if zone_list:
            for z in getattr(zone_list, "Zone", []):
                zones.append({
                    "jpdcode": str(getattr(z, "JPDCode", "")),
                    "code": str(getattr(z, "Code", "")),
                    "name": str(getattr(z, "Name", "")),
                    "area_type": str(getattr(z, "AreaType", "")),
                    "searchable": bool(getattr(z, "Searchable", False)),
                    "parent_jpdcode": str(getattr(z, "ParentJPDCode", "") or ""),
                })
        return zones

    async def hotel_portfolio(self, page_token: str | None = None, page_size: int = 500) -> dict:
        """Retrieve hotel codes with pagination from HotelPortfolio SOAP operation."""
        logger.info("HotelPortfolio: token=%s, page_size=%d", page_token, page_size)
        kwargs = {"RecordsPerPage": page_size}
        if page_token:
            kwargs["Token"] = page_token
        response = await self._call_with_retry("HotelPortfolio", **kwargs)

        portfolio = getattr(response, "HotelPortfolio", response)
        hotels = []
        for h in getattr(portfolio, "Hotel", []):
            zone = getattr(h, "Zone", None)
            city = getattr(h, "City", None)
            cat = getattr(h, "HotelCategory", None)
            hotels.append({
                "jp_code": str(getattr(h, "JPCode", "")),
                "name": str(getattr(h, "Name", "")),
                "zone_jpdcode": str(getattr(zone, "JPDCode", "")) if zone else "",
                "category_type": str(getattr(cat, "Type", "")) if cat else "",
                "address": str(getattr(h, "Address", "")),
                "latitude": str(getattr(h, "Latitude", "")),
                "longitude": str(getattr(h, "Longitude", "")),
                "city_name": str(getattr(city, "_value_1", getattr(city, "Name", ""))) if city else "",
                "city_jpdcode": str(getattr(city, "JPDCode", "")) if city else "",
            })
        # TotalRecords may be present but None on some UAT responses; getattr default only applies if missing.
        raw_total = getattr(portfolio, "TotalRecords", None)
        try:
            total_records = int(raw_total) if raw_total is not None else 0
        except (TypeError, ValueError):
            total_records = 0

        return {
            "hotels": hotels,
            "next_token": str(getattr(portfolio, "NextToken", "") or ""),
            "total_records": total_records,
        }

    async def hotel_content(self, hotel_codes: list[str]) -> list[dict]:
        """Retrieve hotel details from HotelContent SOAP operation (max 25)."""
        logger.info("HotelContent: %d hotels", len(hotel_codes))
        hotel_list = [{"Code": code} for code in hotel_codes[:25]]
        response = await self._call_with_retry(
            "HotelContent",
            HotelContentList={"Hotel": hotel_list},
        )
        results = []
        for hc in getattr(response, "HotelContent", []):
            time_info = getattr(hc, "TimeInformation", None)
            check_time = getattr(time_info, "CheckTime", None) if time_info else None
            results.append({
                "jp_code": str(getattr(hc, "JPCode", getattr(hc, "Code", ""))),
                "name": str(getattr(hc, "HotelName", "")),
                "images": [str(getattr(img, "FileName", "")) for img in getattr(hc, "Images", {}).get("Image", []) or []] if hasattr(getattr(hc, "Images", None) or {}, "get") else [],
                "descriptions": {str(getattr(d, "Type", "")): str(getattr(d, "_value_1", "")) for d in getattr(hc, "Descriptions", {}).get("Description", []) or []} if hasattr(getattr(hc, "Descriptions", None) or {}, "get") else {},
                "features": [str(getattr(f, "_value_1", "")) for f in getattr(hc, "Features", {}).get("Feature", []) or []] if hasattr(getattr(hc, "Features", None) or {}, "get") else [],
                "check_in_time": str(getattr(check_time, "CheckIn", "")) if check_time else "",
                "check_out_time": str(getattr(check_time, "CheckOut", "")) if check_time else "",
            })
        return results

    async def generic_data_catalogue(self, catalogue_type: str) -> list[dict]:
        """Retrieve generic catalogue (CURRENCY, COUNTRIES, LANGUAGES)."""
        logger.info("GenericDataCatalogue: %s", catalogue_type)
        response = await self._call_with_retry(
            "GenericDataCatalogue",
            GenericDataCatalogueRequest={"Type": catalogue_type},
        )
        items = []
        catalogue = getattr(response, "GenericDataCatalogue", response)
        for item in getattr(catalogue, "CatalogueItem", []):
            name = ""
            content_list = getattr(item, "ItemContentList", None)
            if content_list:
                for ic in getattr(content_list, "ItemContent", []) or []:
                    if ic is None:
                        continue
                    # Language may be present on the node but null; getattr default only applies if missing.
                    lang = (getattr(ic, "Language", None) or "").strip().upper()
                    if lang == "EN":
                        name = str(getattr(ic, "Name", "") or "")
                        break
                if not name:
                    first = next(
                        (x for x in (getattr(content_list, "ItemContent", []) or []) if x is not None),
                        None,
                    )
                    if first:
                        name = str(getattr(first, "Name", "") or "")
            items.append({"code": str(getattr(item, "Code", "")), "name": name})
        return items

    async def hotel_catalogue_data(self) -> dict:
        """Retrieve hotel-specific catalogue data (categories, boards, etc.)."""
        logger.info("HotelCatalogueData")
        response = await self._call_with_retry("HotelCatalogueData")
        static_data = getattr(response, "HotelStaticData", response)

        def _parse_list(node_name, items_attr):
            result = []
            parent = getattr(static_data, node_name, None)
            if parent:
                for item in getattr(parent, items_attr, []):
                    result.append({
                        "code": str(getattr(item, "Type", getattr(item, "Code", ""))),
                        "name": str(getattr(item, "_value_1", "")),
                    })
            return result

        return {
            "hotel_categories": _parse_list("HotelCategoryList", "HotelCategory"),
            "board_types": _parse_list("BoardList", "Board"),
        }

    # ---- Booking flow methods ----

    @staticmethod
    def _normalize_hotel_codes(raw: list[str] | None) -> list[str]:
        """Upper-case, strip, dedupe JPCodes; preserve original order."""
        if not raw:
            return []
        seen: set[str] = set()
        out: list[str] = []
        for code in raw:
            if not code:
                continue
            cleaned = str(code).strip().upper()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            out.append(cleaned)
        return out

    async def _hotel_avail_batch(
        self,
        *,
        hotel_codes: list[str],
        start_date: date,
        end_date: date,
        paxes: list[dict],
        country_of_residence: str | None,
        batch_index: int,
        total_batches: int,
    ) -> list[dict]:
        """Call HotelAvail for a single batch of JPCodes.

        ``NoResultsError`` is swallowed at the caller level (an empty batch
        is not fatal when other batches may still have inventory).
        """
        # JP_SearchSegmentHotels inherits JP_SearchSegmentBase; zeep needs
        # both the base payload (_value_1) and duplicated attributes to
        # serialize dates reliably. HotelCodes / CountryOfResidence live on
        # the outer SearchSegmentsHotels wrapper (sibling of the per-stay
        # SearchSegmentHotels), per Juniper WSDL and doc §1.1.
        search_segment_base: dict[str, Any] = {"Start": start_date, "End": end_date}
        search_segment: dict[str, Any] = {
            "_value_1": search_segment_base,
            **search_segment_base,
        }

        search_segments_hotels: dict[str, Any] = {
            "SearchSegmentHotels": search_segment,
            "HotelCodes": {"HotelCode": list(hotel_codes)},
        }
        if country_of_residence:
            search_segments_hotels["CountryOfResidence"] = country_of_residence

        logger.info(
            "HotelAvail batch %d/%d: %d hotel_codes (first=%s)",
            batch_index, total_batches, len(hotel_codes), hotel_codes[0],
        )

        # Juniper caps TimeOut at 8000 ms on the WebService interface. Values
        # above the cap are silently clamped server-side — we still clamp
        # here so the outbound XML reflects what will actually take effect.
        timeout_ms = min(max(1, int(settings.juniper_avail_timeout_ms)), 8000)
        advanced_options: dict[str, Any] = {
            "ShowHotelInfo": bool(settings.juniper_avail_show_hotel_info),
            "ShowCancellationPolicies": bool(settings.juniper_avail_show_cancellation_policies),
            "ShowOnlyAvailable": bool(settings.juniper_avail_show_only_available),
            "TimeOut": timeout_ms,
        }

        response = await self._call_with_retry(
            "HotelAvail",
            Paxes={"Pax": paxes},
            HotelRequest={
                "SearchSegmentsHotels": search_segments_hotels,
                "RelPaxesDist": {
                    "RelPaxDist": [{
                        "RelPaxes": {"RelPax": [{"IdPax": pax["IdPax"]} for pax in paxes]},
                    }],
                },
            },
            AdvancedOptions=advanced_options,
        )
        # Opt-in deep probe: when ``JUNIPER_DEBUG_RAW_RESPONSE=1`` log the
        # zeep-level shape so we can tell whether an empty batch is the
        # server genuinely returning zero hotels or our serializer failing
        # to traverse the bound object (e.g. ``Results`` hidden behind
        # xs:any / ``_value_1``).  Gated on env var so it stays silent in
        # normal runs but is available during UAT debugging — see
        # ``doc/refactor-juniper-hotelcodes.md`` §10.
        import os as _os
        debug_env = _os.environ.get("JUNIPER_DEBUG_RAW_RESPONSE")
        if debug_env:
            self._log_response_shape(response, batch_index=batch_index)
        rows = serialize_hotel_avail(response)
        # Auto-probe on the "mystery empty": we got a response object with
        # any sign of content (Results / _value_1 non-empty) but the
        # serializer produced zero rows — log the shape so the next UAT
        # run surfaces the misparse without requiring the env var. Kept
        # at WARNING so it shows up in stdout during the sandbox script.
        if not rows and not debug_env:
            results = getattr(response, "Results", None)
            has_content = (
                results is not None
                or bool(getattr(response, "_value_1", None))
                or bool(getattr(response, "_any_1", None))
            )
            if has_content:
                logger.warning(
                    "[HotelAvail] batch=%d serialize returned 0 rows but "
                    "response looks non-empty — dumping zeep shape for "
                    "diagnosis. Set JUNIPER_DEBUG_RAW_RESPONSE=1 to see "
                    "this on every batch.",
                    batch_index,
                )
                self._log_response_shape(response, batch_index=batch_index)
        return rows

    @staticmethod
    def _log_response_shape(response: Any, *, batch_index: int) -> None:
        def _summary(node: Any) -> str:
            if node is None:
                return "None"
            cls = type(node).__name__
            attrs_of_interest = [
                "Results", "HotelResult", "HotelOptions", "HotelOption",
                "_value_1", "_value_2", "_any_1", "Errors",
            ]
            found: list[str] = []
            for name in attrs_of_interest:
                val = getattr(node, name, None)
                if val is None:
                    continue
                if isinstance(val, list):
                    found.append(f"{name}=list[{len(val)}]")
                else:
                    found.append(f"{name}={type(val).__name__}")
            raw = getattr(node, "__values__", None)
            if raw is not None:
                try:
                    found.append(f"__values__keys={sorted(raw.keys())[:12]}")
                except Exception:
                    pass
            return f"{cls}({', '.join(found)})"

        def _describe_item(item: Any) -> str:
            """One-line description of a ``_value_1`` list element so we
            can tell lxml Elements / zeep AnyObjects / zeep ComplexValues
            / plain dicts apart at a glance."""
            if item is None:
                return "None"
            cls = type(item)
            module = getattr(cls, "__module__", "") or ""
            name = f"{module}.{cls.__name__}"
            extras: list[str] = []
            tag = getattr(item, "tag", None)
            if tag is not None:
                extras.append(f"tag={tag}")
            attrib = getattr(item, "attrib", None)
            if attrib is not None:
                try:
                    keys = list(attrib.keys())[:6]
                    extras.append(f"attrib_keys={keys}")
                except Exception:
                    pass
            inner_value = getattr(item, "value", None)
            if inner_value is not None and inner_value is not item:
                extras.append(f".value={type(inner_value).__name__}")
            raw = getattr(item, "__values__", None)
            if raw is not None:
                try:
                    extras.append(f"__values__keys={sorted(raw.keys())[:8]}")
                except Exception:
                    pass
            # For plain dicts (zeep's xs:any fallback), surface the
            # top-level keys so we can map them to business markers
            # and confirm the HotelOptions/HotelInfo shape on the first
            # successful UAT batch. Also peek into nested HotelOptions
            # to see whether it's a dict or a list.
            if isinstance(item, dict):
                try:
                    keys = sorted(item.keys())[:12]
                    extras.append(f"dict_keys={keys}")
                    ho = item.get("HotelOptions")
                    if isinstance(ho, dict):
                        extras.append(
                            f"HotelOptions.dict_keys={sorted(ho.keys())[:8]}"
                        )
                        inner_ho = ho.get("HotelOption")
                        if isinstance(inner_ho, list):
                            extras.append(
                                f"HotelOption=list[{len(inner_ho)}]"
                            )
                        elif isinstance(inner_ho, dict):
                            extras.append(
                                f"HotelOption=dict(keys={sorted(inner_ho.keys())[:8]})"
                            )
                except Exception:
                    pass
            return f"{name}({', '.join(extras)})"

        logger.warning(
            "[JUNIPER_DEBUG_RAW_RESPONSE] batch=%d response=%s",
            batch_index, _summary(response),
        )
        results = getattr(response, "Results", None)
        logger.warning(
            "  .Results=%s .HotelResult(on response)=%s .Errors=%s "
            "._value_1=%s ._any_1=%s",
            _summary(results),
            _summary(getattr(response, "HotelResult", None)),
            _summary(getattr(response, "Errors", None)),
            _summary(getattr(response, "_value_1", None)),
            _summary(getattr(response, "_any_1", None)),
        )
        if results is not None:
            hr = getattr(results, "HotelResult", None)
            logger.warning(
                "  .Results.HotelResult=%s .Results._value_1=%s "
                ".Results._any_1=%s",
                _summary(hr),
                _summary(getattr(results, "_value_1", None)),
                _summary(getattr(results, "_any_1", None)),
            )
            v1 = getattr(results, "_value_1", None)
            if isinstance(v1, (list, tuple)) and v1:
                for i, item in enumerate(v1[:3]):
                    logger.warning(
                        "    .Results._value_1[%d] = %s", i, _describe_item(item),
                    )

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
        """Search for available hotels by explicit JPCode list.

        Juniper UAT (account TestXMLFlicknmix) rejects ``DestinationZone``
        with ``REQ_PRACTICE`` (ticket 1096690). Callers MUST resolve the
        destination to a JPCode list via the local ``hotel_cache`` and pass
        it via ``hotel_codes``. ``zone_code`` is preserved in the signature
        only to satisfy the abstract ``HotelSupplier`` contract and is
        ignored here — a non-None value is logged as a warning.

        Behaviour:
        - Normalizes + dedupes ``hotel_codes``.
        - Splits them into batches of ``settings.hotel_avail_batch_size``.
        - Executes batches concurrently, bounded by
          ``settings.hotel_avail_batch_concurrency``.
        - Aggregates and de-duplicates results by ``rate_plan_code``.
        - Per-batch ``NoResultsError`` is tolerated; only raises
          ``NoResultsError`` when every batch is empty.

        Raises:
            ValueError: if ``hotel_codes`` is empty or missing.
            NoResultsError: if no batch returned any rate plan.
            JuniperFaultError / SOAPTimeoutError: propagated from the first
                failing batch (other in-flight batches are cancelled).
        """
        if zone_code is not None:
            logger.warning(
                "HotelAvail called with zone_code=%r; ignored — Juniper requires HotelCodes.",
                zone_code,
            )

        codes = self._normalize_hotel_codes(hotel_codes)
        if not codes:
            raise ValueError(
                "JuniperClient.hotel_avail requires a non-empty 'hotel_codes' list. "
                "Resolve the destination to JPCodes via the local hotel_cache "
                "(see list_hotels_in_zone_jpdcodes) and pass them here. "
                "DestinationZone search is rejected by Juniper with REQ_PRACTICE."
            )

        max_candidates = settings.hotel_avail_max_candidates
        if max_candidates and len(codes) > max_candidates:
            logger.warning(
                "HotelAvail: %d candidates exceeds max_candidates=%d; truncating.",
                len(codes), max_candidates,
            )
            codes = codes[:max_candidates]

        record_hotel_avail_candidates(len(codes))

        batch_size = max(1, settings.hotel_avail_batch_size)
        concurrency = max(1, settings.hotel_avail_batch_concurrency)
        batches = [codes[i:i + batch_size] for i in range(0, len(codes), batch_size)]

        paxes: list[dict] = []
        for i in range(adults):
            paxes.append({"IdPax": i + 1, "Age": 30})
        for i in range(children):
            paxes.append({"IdPax": adults + i + 1, "Age": 8})

        start_date = self._parse_iso_date(check_in)
        end_date = self._parse_iso_date(check_out)

        logger.info(
            "HotelAvail: %d JPCodes -> %d batches (size=%d, concurrency=%d), "
            "%s to %s, adults=%d children=%d",
            len(codes), len(batches), batch_size, concurrency,
            check_in, check_out, adults, children,
        )

        semaphore = asyncio.Semaphore(concurrency)
        # ``ok_batches`` / ``empty_batches`` are counted only in the success
        # path; on early abort the first failing batch claims the
        # ``fault`` / ``timeout`` tick via ``fatal_event`` and siblings
        # short-circuit without re-reporting (§7 "上报一次" guarantee).
        ok_batches = 0
        empty_batches = 0
        fatal_event = asyncio.Event()
        t_start = time.monotonic()

        async def _run_batch(idx: int, batch: list[str]) -> list[dict]:
            nonlocal ok_batches, empty_batches
            async with semaphore:
                # Another batch already reported a fatal Juniper error —
                # don't spend a SOAP round-trip we're about to discard.
                if fatal_event.is_set():
                    return []
                try:
                    result = await self._hotel_avail_batch(
                        hotel_codes=batch,
                        start_date=start_date,
                        end_date=end_date,
                        paxes=paxes,
                        country_of_residence=country_of_residence,
                        batch_index=idx,
                        total_batches=len(batches),
                    )
                except NoResultsError:
                    logger.info(
                        "HotelAvail batch %d/%d: no results (tolerated)",
                        idx, len(batches),
                    )
                    record_hotel_avail_batch("empty")
                    empty_batches += 1
                    return []
                except JuniperFaultError as exc:
                    # Claim the single-shot fault-report token; later
                    # batches that race past ``fatal_event.is_set()`` but
                    # also fail won't double-record or double-log.
                    if not fatal_event.is_set():
                        fatal_event.set()
                        record_hotel_avail_batch("fault")
                        logger.error(
                            "HotelAvail batch %d/%d: Juniper fault [%s] — "
                            "aborting search (candidates=%d, batches=%d)",
                            idx, len(batches), exc.fault_code,
                            len(codes), len(batches),
                        )
                    raise
                except SOAPTimeoutError:
                    if not fatal_event.is_set():
                        fatal_event.set()
                        record_hotel_avail_batch("timeout")
                        logger.error(
                            "HotelAvail batch %d/%d: SOAP timeout — "
                            "aborting search (candidates=%d, batches=%d)",
                            idx, len(batches), len(codes), len(batches),
                        )
                    raise
                if result:
                    record_hotel_avail_batch("ok")
                    ok_batches += 1
                else:
                    record_hotel_avail_batch("empty")
                    empty_batches += 1
                return result

        batch_results = await asyncio.gather(
            *[_run_batch(i + 1, b) for i, b in enumerate(batches)],
        )

        merged: dict[str, dict] = {}
        for batch in batch_results:
            for hotel in batch:
                key = hotel.get("rate_plan_code") or f"{hotel.get('hotel_code','')}::{hotel.get('room_type','')}"
                if key not in merged:
                    merged[key] = hotel

        hotels = list(merged.values())
        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        logger.info(
            "HotelAvail: %d batches complete (ok=%d, empty=%d), "
            "%d unique rate plans, candidates=%d, elapsed=%dms",
            len(batches), ok_batches, empty_batches,
            len(hotels), len(codes), elapsed_ms,
        )

        if not hotels:
            raise NoResultsError(
                f"No hotels available for {len(codes)} JPCodes "
                f"between {check_in} and {check_out}"
            )
        return hotels

    async def hotel_check_avail(
        self,
        rate_plan_code: str,
        *,
        check_in: date | str | None = None,
        check_out: date | str | None = None,
        hotel_code: str | None = None,
        expected_price: str | None = None,
    ) -> dict:
        """Revalidate a previously retrieved RatePlanCode.

        Parameters
        ----------
        rate_plan_code:
            The ``RatePlanCode`` returned by ``HotelAvail`` (or a prior
            ``HotelCheckAvail``).
        check_in / check_out / hotel_code:
            Optional verification block — Juniper uses ``SearchSegmentsHotels
            /SearchSegmentHotels[@Start,@End]`` + ``HotelCodes/HotelCode`` to
            cross-check that the RatePlanCode still matches the original
            query. Recommended whenever the caller has the info handy; omit
            only when working from a bare code (legacy paths).
        expected_price:
            Original ``HotelAvail`` total used to populate
            ``PriceChangedError.old_price`` when a change is detected. When
            ``None`` the error will carry ``"unknown"``.

        Raises
        ------
        RoomUnavailableError:
            - No ``HotelOption`` returned, or
            - picked option has ``@Status=RQ`` / ``warnStatusChanged``, or
            - supplier reported ``warnCheckNotPossible``.
        PriceChangedError:
            Response included ``warnPriceChanged``. The error carries the
            new ``RatePlanCode`` so the caller can continue the booking flow
            with the updated code (per docs §HotelCheckAvail Response).
        """
        logger.info(
            "HotelCheckAvail: rate_plan_code=%s, hotel_code=%s, %s→%s",
            rate_plan_code, hotel_code, check_in, check_out,
        )
        # Build SearchSegmentsHotels verification block when the caller
        # supplied dates — Juniper cross-checks the RatePlanCode matches the
        # original search params. If the dates/hotel don't match the
        # supplier returns ``warnCheckNotPossible``.
        search_segments = self._build_search_segments_hotels(check_in, check_out, hotel_code)

        response = await self._call_with_retry(
            "HotelCheckAvail",
            RatePlanCode=rate_plan_code,
            SearchSegmentsHotels=search_segments,
        )
        result = serialize_check_avail(response)

        # Order matters: warnCheckNotPossible means the supplier couldn't
        # verify at all, so "available" is meaningless — surface it first.
        if result.get("check_not_possible"):
            raise RoomUnavailableError(
                f"Supplier could not verify rate plan {rate_plan_code} (warnCheckNotPossible)"
            )

        # Price change is a recoverable error: the caller gets the *new*
        # RatePlanCode via PriceChangedError.new_rate_plan_code and can
        # re-enter the booking flow with the updated code.
        if result.get("price_changed"):
            raise PriceChangedError(
                expected_price or "unknown",
                result["total_price"],
                result["currency"],
                new_rate_plan_code=result.get("rate_plan_code") or "",
            )

        if result.get("status_changed") or not result.get("available"):
            raise RoomUnavailableError(
                f"Rate plan {rate_plan_code} is no longer available "
                f"(status={result.get('status') or 'missing'})"
            )

        return result

    async def hotel_booking_rules(
        self,
        rate_plan_code: str,
        *,
        check_in: date | str | None = None,
        check_out: date | str | None = None,
        hotel_code: str | None = None,
        expected_price: str | None = None,
    ) -> dict:
        """Pre-booking valuation: validate the RatePlanCode and retrieve the
        ``BookingCode`` that ``HotelBooking`` consumes.

        Per docs (``uploads/hotel-api-0.md`` §HotelBookingRules), this step
        also:

        * Returns the **final cancellation policy** (critical for the
          caller to display to the guest);
        * Returns detailed **RequiredFields** (which pax fields are
          mandatory) and **Comments** from the hotel;
        * Re-validates allotment and price — if either drifted, the response
          carries ``warnPriceChanged`` / ``warnStatusChanged`` and the
          ``RatePlanCode`` may be regenerated. The **new code** comes back
          on ``HotelOption/@RatePlanCode`` and MUST replace the old one
          for any subsequent HotelBooking call.

        Parameters
        ----------
        rate_plan_code:
            The ``RatePlanCode`` returned by ``HotelAvail`` or a prior
            ``HotelCheckAvail`` / ``HotelBookingRules``.
        check_in / check_out / hotel_code:
            Optional ``SearchSegmentsHotels`` verification block. Juniper
            uses these to confirm the RatePlanCode still matches the
            original search window — mismatch ⇒ ``warnCheckNotPossible``.
            Recommended whenever the caller has the info handy.
        expected_price:
            The total from the previous step; used to populate
            ``PriceChangedError.old_price`` when a drift is detected.

        Returns
        -------
        dict
            The serialized booking rules (see ``serialize_booking_rules``),
            including ``booking_code`` / ``booking_code_expires_at`` / the
            (possibly refreshed) ``rate_plan_code`` / structured
            ``cancellation`` / ``required_fields`` / ``hotel_content``.

        Raises
        ------
        RoomUnavailableError:
            - Supplier returned no ``HotelOption``, or
            - Picked option has ``@Status=RQ`` / ``warnStatusChanged``, or
            - Supplier reported ``warnCheckNotPossible``, or
            - Response lacks a ``BookingCode`` (the whole point of the call).
        PriceChangedError:
            Response included ``warnPriceChanged``. The error carries the
            new ``RatePlanCode`` (``new_rate_plan_code``) so the caller can
            re-enter the booking flow with the updated code.
        """
        logger.info(
            "HotelBookingRules: rate_plan_code=%s, hotel_code=%s, %s→%s",
            rate_plan_code, hotel_code, check_in, check_out,
        )

        search_segments = self._build_search_segments_hotels(check_in, check_out, hotel_code)

        response = await self._call_with_retry(
            "HotelBookingRules",
            RatePlanCode=rate_plan_code,
            SearchSegmentsHotels=search_segments,
        )
        result = serialize_booking_rules(response)

        # Order matters — same as HotelCheckAvail:
        # 1. ``warnCheckNotPossible`` ⇒ verification failed, "valid" is
        #    meaningless. Surface as unavailable.
        if "warnCheckNotPossible" in result.get("warning_codes", []):
            raise RoomUnavailableError(
                f"Supplier could not verify rate plan {rate_plan_code} "
                f"(warnCheckNotPossible)"
            )

        # 2. ``warnPriceChanged`` ⇒ recoverable. The serializer already
        #    extracted the refreshed RatePlanCode (from HotelOption/@RatePlanCode)
        #    so the caller can retry with the new code.
        if result.get("price_changed"):
            raise PriceChangedError(
                expected_price or "unknown",
                result.get("total_price") or "0",
                result.get("currency") or "EUR",
                new_rate_plan_code=result.get("rate_plan_code") or "",
            )

        # 3. ``warnStatusChanged`` or @Status != OK ⇒ allotment dropped.
        if result.get("status_changed") or not result.get("valid"):
            raise RoomUnavailableError(
                f"Rate plan {rate_plan_code} is no longer available "
                f"(status={result.get('status') or 'missing'})"
            )

        # 4. No BookingCode ⇒ the response is technically "valid" but
        #    useless for HotelBooking. Docs are explicit: "BookingCode …
        #    will be required in order to later confirm the booking on the
        #    HotelBooking request" (line 2556). Fail loudly.
        if not result.get("booking_code"):
            raise RoomUnavailableError(
                f"HotelBookingRules returned no BookingCode for rate plan {rate_plan_code}"
            )

        return result

    async def hotel_booking(
        self,
        rate_plan_code: str,
        guest_name: str,
        guest_email: str,
        *,
        booking_code: str = "",
        hotel_code: str = "",
        check_in: date | str | None = None,
        check_out: date | str | None = None,
        total_price: str | float | None = None,
        currency: str = "EUR",
        first_name: str | None = None,
        surname: str = "",
        country_of_residence: str = "",
        adults: int = 1,
        children: int = 0,
        paxes: list[dict] | None = None,
        rel_paxes_dist: list[list[int]] | None = None,
        external_booking_reference: str = "",
        **_unused,
    ) -> dict:
        """Confirm a hotel booking on Juniper.

        Juniper's ``HotelBooking`` payload is far more than just
        "BookingCode + guest info": the supplier cross-validates the stay
        window, hotel code, price range, and room-to-pax mapping against
        the reservation that was valuated by ``HotelBookingRules``. Any
        missing element triggers a ``REQ_PRACTICE`` fault the same way
        ``DestinationZone`` did on HotelAvail. See
        ``doc/juniper-hotel-api.md`` §2.

        Parameters
        ----------
        rate_plan_code:
            Only used as a BookingCode fallback when ``booking_code`` is
            blank. Real UAT flows should always pass the fresh code from
            ``HotelBookingRules`` (BookingCode expires after 10 minutes).
        booking_code:
            The ``BookingCode`` returned by ``HotelBookingRules``. Required
            for production Juniper flows.
        hotel_code / check_in / check_out:
            Must match what was sent to ``HotelBookingRules``. These go
            into ``HotelBookingInfo`` where Juniper re-validates the window
            before committing the reservation.
        total_price / currency:
            The quoted total from ``HotelBookingRules``. Fed into
            ``HotelBookingInfo/Price/PriceRange`` as a tolerance band using
            ``settings.juniper_booking_price_tolerance_pct`` — Juniper
            rejects the booking server-side if the real price falls outside
            this window, so this is how we guard against silent price drift.
        guest_name / guest_email / first_name / surname:
            Holder (primary guest) info. ``first_name`` + ``surname`` take
            precedence when provided; otherwise we split ``guest_name``.
        country_of_residence:
            Populates ``Pax/Nationality`` on the primary pax.
        adults / children:
            When ``paxes`` is ``None``, build a roster that matches
            ``hotel_avail`` (``IdPax`` 1..adults at age 30, then children at
            age 8). **Must match** the occupancy used in HotelAvail /
            HotelBookingRules or Juniper returns ``JP_BOOK_OCCUPANCY_ERROR``.
        paxes:
            Optional explicit list of pre-built Pax dicts (already
            containing ``IdPax``, ``Name``, ``Surname``, ``Age``, etc.).
            When ``None`` we build from ``adults``/``children`` and
            ``guest_name``. Ignores ``adults``/``children`` when ``paxes`` is
            set.
        rel_paxes_dist:
            Optional explicit room→pax split (list of lists of IdPax).
            Default: single room containing every pax.
        external_booking_reference:
            Idempotency key propagated to ``ExternalBookingReference`` so
            the retry layer can reconcile duplicates.
        """
        first_name = first_name or guest_name.split(maxsplit=1)[0] if guest_name else ""
        if not surname and guest_name and " " in guest_name:
            surname = guest_name.split(maxsplit=1)[1]

        logger.info(
            "HotelBooking: rate_plan=%s hotel=%s %s→%s total=%s %s holder=%s %s",
            rate_plan_code, hotel_code, check_in, check_out,
            total_price, currency, first_name, surname,
        )

        if paxes is None:
            if adults < 1:
                raise ValueError("hotel_booking requires adults >= 1 when paxes is omitted")
            if children < 0:
                raise ValueError("hotel_booking children cannot be negative")
            built: list[dict[str, Any]] = []
            for i in range(adults):
                pid = i + 1
                pax_row: dict[str, Any] = {
                    "IdPax": pid,
                    "Age": 30,
                    "Name": first_name if i == 0 else "Guest",
                    "Surname": surname if i == 0 else str(pid),
                }
                if i == 0:
                    pax_row["Email"] = guest_email
                    if country_of_residence:
                        pax_row["Nationality"] = country_of_residence
                built.append(pax_row)
            for i in range(children):
                pid = adults + i + 1
                built.append(
                    {
                        "IdPax": pid,
                        "Name": "Child",
                        "Surname": str(pid),
                        "Age": 8,
                    },
                )
            paxes = built

        pax_ids: list[int] = []
        for pax in paxes:
            try:
                pax_ids.append(int(pax["IdPax"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"HotelBooking pax missing integer IdPax: {pax!r}") from exc

        hotel_booking_info: dict[str, Any] = {}
        if check_in:
            hotel_booking_info["Start"] = (
                check_in if isinstance(check_in, str) else check_in.strftime("%Y-%m-%d")
            )
        if check_out:
            hotel_booking_info["End"] = (
                check_out if isinstance(check_out, str) else check_out.strftime("%Y-%m-%d")
            )
        price_range = self._build_price_range(
            total_price, currency, settings.juniper_booking_price_tolerance_pct,
        )
        if price_range:
            hotel_booking_info["Price"] = price_range
        if hotel_code:
            hotel_booking_info["HotelCode"] = hotel_code

        booking_kwargs: dict[str, Any] = {
            "Holder": {"RelPax": {"IdPax": pax_ids[0]}},
            "Paxes": {"Pax": paxes},
            "RelPaxesDist": self._build_rel_paxes_dist(pax_ids, rel_paxes_dist=rel_paxes_dist),
        }
        if hotel_booking_info:
            booking_kwargs["HotelBookingInfo"] = hotel_booking_info

        if booking_code:
            booking_kwargs["BookingCode"] = booking_code
        else:
            logger.warning(
                "HotelBooking called without BookingCode — falling back to "
                "RatePlanCode %s. Juniper docs (line 2556) require BookingCode "
                "from HotelBookingRules; this path only exists for mock/test.",
                rate_plan_code,
            )
            booking_kwargs["RatePlanCode"] = rate_plan_code

        if external_booking_reference:
            booking_kwargs["ExternalBookingReference"] = external_booking_reference

        response = await self._call_with_retry("HotelBooking", **booking_kwargs)
        return serialize_booking(response)

    async def read_booking(self, booking_id: str, user_id: str | None = None) -> dict:
        """Read an existing booking. Ownership is enforced at the database layer."""
        logger.info("ReadBooking: %s, user_id=%s", booking_id, user_id)
        response = await self._call_with_retry("ReadBooking", Locator=booking_id)
        return serialize_read_booking(response)

    async def list_bookings(self, user_id: str | None = None) -> list[dict]:
        """List bookings — not supported by Juniper SOAP API.

        In production, booking history should be queried from the local database.
        """
        raise NotImplementedError(
            "Juniper SOAP API does not support listing bookings. "
            "Use the database query via GET /api/v1/bookings instead."
        )

    async def cancel_booking(
        self, booking_id: str, user_id: str | None = None, only_fees: bool = False,
    ) -> dict:
        """Cancel a booking or query cancellation fees only."""
        logger.info("CancelBooking: %s, user_id=%s, only_fees=%s", booking_id, user_id, only_fees)
        cancel_kwargs = {"Locator": booking_id}
        if only_fees:
            cancel_kwargs["OnlyCancellationFees"] = "true"

        response = await self._call_with_retry("CancelBooking", **cancel_kwargs)

        # Parse CancelInfo from response if available
        cancel_info = getattr(response, "CancelInfo", None)
        warnings = getattr(response, "Warnings", None)
        warning_codes = []
        if warnings:
            for w in getattr(warnings, "Warning", []):
                warning_codes.append(str(getattr(w, "Code", "")))

        result = {"booking_id": booking_id}
        if only_fees:
            result["status"] = "fee_query"
            result["cancel_cost"] = str(getattr(cancel_info, "BookingCancelCost", "0")) if cancel_info else "0"
            result["cancel_cost_currency"] = str(getattr(cancel_info, "BookingCancelCostCurrency", "EUR")) if cancel_info else "EUR"
        else:
            result["status"] = "cancelled"
        result["warnings"] = warning_codes
        return result

    async def hotel_modify(self, booking_id: str, user_id: str | None = None, **modifications) -> dict:
        """Step 1: Request modification options via HotelModify."""
        logger.info("HotelModify: %s, user_id=%s, changes=%s", booking_id, user_id, modifications)
        modify_kwargs = {"Locator": booking_id}
        if modifications.get("check_in"):
            modify_kwargs["Start"] = modifications["check_in"]
        if modifications.get("check_out"):
            modify_kwargs["End"] = modifications["check_out"]

        response = await self._call_with_retry("HotelModify", **modify_kwargs)

        modify_code = str(getattr(response, "ModifyCode", ""))
        result = serialize_read_booking(response)
        result["modify_code"] = modify_code
        return result

    async def hotel_confirm_modify(self, modify_code: str) -> dict:
        """Step 2: Confirm modification via HotelConfirmModify."""
        logger.info("HotelConfirmModify: %s", modify_code)
        response = await self._call_with_retry("HotelConfirmModify", ModifyCode=modify_code)
        return serialize_read_booking(response)
