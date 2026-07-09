from __future__ import annotations

"""Geocoding — Census geocoder (free, no key) with Smarty/Mapbox upgrade path.

Census returns rooftop-ish points for real addresses; confidence is derived
from the matcher score. For MVP we use Census exclusively; paid tiers swap to
Smarty for true rooftop accuracy. All geocoders return (lat, lng, confidence).
"""
from typing import Optional, Tuple  # noqa: E402

import httpx  # noqa: E402

CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"


def geocode_census(address: str, client: Optional[httpx.Client] = None) -> Optional[Tuple[float, float, float]]:
    """Returns (lat, lng, confidence 0..1) or None."""
    own = client is None
    c = client or httpx.Client(timeout=10.0)
    try:
        r = c.get(CENSUS_URL, params={
            "address": address, "benchmark": "2020", "format": "json",
        })
        r.raise_for_status()
        data = r.json()
        matches = data.get("result", {}).get("addressMatches", [])
        if not matches:
            return None
        m = matches[0]
        coords = m.get("coordinates", {})
        # confidence: tie to whether the matcher returned an exact-tigerline match
        conf = 0.85 if m.get("addressComponents") else 0.6
        return (float(coords["y"]), float(coords["x"]), conf)
    except Exception:  # noqa: BLE001
        return None
    finally:
        if own:
            c.close()


def geocode(address: str, provider: str = "census") -> Optional[Tuple[float, float, float]]:
    """Dispatch to the configured provider. Stub for smarty/mapbox for now."""
    if provider == "census":
        return geocode_census(address)
    # smarty / mapbox implementations live in paid-tier modules; not in MVP scope.
    return geocode_census(address)
