from __future__ import annotations

"""ArcGIS REST base adapter — shared machinery for ArcGIS Hub / FeatureServer cities.

ArcGIS REST (Esri) is the *other* major open-data dialect besides Socrata. LA
(LADBS) and Miami-Dade publish through it. The query model is quite different
from Socrata SoQL, so this module centralises the ArcGIS-specific concerns:

  * Endpoint shape:  {feature_server}/{layer}/query?where=...&outFields=*&f=json
  * Response shape:  {"features":[{"attributes":{...},"geometry":{...}}],
                      "spatialReference":{"wkid":...}}
  * Dates are epoch-milliseconds (ints), NOT ISO strings — see ``epoch_ms_to_date``.
  * Geometry is often in a *projected* CRS (StatePlane, WKID 2229 / 2236 / ...)
    not WGS84 lat/lng. Some layers ALSO publish explicit ``LAT``/``LON``
    attribute fields in decimal degrees — prefer those when present (LA does).
    When only projected geometry is available (Miami), we keep the raw x/y and
    flag geocode confidence low; a downstream reprojector can upgrade later.

City adapters subclass ``ArcGISAdapter`` and implement ``normalize()`` exactly
like the Socrata adapters — the only ArcGIS-isms they need are the helpers below
(``epoch_ms_to_date`` for dates, ``_feature_attributes`` / ``_feature_geometry``
to unwrap a feature). fetch() is provided here once for every ArcGIS city.
"""
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx

from permy.adapters.base import _str, now_utc


# ---------------------------------------------------------------------------
# ArcGIS value helpers
# ---------------------------------------------------------------------------
def epoch_ms_to_date(v: Any) -> Optional[date]:
    """ArcGIS stores dates as epoch-milliseconds (e.g. 1782950400000 = 2026-07-02).

    Some fields come back as None or as an already-parsed ISO string (rare);
    handle both gracefully so a city adapter can pass any 'date-ish' value through.

    Sentinel handling: several ArcGIS layers use ``00000000`` or epoch ``0`` as
    "no date" (Miami-Dade does this for unset LSTAPPRDT / BLDCMPDT). We treat any
    value that parses to on-or-before 1970-01-02 as None so the permit doesn't
    show a fabricated 1970 date.
    """
    if v is None or v == "":
        return None
    # already a string? (some ArcGIS configs return ISO)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        # all-zeros sentinel ("00000000") → no date
        if s.replace("0", "") == "":
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(s[:10])
            except ValueError:
                # numeric string? treat as epoch-ms
                try:
                    d = datetime.fromtimestamp(int(float(s)) / 1000.0, tz=timezone.utc).date()
                except (TypeError, ValueError, OSError, OverflowError):
                    return None
                return None if d <= date(1970, 1, 2) else d
    if isinstance(v, (int, float)):
        try:
            d = datetime.fromtimestamp(int(v) / 1000.0, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
        return None if d <= date(1970, 1, 2) else d
    return None


def _feature_attributes(feature: Dict[str, Any]) -> Dict[str, Any]:
    """Pull the attribute dict out of an ArcGIS feature (fall back to the feature itself)."""
    if isinstance(feature, dict):
        attrs = feature.get("attributes")
        if isinstance(attrs, dict):
            return attrs
        return feature
    return {}


def _feature_geometry(feature: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(feature, dict):
        g = feature.get("geometry")
        if isinstance(g, dict):
            return g
    return {}


def _is_projected_crs(spatial_reference: Dict[str, Any]) -> bool:
    """True when the geometry is NOT in WGS84 (4326). Projected CRS have wkid != 4326."""
    if not isinstance(spatial_reference, dict):
        return False
    wkid = spatial_reference.get("wkid") or spatial_reference.get("latestWkid")
    return wkid not in (None, 4326, 4269)  # 4326=WGS84, 4269=NAD83 (geographic)


# ---------------------------------------------------------------------------
# Reprojection (projected StatePlane → WGS84 lat/lng)
# ---------------------------------------------------------------------------
_pyproj_cache: Dict[Any, Any] = {}


def reproject_xy(x: Any, y: Any, from_wkid: Any) -> "tuple[Optional[float], Optional[float]]":
    """Reproject a projected (x, y) point to WGS84 (lng, lat).

    Uses pyproj when available; returns (None, None) when pyproj isn't installed
    or the transform fails, so the caller can fall back to an honest null geocode.
    Transformers are cached per-WKID for speed.
    """
    if x is None or y is None or from_wkid is None:
        return None, None
    try:
        import pyproj  # type: ignore
    except ImportError:
        return None, None
    try:
        xf = _float_xy(x)
        yf = _float_xy(y)
        if xf is None or yf is None:
            return None, None
        tr = _pyproj_cache.get(from_wkid)
        if tr is None:
            tr = pyproj.Transformer.from_crs(f"EPSG:{from_wkid}", "EPSG:4326", always_xy=True)
            _pyproj_cache[from_wkid] = tr
        lng, lat = tr.transform(xf, yf)
        if lat is None or lng is None:
            return None, None
        return float(lat), float(lng)
    except Exception:  # noqa: BLE001 — geocode is best-effort, never fatal
        return None, None


def _float_xy(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Base adapter
# ---------------------------------------------------------------------------
class ArcGISAdapter:
    """Subclass and set the class attrs; ``fetch`` + ``source_meta`` come from here.

    Subclass contract:
        feature_server : str   e.g. "https://lacitydbs.org/arcgiswebad/rest/services/PERMIT_FC_PRO/FeatureServer"
        layer_id       : int   the layer to query
        order_field    : str   field used for $orderByFields (usually ISSUE_DATE / ISSUDATE)
        jurisdiction_slug / city / state / source_portal / source_name  (same as Socrata adapters)
    """

    feature_server: str = ""
    layer_id: int = 0
    order_field: str = ""
    jurisdiction_slug: str = ""
    city: str = ""
    state: str = ""
    source_portal: str = "arcgis"
    source_name: str = ""

    def __init__(self, client: Optional[httpx.Client] = None, timeout: float = 30.0):
        self._client = client or httpx.Client(timeout=timeout, headers={"Accept": "application/json"})
        # spatial reference of the geometry returned by the last fetch() — set so
        # normalize() can reproject projected CRSes (StatePlane → WGS84) when the
        # layer has no explicit lat/lng attribute fields. When loading from a
        # recorded fixture, a city adapter may set this directly.
        self._geometry_wkid: Optional[int] = None

    # ---- fetch (ArcGIS REST query) ----
    def fetch(self, since: Optional[date] = None, limit: int = 1000) -> List[Dict[str, Any]]:
        """Query the ArcGIS FeatureServer layer. Returns the raw ``features`` list.

        Each element is ``{"attributes":{...}, "geometry":{...}}`` — city
        adapters unwrap with ``_feature_attributes`` / ``_feature_geometry``.
        """
        where = "1=1"
        if since is not None:
            # ArcGIS date filters are epoch-ms against the field
            ms = int(since.strftime("%s")) * 1000
            where = f"{self.order_field} >= {ms}"
        params: Dict[str, Any] = {
            "where": where,
            "outFields": "*",
            "resultRecordCount": limit,
            "f": "json",
            "returnGeometry": "true",
        }
        if self.order_field:
            params["orderByFields"] = f"{self.order_field} DESC"
        url = f"{self.feature_server}/{self.layer_id}/query?{urlencode(params)}"
        r = self._client.get(url)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and "error" in data:
            raise RuntimeError(f"ArcGIS query error: {data['error']}")
        # remember the geometry CRS so normalize() can reproject if needed
        sr = data.get("spatialReference") if isinstance(data, dict) else None
        if isinstance(sr, dict):
            self._geometry_wkid = sr.get("wkid") or sr.get("latestWkid")
        return data.get("features", []) if isinstance(data, dict) else []

    # ---- normalise is city-specific; subclasses implement it ----
    def normalize(self, raw: Dict[str, Any]) -> Any:  # pragma: no cover - abstract
        raise NotImplementedError

    # ---- source_meta default; subclasses may override ----
    def source_meta(self) -> Dict[str, Any]:
        return {
            "jurisdiction_slug": self.jurisdiction_slug,
            "city": self.city,
            "state": self.state,
            "source_portal": self.source_portal,
            "source_name": self.source_name,
            "is_live": True,
            "ingest_cadence": "daily",
        }


__all__ = [
    "ArcGISAdapter", "epoch_ms_to_date",
    "_feature_attributes", "_feature_geometry", "_is_projected_crs",
    "_str", "now_utc",
]
