from __future__ import annotations

"""License-board join — enrich contractors with license status + trade qualifications.

Sources (per state):
  CA CSLB, FL DBPR, NY DOL, WA L&I, MN DLI, TX TRCC, etc.

MVP: thin lookup interface + a TX TRCC stub. Real boards have heterogeneous
APIs (some are CSV downloads, some web scraping, some no public API at all),
so each board is its own small adapter behind LicenseBoard protocol.
"""
from typing import Dict, Optional, Protocol, runtime_checkable


@runtime_checkable
class LicenseBoard(Protocol):
    state: str

    def lookup(self, license_number: str) -> Dict[str, Optional[str]]:
        """Returns {status, trade, expires, url} or empty dict if not found."""
        ...


class TXTrierOfLicense:
    """TX TRCC (Texas Dept of Licensing & Regulation) — stub.

    The real board exposes a search at tdlr.texas.gov; many licenses are also
    surfaced via Socrata. This stub returns 'unknown' status so the pipeline
    never blocks on a missing license lookup. Swap for the real join in Phase 2.
    """
    state = "TX"

    def lookup(self, license_number: str) -> Dict[str, Optional[str]]:
        if not license_number:
            return {}
        return {"status": "unknown", "trade": None, "expires": None,
                "url": f"https://www.tdlr.texas.gov/tools_search/remote.asp?lic={license_number}"}


_BOARDS: Dict[str, LicenseBoard] = {"TX": TXTrierOfLicense()}


def get_board(state: str) -> Optional[LicenseBoard]:
    return _BOARDS.get(state.upper())
