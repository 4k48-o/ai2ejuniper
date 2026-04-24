#!/usr/bin/env python3
"""Offline diagnostic: feed a captured Juniper HotelAvail response XML to
``serialize_hotel_avail`` and dump what happens at every decision point.

Usage:
    python scripts/diagnose_serializer.py logs/soap_dumps/<file>.xml

The sandbox dumps the full SOAP envelope (request + response) by
``--debug-soap``. This script extracts the response envelope, parses it
into a tiny attribute-proxy tree whose shape matches what the zeep
client returns, then:

  * prints the shape at every nesting level we expect
  * runs ``serialize_hotel_avail`` on it
  * prints the serialized output

Goal: prove whether a bug lives in our serializer / parsers vs. in how
we traverse the zeep object (e.g. ``Results`` / ``HotelResult`` /
``HotelOption`` nesting mismatches).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lxml import etree

from juniper_ai.app.juniper.serializers import serialize_hotel_avail


NS = {"jp": "http://www.juniper.es/webservice/2007/"}


class _ElemProxy:
    """Minimal duck-type of a zeep object: ``getattr`` returns children,
    attributes, or text.

    Juniper responses arrive namespaced. ``getattr(node, "HotelResult")``
    returns a ``list`` if more than one match, a single proxy if exactly
    one, and ``None`` when absent — mirroring zeep's behaviour that our
    serializer was written against.
    """

    __slots__ = ("_el",)

    def __init__(self, el: etree._Element) -> None:
        self._el = el

    def __repr__(self) -> str:
        tag = etree.QName(self._el.tag).localname
        attrs = " ".join(f"{k}={v!r}" for k, v in self._el.attrib.items())
        return f"<{tag} {attrs}>" if attrs else f"<{tag}>"

    def __getattr__(self, name: str) -> Any:
        # 1) XML attribute?
        if name in self._el.attrib:
            return self._el.attrib[name]
        # 2) Child element(s)?
        children = [c for c in self._el if etree.QName(c.tag).localname == name]
        if not children:
            return None
        if len(children) == 1:
            child = children[0]
            # Leaf text → return the text directly so ``text()`` helper
            # can read it.  But keep attributes accessible too — zeep's
            # approach is ``_value_1`` for text, so emulate that.
            if len(child) == 0 and child.attrib:
                return _ElemProxy(child)
            if len(child) == 0:
                # pure text leaf
                return child.text or ""
            return _ElemProxy(child)
        return [_ElemProxy(c) for c in children]

    @property
    def _value_1(self) -> str:
        return self._el.text or ""


def _extract_response_body(path: Path) -> etree._Element:
    raw = path.read_text(encoding="utf-8")
    marker = "<!-- ===== RESPONSE ===== -->"
    if marker not in raw:
        raise ValueError(f"{path}: missing RESPONSE marker")
    resp_section = raw.split(marker, 1)[1].strip()
    # Strip a potential trailing FOOTER marker (none today, future-proofing).
    resp_section = re.split(r"<!--\s*=====", resp_section, maxsplit=1)[0]
    root = etree.fromstring(resp_section.encode("utf-8"))
    # SOAP envelope → Body → HotelAvailResponse → AvailabilityRS
    body = root.find(".//{http://schemas.xmlsoap.org/soap/envelope/}Body")
    if body is None:
        raise ValueError("SOAP Body not found")
    op_response = next(iter(body), None)  # e.g. HotelAvailResponse
    if op_response is None:
        raise ValueError("SOAP Body is empty")
    availability_rs = next(iter(op_response), None)  # AvailabilityRS
    if availability_rs is None:
        raise ValueError(f"{op_response.tag}: no inner RS element")
    return availability_rs


def _print_shape(response: _ElemProxy) -> None:
    print("\n=== RESPONSE SHAPE PROBE ===")
    print("response =", response)
    results = getattr(response, "Results", None)
    print("response.Results =", results)
    if results is None:
        print("  -> no Results element")
        return
    hr = getattr(results, "HotelResult", None)
    print("response.Results.HotelResult =", type(hr).__name__, "-", hr)
    hr_list = hr if isinstance(hr, list) else ([hr] if hr is not None else [])
    print(f"  -> {len(hr_list)} HotelResult(s)")
    for i, h in enumerate(hr_list):
        print(f"  [{i}] {h!r}")
        info = getattr(h, "HotelInfo", None)
        print(f"      HotelInfo = {info!r}")
        if info is not None:
            print(f"        Name child = {getattr(info, 'Name', None)!r}")
        opts_wrapper = getattr(h, "HotelOptions", None)
        print(f"      HotelOptions wrapper = {opts_wrapper!r}")
        if opts_wrapper is not None:
            opts = getattr(opts_wrapper, "HotelOption", None)
            opts_list = opts if isinstance(opts, list) else ([opts] if opts is not None else [])
            print(f"        -> {len(opts_list)} HotelOption(s)")
            for j, opt in enumerate(opts_list[:3]):
                print(f"        [{j}] {opt!r}")
                print(f"            RatePlanCode = {getattr(opt, 'RatePlanCode', '')[:40]}...")
                print(f"            Status       = {getattr(opt, 'Status', '')!r}")
                board = getattr(opt, "Board", None)
                print(f"            Board        = {board!r}")
                prices = getattr(opt, "Prices", None)
                print(f"            Prices       = {prices!r}")


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <dump.xml>", file=sys.stderr)
        sys.exit(2)
    path = Path(sys.argv[1])
    availability_rs = _extract_response_body(path)
    response = _ElemProxy(availability_rs)

    _print_shape(response)

    print("\n=== serialize_hotel_avail(response) ===")
    out = serialize_hotel_avail(response)
    print(f"returned {len(out)} row(s)")
    for i, row in enumerate(out[:5]):
        print(f"  [{i}] name={row.get('name')!r}"
              f" status={row.get('status')!r}"
              f" board_type={row.get('board_type')!r}"
              f" total_price={row.get('total_price')!r}"
              f" currency={row.get('currency')!r}"
              f" rate_plan_code={(row.get('rate_plan_code') or '')[:30]!r}")


if __name__ == "__main__":
    main()
