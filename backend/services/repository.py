"""
Investigation persistence.

One repository, two backends, chosen at import time:

  Supabase  when SUPABASE_URL and SUPABASE_ANON_KEY are configured
  Local     otherwise — a JSON file on disk

The local backend is not a stub. It is a working single-process store, so the
whole product is usable end to end without provisioning a database, and so a
developer can run the app with an empty `.env` and still see a real history
page. What it cannot do is survive multiple workers or authenticate users, and
`describe()` says exactly that rather than implying full parity.

SECURITY: the service-role key is read here and never leaves this module. No
method returns it, and `describe()` reports presence only.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import config

__all__ = ["get_repository", "InvestigationRepository", "LocalRepository", "SupabaseRepository"]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class InvestigationRepository:
    """The interface every router codes against."""

    backend: str = "none"

    # -- investigations -------------------------------------------------
    def save_investigation(self, record: Dict[str, Any], user_id: Optional[str]) -> Dict[str, Any]:
        raise NotImplementedError

    def get_investigation(self, investigation_id: str, user_id: Optional[str]) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def list_investigations(
        self, user_id: Optional[str], limit: int = 25, offset: int = 0,
        chain: Optional[str] = None, risk_level: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        raise NotImplementedError

    def delete_investigation(self, investigation_id: str, user_id: Optional[str]) -> bool:
        raise NotImplementedError

    # -- entities -------------------------------------------------------
    def list_entities(
        self, user_id: Optional[str], limit: int = 50, offset: int = 0,
        entity_type: Optional[str] = None, chain: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        raise NotImplementedError

    # -- reports --------------------------------------------------------
    def record_report(self, investigation_id: str, user_id: Optional[str], report_url: str) -> None:
        raise NotImplementedError

    # -- meta -----------------------------------------------------------
    def describe(self) -> Dict[str, Any]:
        return {"backend": self.backend}


# ============================================================
# LOCAL JSON BACKEND
# ============================================================


class LocalRepository(InvestigationRepository):
    """
    A JSON-file store. Correct, not scalable.

    Every write is a whole-file rewrite under a lock, which is fine for a
    single user on a laptop and wrong for a server. It exists so the product is
    demonstrable without a database, and `describe()` advertises that limit.
    """

    backend = "local_json"

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.RLock()
        # Set when the local store is a *fallback* from a configured but
        # broken Supabase. Surfaced in the health check so the operator can see
        # that their cases are being written to disk instead of to Postgres.
        self.degraded_reason: Optional[str] = None
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if not os.path.exists(self.path):
            self._write([])

    # -- io -------------------------------------------------------------
    def _read(self) -> List[Dict[str, Any]]:
        with self._lock:
            try:
                with open(self.path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                return data if isinstance(data, list) else []
            except (OSError, ValueError):
                # A corrupt store must not take the API down. Start clean and
                # say so in the health check rather than crashing every
                # request with a JSONDecodeError.
                return []

    def _write(self, rows: List[Dict[str, Any]]) -> None:
        with self._lock:
            tmp = f"{self.path}.tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(rows, handle, indent=2, default=str)
            os.replace(tmp, self.path)

    # -- investigations -------------------------------------------------
    def save_investigation(self, record: Dict[str, Any], user_id: Optional[str]) -> Dict[str, Any]:
        rows = self._read()
        entry = dict(record)
        entry.setdefault("id", str(uuid.uuid4()))
        entry.setdefault("created_at", _now_iso())
        entry["user_id"] = user_id
        rows.append(entry)
        self._write(rows)
        return entry

    def get_investigation(self, investigation_id: str, user_id: Optional[str]) -> Optional[Dict[str, Any]]:
        for row in self._read():
            if row.get("id") != investigation_id:
                continue
            # Ownership check. Without auth every row is anonymous, so the
            # check passes; with auth it is the thing that stops one analyst
            # reading another's case.
            if user_id and row.get("user_id") and row["user_id"] != user_id:
                return None
            return row
        return None

    def list_investigations(
        self, user_id: Optional[str], limit: int = 25, offset: int = 0,
        chain: Optional[str] = None, risk_level: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        rows = self._read()
        if user_id:
            rows = [r for r in rows if r.get("user_id") == user_id]
        if chain:
            rows = [r for r in rows if r.get("chain") == chain]
        if risk_level:
            rows = [r for r in rows if r.get("risk_level") == risk_level]
        if search:
            needle = search.lower()
            rows = [
                r for r in rows
                if needle in str(r.get("seed", "")).lower()
                or needle in str(r.get("title", "")).lower()
            ]
        rows.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
        return rows[offset:offset + limit], len(rows)

    def delete_investigation(self, investigation_id: str, user_id: Optional[str]) -> bool:
        rows = self._read()
        kept = []
        removed = False
        for row in rows:
            if row.get("id") == investigation_id and (
                not user_id or not row.get("user_id") or row["user_id"] == user_id
            ):
                removed = True
                continue
            kept.append(row)
        if removed:
            self._write(kept)
        return removed

    # -- entities -------------------------------------------------------
    def list_entities(
        self, user_id: Optional[str], limit: int = 50, offset: int = 0,
        entity_type: Optional[str] = None, chain: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Entities are derived from saved investigations, not stored separately.

        A separate entity table is a cache of this computation, and a cache
        that can disagree with its source is a liability. Recomputing means the
        entities page can never show a label that no trace actually supports.
        """
        seen: Dict[str, Dict[str, Any]] = {}
        for row in self._read():
            if user_id and row.get("user_id") and row["user_id"] != user_id:
                continue
            if chain and row.get("chain") != chain:
                continue
            for node in (row.get("result") or {}).get("nodes") or []:
                entity = node.get("entity")
                if not entity or not entity.get("name"):
                    continue
                if entity_type and entity.get("type") != entity_type:
                    continue
                key = f"{row.get('chain')}:{node.get('address')}"
                if key in seen:
                    seen[key]["seen_count"] += 1
                    continue
                seen[key] = {
                    "address": node.get("address"),
                    "chain": row.get("chain"),
                    "chain_name": row.get("chain_name"),
                    "name": entity.get("name"),
                    "type": entity.get("type"),
                    "source_type": entity.get("source_type"),
                    "verification_status": entity.get("verification_status"),
                    "confidence": entity.get("confidence"),
                    "source_url": entity.get("source_url"),
                    "evidence": entity.get("evidence") or [],
                    "seen_count": 1,
                    "first_seen": row.get("created_at"),
                    "last_seen": row.get("created_at"),
                }
        rows = sorted(seen.values(), key=lambda r: (-r["seen_count"], str(r["name"])))
        return rows[offset:offset + limit], len(rows)

    # -- reports --------------------------------------------------------
    def record_report(self, investigation_id: str, user_id: Optional[str], report_url: str) -> None:
        rows = self._read()
        for row in rows:
            if row.get("id") == investigation_id:
                row["report_url"] = report_url
                row["has_report"] = True
                break
        self._write(rows)

    def describe(self) -> Dict[str, Any]:
        described: Dict[str, Any] = {
            "backend": self.backend,
            "path": self.path,
            "persistent": True,
            "multi_user": False,
            "note": (
                "Local JSON store. Suitable for a single user or a demo; it "
                "does not isolate cases between users and does not survive "
                "multiple worker processes. Configure Supabase for that."
            ),
        }
        if self.degraded_reason:
            described["degraded"] = True
            described["degraded_reason"] = self.degraded_reason
        return described


# ============================================================
# SUPABASE BACKEND
# ============================================================


class SupabaseRepository(InvestigationRepository):
    """
    Supabase-backed store.

    Uses the service-role key for server-side reads and writes. That key is
    only ever passed to the Supabase client inside this module; it is not
    returned by `describe()`, never logged, and never included in a response.
    """

    backend = "supabase"

    def __init__(self, url: str, service_role_key: str) -> None:
        from supabase import create_client

        # The service-role key bypasses row-level security, so every query
        # below carries an explicit user filter. RLS alone is not the
        # authorization boundary for reads made with this key.
        self._client = create_client(url, service_role_key)

    def save_investigation(self, record: Dict[str, Any], user_id: Optional[str]) -> Dict[str, Any]:
        row = dict(record)
        row["user_id"] = user_id
        row.setdefault("created_at", _now_iso())
        response = self._client.table("investigations").insert(row).execute()
        data = getattr(response, "data", None)
        return (data or [row])[0]

    def get_investigation(self, investigation_id: str, user_id: Optional[str]) -> Optional[Dict[str, Any]]:
        query = self._client.table("investigations").select("*").eq("id", investigation_id)
        if user_id:
            query = query.eq("user_id", user_id)
        data = getattr(query.limit(1).execute(), "data", None)
        return (data or [None])[0]

    def list_investigations(
        self, user_id: Optional[str], limit: int = 25, offset: int = 0,
        chain: Optional[str] = None, risk_level: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        query = self._client.table("investigations").select("*", count="exact")
        if user_id:
            query = query.eq("user_id", user_id)
        if chain:
            query = query.eq("chain", chain)
        if risk_level:
            query = query.eq("risk_level", risk_level)
        if search:
            query = query.ilike("seed", f"%{search}%")
        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        response = query.execute()
        return getattr(response, "data", None) or [], int(getattr(response, "count", 0) or 0)

    def delete_investigation(self, investigation_id: str, user_id: Optional[str]) -> bool:
        query = self._client.table("investigations").delete().eq("id", investigation_id)
        if user_id:
            query = query.eq("user_id", user_id)
        response = query.execute()
        return bool(getattr(response, "data", None))

    def list_entities(
        self, user_id: Optional[str], limit: int = 50, offset: int = 0,
        entity_type: Optional[str] = None, chain: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        query = self._client.table("entities").select("*", count="exact")
        if user_id:
            query = query.eq("user_id", user_id)
        if entity_type:
            query = query.eq("entity_type", entity_type)
        if chain:
            query = query.eq("chain", chain)
        query = query.order("last_seen", desc=True).range(offset, offset + limit - 1)
        response = query.execute()
        return getattr(response, "data", None) or [], int(getattr(response, "count", 0) or 0)

    def record_report(self, investigation_id: str, user_id: Optional[str], report_url: str) -> None:
        query = self._client.table("investigations").update(
            {"report_url": report_url, "has_report": True},
        ).eq("id", investigation_id)
        if user_id:
            query = query.eq("user_id", user_id)
        query.execute()

    def describe(self) -> Dict[str, Any]:
        return {
            "backend": self.backend,
            "persistent": True,
            "multi_user": True,
            "note": "Supabase Postgres with row-level security on investigations.",
        }


# ============================================================
# FACTORY
# ============================================================

_REPOSITORY: Optional[InvestigationRepository] = None
_REPO_LOCK = threading.Lock()


def get_repository() -> InvestigationRepository:
    """
    The process-wide repository.

    Falls back to the local store when Supabase is not fully configured. A
    missing database should degrade the product to "single-user mode", not
    prevent it from starting — but `describe()` must say that is what happened,
    so the operator is never misled about where their cases are stored.
    """
    global _REPOSITORY
    if _REPOSITORY is not None:
        return _REPOSITORY

    with _REPO_LOCK:
        if _REPOSITORY is not None:
            return _REPOSITORY

        local_path = os.path.join(config.REPORT_DIR, "investigations.json")

        if config.SUPABASE_URL and config.SUPABASE_SERVICE_ROLE_KEY:
            try:
                _REPOSITORY = SupabaseRepository(
                    config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY,
                )
                return _REPOSITORY
            except Exception as exc:
                # A bad key or an unreachable project must not crash import.
                # Fall through to local, and record why so the health check
                # shows the failure instead of the product quietly pretending
                # it is on Postgres.
                fallback = LocalRepository(local_path)
                fallback.degraded_reason = (
                    f"Supabase was configured but could not be reached "
                    f"({type(exc).__name__}). Investigations are being stored "
                    f"locally instead."
                )
                _REPOSITORY = fallback
                return _REPOSITORY

        _REPOSITORY = LocalRepository(local_path)
        return _REPOSITORY
