"""Image extraction -> local files. Only the business's own site images, robots.txt respected.

We record source URL + page for every image. Downloaded files stay the property of their
owners: use them for analysis and reference, not republication, unless you have permission.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import time
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .fetch import Fetcher
from .store import Store

_EXT = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif", "AVIF": "avif"}


async def download_images(store: Store, per_lead: int = 5, tiers: tuple[str, ...] = ("perfect", "agent-approved"),
                          min_px: int = 200, concurrency: int = 8, respect_robots: bool = True,
                          retry_failed: bool = False) -> dict:
    out_dir = store.workdir / "images"
    summary = {"leads": 0, "downloaded": 0, "skipped_small": 0, "failed": 0, "duplicates": 0}
    seen_sha: set[str] = {r["sha1"] for r in store.images(downloaded_only=True) if r["sha1"]}
    async with Fetcher(store, concurrency=concurrency, render="never", respect_robots=respect_robots) as f:
        for lead in store.leads(tiers):
            summary["leads"] += 1
            rows = [r for r in store.images(lead["id"]) if retry_failed or r["fetched_at"] is None]
            have = len([r for r in store.images(lead["id"], downloaded_only=True) if r["kind"] != "logo"])
            order = {"cover": 0, "photo": 1, "logo": 2}
            rows.sort(key=lambda r: (order.get(r["kind"], 3), r["id"]))
            wanted = [r for r in rows if r["kind"] != "logo"][: max(0, per_lead - have)]
            wanted += [r for r in rows if r["kind"] == "logo"][:1]

            async def grab(row):
                data, err = await f.get_bytes(row["url"])
                return row, data, err

            for row, data, err in await asyncio.gather(*(grab(r) for r in wanted)):
                now = time.time()
                if not data:
                    store.db.execute("UPDATE images SET fetched_at=? WHERE id=?", (now, row["id"]))
                    summary["failed"] += 1
                    continue
                try:
                    im = Image.open(io.BytesIO(data))
                    im.load()
                except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
                    store.db.execute("UPDATE images SET fetched_at=? WHERE id=?", (now, row["id"]))
                    summary["failed"] += 1
                    continue
                w, h = im.size
                if row["kind"] != "logo" and (w < min_px or h < min_px):
                    store.db.execute("UPDATE images SET fetched_at=?, width=?, height=? WHERE id=?", (now, w, h, row["id"]))
                    summary["skipped_small"] += 1
                    continue
                sha = hashlib.sha1(data).hexdigest()
                if sha in seen_sha:
                    store.db.execute("UPDATE images SET fetched_at=?, sha1=? WHERE id=?", (now, sha, row["id"]))
                    summary["duplicates"] += 1
                    continue
                seen_sha.add(sha)
                ext = _EXT.get(im.format or "", "img")
                path = out_dir / lead["id"] / f"{sha[:12]}.{ext}"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                store.db.execute(
                    "UPDATE images SET local_path=?, sha1=?, width=?, height=?, fetched_at=? WHERE id=?",
                    (str(path.relative_to(store.workdir)), sha, w, h, now, row["id"]))
                summary["downloaded"] += 1
            store.commit()
    store.log_run("images", {"per_lead": per_lead, "min_px": min_px}, summary)
    return summary


def make_thumbnail(path: Path, px: int = 90) -> bytes | None:
    try:
        with Image.open(path) as im:
            rgba = im.convert("RGBA")  # flatten transparency onto white (palette PNGs warn otherwise)
            im = Image.new("RGB", rgba.size, "white")
            im.paste(rgba, mask=rgba.split()[3])
            im.thumbnail((px, px))
            buf = io.BytesIO()
            im.save(buf, "PNG")
            return buf.getvalue()
    except (OSError, UnidentifiedImageError):
        return None
