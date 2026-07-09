from __future__ import annotations

"""Deduplication — stable canonical_uids prevent the same permit landing twice.

canonical_uid = hash(jurisdiction_slug + source_permit_id). This is stable
across re-ingests, so an UPDATE path beats INSERT on conflict. For address-
based dedup of property records we hash the normalized full_address.
"""
import hashlib


def canonical_permit_uid(jurisdiction_slug: str, source_permit_id: str) -> str:
    return hashlib.sha1(f"{jurisdiction_slug}:{source_permit_id}".encode()).hexdigest()[:24]


def canonical_property_uid(full_address: str) -> str:
    norm = " ".join(full_address.lower().split())
    return hashlib.sha1(norm.encode()).hexdigest()[:24]


def canonical_contractor_uid(jurisdiction_slug: str, name: str, license_number: str = "") -> str:
    norm = " ".join((name or "").lower().split())
    return hashlib.sha1(f"{jurisdiction_slug}:{norm}:{license_number}".encode()).hexdigest()[:24]
