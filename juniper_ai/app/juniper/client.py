"""Juniper SOAP client wrapper with async-safe execution via asyncio.to_thread()."""

import asyncio
import logging
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
        if operation_name in with_timestamp:
            return {"TimeStamp": datetime.now(timezone.utc)}
        return {}

    @staticmethod
    def _raise_if_response_errors(operation_name: str, response: Any) -> None:
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
            return {"HotelCheckAvailRequest": {"HotelOption": {"RatePlanCode": rate_plan_code}}}

        if operation_name == "HotelBookingRules":
            rate_plan_code = kwargs.get("RatePlanCode", "")
            return {"HotelBookingRulesRequest": {"HotelOption": {"RatePlanCode": rate_plan_code}}}

        if operation_name == "HotelBooking":
            booking_code = kwargs.get("BookingCode", "")
            rate_plan_code = kwargs.get("RatePlanCode", "")
            payload: dict[str, Any] = {
                "Holder": kwargs.get("Holder", {}),
                "Paxes": kwargs.get("Paxes", {}),
                "Elements": {"HotelElement": {"BookingCode": booking_code or rate_plan_code}},
            }
            external_ref = kwargs.get("ExternalBookingReference")
            if external_ref:
                payload["ExternalBookingReference"] = external_ref
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
        return {
            "hotels": hotels,
            "next_token": str(getattr(portfolio, "NextToken", "") or ""),
            "total_records": int(getattr(portfolio, "TotalRecords", 0)),
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
                for ic in getattr(content_list, "ItemContent", []):
                    if getattr(ic, "Language", "").upper() == "EN":
                        name = str(getattr(ic, "Name", ""))
                        break
                if not name:
                    first = next(iter(getattr(content_list, "ItemContent", [])), None)
                    if first:
                        name = str(getattr(first, "Name", ""))
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

    async def hotel_avail(
        self, zone_code: str, check_in: str, check_out: str,
        adults: int = 2, children: int = 0,
        star_rating: int | None = None,
        max_price: float | None = None,
        board_type: str | None = None,
        country_of_residence: str | None = None,
        **kwargs,
    ) -> list[dict]:
        """Search for available hotels by zone code."""
        logger.info("HotelAvail: zone=%s, %s to %s, %d adults", zone_code, check_in, check_out, adults)

        paxes = []
        for i in range(adults):
            paxes.append({"IdPax": i + 1, "Age": 30})
        for i in range(children):
            paxes.append({"IdPax": adults + i + 1, "Age": 8})

        search_segment_base: dict[str, Any] = {
            "Start": self._parse_iso_date(check_in),
            "End": self._parse_iso_date(check_out),
        }
        if str(zone_code).upper().startswith("JPD"):
            search_segment_base["JPDCode"] = str(zone_code).upper()
        else:
            search_segment_base["DestinationZone"] = int(zone_code)
        # JP_SearchSegmentHotels inherits JP_SearchSegmentBase; zeep needs both
        # explicit attrs and the base payload to serialize reliably.
        search_segment = {
            "_value_1": search_segment_base,
            **search_segment_base,
        }

        search_segments_hotels: dict[str, Any] = {"SearchSegmentHotels": search_segment}
        if country_of_residence:
            search_segments_hotels["CountryOfResidence"] = country_of_residence

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
            AdvancedOptions={"TimeOut": 15000},
        )
        hotels = serialize_hotel_avail(response)
        if not hotels:
            raise NoResultsError(f"No hotels found in zone {zone_code} for {check_in} to {check_out}")
        return hotels

    async def hotel_check_avail(self, rate_plan_code: str) -> dict:
        """Check if a specific rate plan is still available."""
        logger.info("HotelCheckAvail: %s", rate_plan_code)
        response = await self._call_with_retry(
            "HotelCheckAvail",
            RatePlanCode=rate_plan_code,
        )
        result = serialize_check_avail(response)
        if not result.get("available"):
            raise RoomUnavailableError(f"Rate plan {rate_plan_code} is no longer available")
        if result.get("price_changed"):
            raise PriceChangedError("unknown", result["total_price"], result["currency"])
        return result

    async def hotel_booking_rules(self, rate_plan_code: str) -> dict:
        """Validate booking rules and get final price."""
        logger.info("HotelBookingRules: %s", rate_plan_code)
        response = await self._call_with_retry("HotelBookingRules", RatePlanCode=rate_plan_code)
        return serialize_booking_rules(response)

    async def hotel_booking(
        self, rate_plan_code: str, guest_name: str, guest_email: str, **kwargs,
    ) -> dict:
        """Create a hotel booking with proper Pax, BookingCode, and ExternalBookingReference."""
        logger.info("HotelBooking: %s for %s", rate_plan_code, guest_name)

        first_name = kwargs.get("first_name", guest_name)
        surname = kwargs.get("surname", "")
        country = kwargs.get("country_of_residence", "")
        booking_code = kwargs.get("booking_code", "")
        external_ref = kwargs.get("external_booking_reference", "")

        # Build proper Pax object
        pax = {"IdPax": 1, "Name": first_name, "Surname": surname, "Age": 30, "Email": guest_email}
        if country:
            pax["Nationality"] = country

        booking_kwargs = {
            "Holder": {"Name": first_name, "Surname": surname, "Email": guest_email},
            "Paxes": {"Pax": [pax]},
        }

        # Use BookingCode if available (from BookingRules), otherwise fall back to RatePlanCode
        if booking_code:
            booking_kwargs["BookingCode"] = booking_code
        else:
            booking_kwargs["RatePlanCode"] = rate_plan_code

        if external_ref:
            booking_kwargs["ExternalBookingReference"] = external_ref

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
