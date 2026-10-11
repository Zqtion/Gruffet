"""SQLite store: leads, provenance-labelled claims, gate results, cached pages, images.

Every fact is a *claim* with a source and a graphify-style label:
  EXTRACTED  read directly from a source (OSM tag, JSON-LD, mailto:, tel:)
  INFERRED   derived (regex over free text, pattern guess)
  AMBIGUOUS  conflicting or weak evidence
"""
from __future__ import annotations

import json
import sqlite3
import time
import zlib
from pathlib import Path

from .util import haversine_m, lead_id, norm_name

LABELS = ("EXTRACTED", "INFERRED", "AMBIGUOUS")

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, name_norm TEXT NOT NULL, category TEXT,
  lat REAL, lon REAL, region TEXT, score INTEGER DEFAULT 0, tier TEXT DEFAULT 'new',
  tier_reason TEXT DEFAULT '', created_at REAL
);
CREATE INDEX IF NOT EXISTS leads_name_norm ON leads(name_norm);
CREATE TABLE IF NOT EXISTS claims (
  id INTEGER PRIMARY KEY, lead_id TEXT NOT NULL, field TEXT NOT NULL, value TEXT NOT NULL,
  source TEXT NOT NULL, family TEXT NOT NULL, label TEXT NOT NULL, seen_at REAL,
  UNIQUE(lead_id, field, value, source)
);
CREATE INDEX IF NOT EXISTS claims_lead ON claims(lead_id, field);
CREATE TABLE IF NOT EXISTS gates (
  lead_id TEXT NOT NULL, gate TEXT NOT NULL, status TEXT NOT NULL, detail TEXT DEFAULT '',
  PRIMARY KEY (lead_id, gate)
);
CREATE TABLE IF NOT EXISTS verdicts (
  lead_id TEXT PRIMARY KEY, decision TEXT NOT NULL, reason TEXT, decided_at REAL
);
CREATE TABLE IF NOT EXISTS pages (
  url TEXT PRIMARY KEY, final_url TEXT, status INTEGER, error TEXT, body BLOB,
  rendered INTEGER DEFAULT 0, fetched_at REAL
);
CREATE TABLE IF NOT EXISTS images (
  id INTEGER PRIMARY KEY, lead_id TEXT NOT NULL, url TEXT NOT NULL, page_url TEXT, alt TEXT,
  kind TEXT, local_path TEXT, sha1 TEXT, width INTEGER, height INTEGER, fetched_at REAL,
  UNIQUE(lead_id, url)
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY, started_at REAL, command TEXT, params TEXT, summary TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS notes (
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL, created_at REAL
);
CREATE TABLE IF NOT EXISTS competitors (
  id TEXT PRIMARY KEY, url TEXT NOT NULL, host TEXT, note TEXT DEFAULT '', status TEXT DEFAULT 'new', added_at REAL
);
"""


class Store:
    def __init__(self, workdir: str | Path):
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.workdir / "gruffet.db")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.commit()
        self.db.close()

    # -- meta / runs ---------------------------------------------------
    def set_meta(self, key: str, value: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value))
        self.db.commit()

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        r = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

    def log_run(self, command: str, params: dict, summary: dict) -> None:
        self.db.execute(
            "INSERT INTO runs(started_at, command, params, summary) VALUES (?,?,?,?)",
            (time.time(), command, json.dumps(params, default=str), json.dumps(summary, default=str)),
        )
        self.db.commit()

    # -- leads ---------------------------------------------------------
    def upsert_lead(self, name: str, category: str | None, lat: float | None, lon: float | None,
                    region: str | None = None, fuzzy: bool = False) -> tuple[str, bool]:
        """Insert a lead, merging into an existing one with the same name within 150 m.

        Returns (lead_id, created). OSM often maps one business as both a node and a way;
        the proximity merge keeps those from becoming duplicate leads.
        """
        nn = norm_name(name)
        if lat is not None and lon is not None:
            cands = list(self.db.execute("SELECT id, lat, lon FROM leads WHERE name_norm=?", (nn,)))
            # A lead the agent renamed must still absorb re-discovered OSM records under the old name.
            cands += [r for r in self.db.execute(
                "SELECT l.id, l.lat, l.lon, c.value FROM claims c JOIN leads l ON l.id=c.lead_id WHERE c.field='former_name'")
                if norm_name(r["value"]) == nn]
            for r in cands:
                if r["lat"] is not None and haversine_m(lat, lon, r["lat"], r["lon"]) < 150:
                    return r["id"], False
            if fuzzy:  # different sources spell names differently ("Smile Dental" vs "Smile Dental Clinic")
                from rapidfuzz import fuzz
                for r in self.db.execute("SELECT id, name_norm, lat, lon FROM leads WHERE lat IS NOT NULL"):
                    if haversine_m(lat, lon, r["lat"], r["lon"]) < 150 and fuzz.token_set_ratio(nn, r["name_norm"]) >= 88:
                        return r["id"], False
        lid = lead_id(name, lat, lon)
        cur = self.db.execute(
            "INSERT OR IGNORE INTO leads(id,name,name_norm,category,lat,lon,region,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (lid, name, nn, category, lat, lon, region, time.time()),
        )
        self.db.commit()
        return lid, cur.rowcount > 0

    def lead(self, lid: str):
        return self.db.execute("SELECT * FROM leads WHERE id=?", (lid,)).fetchone()

    def leads(self, tier: str | tuple[str, ...] | None = None):
        if tier is None:
            return self.db.execute("SELECT * FROM leads ORDER BY score DESC, name").fetchall()
        tiers = (tier,) if isinstance(tier, str) else tuple(tier)
        q = ",".join("?" * len(tiers))
        return self.db.execute(f"SELECT * FROM leads WHERE tier IN ({q}) ORDER BY score DESC, name", tiers).fetchall()

    def set_tier(self, lid: str, score: int, tier: str, reason: str) -> None:
        self.db.execute("UPDATE leads SET score=?, tier=?, tier_reason=? WHERE id=?", (score, tier, reason, lid))
        self.db.commit()

    # -- claims --------------------------------------------------------
    def add_claim(self, lid: str, field: str, value: str, source: str, label: str = "EXTRACTED") -> None:
        if not value:
            return
        assert label in LABELS, label
        family = source.split(":", 1)[0]
        self.db.execute(
            "INSERT OR IGNORE INTO claims(lead_id,field,value,source,family,label,seen_at) VALUES (?,?,?,?,?,?,?)",
            (lid, field, str(value).strip(), source, family, label, time.time()),
        )

    def claims(self, lid: str, field: str | None = None):
        if field:
            return self.db.execute("SELECT * FROM claims WHERE lead_id=? AND field=? ORDER BY id", (lid, field)).fetchall()
        return self.db.execute("SELECT * FROM claims WHERE lead_id=? ORDER BY field, id", (lid,)).fetchall()

    def values(self, lid: str, field: str) -> list[str]:
        seen: list[str] = []
        for r in self.claims(lid, field):
            if r["value"] not in seen:
                seen.append(r["value"])
        return seen

    def families_for(self, lid: str, field: str, value: str) -> set[str]:
        rows = self.db.execute(
            "SELECT DISTINCT family FROM claims WHERE lead_id=? AND field=? AND value=?", (lid, field, value)
        ).fetchall()
        return {r["family"] for r in rows}

    def clear_claims(self, lid: str, source_prefix: str) -> None:
        self.db.execute("DELETE FROM claims WHERE lead_id=? AND source LIKE ?", (lid, source_prefix + "%"))

    # -- competitors (entity id is "c:<host>"; their facts live in the same claims table) ----------
    def add_competitor(self, url: str, note: str = "") -> str:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or url).lower().removeprefix("www.")
        cid = f"c:{host}"
        self.db.execute("INSERT OR IGNORE INTO competitors(id,url,host,note,added_at) VALUES (?,?,?,?,?)",
                        (cid, url, host, note, time.time()))
        self.db.commit()
        return cid

    def competitors(self):
        return self.db.execute("SELECT * FROM competitors ORDER BY host").fetchall()

    def set_competitor_status(self, cid: str, status: str) -> None:
        self.db.execute("UPDATE competitors SET status=? WHERE id=?", (status, cid))

    # -- analysis notes written by the agent (exported as the "Analysis" sheet) ----------------
    def add_note(self, title: str, body: str) -> None:
        """Saving a note with an existing title replaces it, so an analysis can be corrected."""
        self.db.execute("DELETE FROM notes WHERE title=?", (title,))
        self.db.execute("INSERT INTO notes(title, body, created_at) VALUES (?,?,?)", (title, body, time.time()))
        self.db.commit()

    def notes(self):
        return self.db.execute("SELECT * FROM notes ORDER BY id").fetchall()

    # -- gates / verdicts -----------------------------------------------
    def set_gate(self, lid: str, gate: str, status: str, detail: str = "") -> None:
        assert status in ("pass", "fail", "unknown")
        self.db.execute("INSERT OR REPLACE INTO gates VALUES (?,?,?,?)", (lid, gate, status, detail))

    def gates(self, lid: str) -> dict[str, sqlite3.Row]:
        return {r["gate"]: r for r in self.db.execute("SELECT * FROM gates WHERE lead_id=?", (lid,))}

    def set_verdict(self, lid: str, decision: str, reason: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO verdicts VALUES (?,?,?,?)", (lid, decision, reason, time.time()))
        self.db.commit()

    def verdict(self, lid: str):
        return self.db.execute("SELECT * FROM verdicts WHERE lead_id=?", (lid,)).fetchone()

    # -- page cache -----------------------------------------------------
    def get_page(self, url: str, max_age_s: float | None = None):
        r = self.db.execute("SELECT * FROM pages WHERE url=?", (url,)).fetchone()
        if not r:
            return None
        if max_age_s is not None and time.time() - (r["fetched_at"] or 0) > max_age_s:
            return None
        return r

    def put_page(self, url: str, final_url: str | None, status: int | None, error: str | None,
                 html: str | None, rendered: bool) -> None:
        body = zlib.compress(html.encode("utf-8", "replace")) if html else None
        self.db.execute(
            "INSERT OR REPLACE INTO pages VALUES (?,?,?,?,?,?,?)",
            (url, final_url, status, error, body, int(rendered), time.time()),
        )

    @staticmethod
    def page_html(row) -> str:
        return zlib.decompress(row["body"]).decode("utf-8", "replace") if row and row["body"] else ""

    # -- images ---------------------------------------------------------
    def add_image(self, lid: str, url: str, page_url: str, alt: str, kind: str) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO images(lead_id,url,page_url,alt,kind) VALUES (?,?,?,?,?)",
            (lid, url, page_url, alt, kind),
        )

    def images(self, lid: str | None = None, downloaded_only: bool = False):
        q = "SELECT * FROM images"
        conds, args = [], []
        if lid:
            conds.append("lead_id=?")
            args.append(lid)
        if downloaded_only:
            conds.append("local_path IS NOT NULL")
        if conds:
            q += " WHERE " + " AND ".join(conds)
        return self.db.execute(q + " ORDER BY lead_id, id", args).fetchall()

    def commit(self) -> None:
        self.db.commit()
