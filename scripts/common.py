"""Shared plumbing for the catalogue builders.

The build has one rule, inherited from the app: **it never decides what a licence
means.** Every source records the raw signals it was given — the licence code, its
version, the deed URL — under a `lk` ("licence kind") tag, and AssetVault's own
`LicenseRegistry` resolves them on the device. That keeps a single source of truth
for licence semantics in the app, where the guarantee is stated, instead of forking
it into a Python script that would silently drift.

Records use short keys because the whole catalogue ships as one file to a phone.
The mapping is mirrored by `CatalogCodec.kt` on the app side; the two must change
together.
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from typing import Any, Iterable

import requests

# Wikimedia's API etiquette asks for a descriptive agent with a contact URL, and
# several other sources rate-limit anonymous traffic harder without one.
USER_AGENT = (
    "AssetVaultCatalogBot/1.0 (+https://github.com/NikhilKain/assetvault-appdata; "
    "builds the offline index for the AssetVault Android app)"
)

TIMEOUT = 30


class Http:
    """A requests session with retry, backoff and a shared politeness delay."""

    def __init__(self, delay: float = 0.0):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.session.headers["Accept"] = "application/json"
        self.delay = delay

    def get_json(self, url: str, params: dict | None = None, tries: int = 4) -> Any:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        last = None
        for attempt in range(tries):
            try:
                if self.delay:
                    time.sleep(self.delay)
                r = self.session.get(url, params=params, timeout=TIMEOUT)
                # 429 and 5xx are worth waiting out; 4xx otherwise is a real answer.
                if r.status_code == 429 or r.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {r.status_code}")
                r.raise_for_status()
                return r.json()
            except Exception as e:  # noqa: BLE001 - the builder must survive any source
                last = e
                backoff = (2 ** attempt) + random.random()
                log(f"  retry {attempt + 1}/{tries} after {backoff:.1f}s — {url} — {e}")
                time.sleep(backoff)
        raise RuntimeError(f"giving up on {url}: {last}")


def log(msg: str) -> None:
    print(msg, flush=True)


# --- Licence kinds -------------------------------------------------------------------
#
# These are tags, not judgements. Each one tells the app which of its *existing*
# resolution paths to run, so a catalogue asset and a live-API asset of the same
# thing end up with byte-identical licence objects.

LK_RAW = "raw"                    # resolve lc/lv/lu through LicenseRegistry
LK_CC0_PER_ASSET = "cc0_asset"    # source flagged this individual item as CC0
LK_CC0_PROVIDER = "cc0_provider"  # whole catalogue is CC0 (Poly Haven)
LK_NASA = "nasa"                  # NASA media guidelines — not a PD dedication
LK_RESERVED = "reserved"          # source says rights reserved; app shows unverified
LK_OFL = "ofl"                    # SIL Open Font Licence
LK_GOOGLE_FONTS = "google_fonts"  # open source, but the API won't say which of the three


def clean(value: Any) -> str | None:
    """Trims a string and turns blanks into None, matching `String.cleanOrNull()`."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    return v or None


HTML_TAG = re.compile(r"<[^>]*>")


def strip_html(value: Any) -> str | None:
    v = clean(value)
    if v is None:
        return None
    v = HTML_TAG.sub(" ", v)
    for entity, char in (("&nbsp;", " "), ("&amp;", "&"), ("&quot;", '"'), ("&#039;", "'")):
        v = v.replace(entity, char)
    return clean(v)


def http_url(value: Any) -> str | None:
    """Mirrors `asHttpUrlOrNull` — only absolute http(s) URLs survive."""
    v = clean(value)
    if v is None:
        return None
    return v if v.startswith("http://") or v.startswith("https://") else None


def asset(
    *,
    provider: str,
    provider_asset_id: str,
    title: str,
    type: str,
    source_url: str,
    lk: str,
    thumbnail: str | None = None,
    preview: str | None = None,
    audio_preview: str | None = None,
    direct_file: str | None = None,
    file_format: str | None = None,
    width: int | None = None,
    height: int | None = None,
    size_bytes: int | None = None,
    duration_ms: int | None = None,
    author: str | None = None,
    author_url: str | None = None,
    license_code: str | None = None,
    license_version: str | None = None,
    license_url: str | None = None,
    license_short_name: str | None = None,
    license_terms: str | None = None,
    tags: Iterable[str] | None = None,
    description: str | None = None,
    attribution: str | None = None,
    rank: float = 0.0,
) -> dict | None:
    """Builds one catalogue record, or None when it is not worth shipping.

    A record with no landing page or no title is dropped: the app's detail screen
    needs somewhere honest to send the user, and an untitled row is dead weight in
    a file that has to travel over a phone connection.
    """
    src = http_url(source_url)
    name = clean(title)
    if not src or not name or not provider_asset_id:
        return None

    record: dict[str, Any] = {
        "i": f"{provider}:{provider_asset_id}",
        "p": provider,
        "a": str(provider_asset_id),
        "t": name[:180],
        "y": type,
        "s": src,
        "lk": lk,
    }

    def put(key: str, value: Any) -> None:
        if value not in (None, "", [], 0):
            record[key] = value

    put("th", http_url(thumbnail))
    put("pv", http_url(preview))
    put("ap", http_url(audio_preview))
    put("df", http_url(direct_file))
    put("f", clean(file_format))
    put("w", width if isinstance(width, int) and width > 0 else None)
    put("h", height if isinstance(height, int) and height > 0 else None)
    put("sz", size_bytes if isinstance(size_bytes, int) and size_bytes > 0 else None)
    put("du", duration_ms if isinstance(duration_ms, int) and duration_ms > 0 else None)
    put("an", clean(author))
    put("au", http_url(author_url))
    put("lc", clean(license_code))
    put("lv", clean(license_version))
    put("lu", http_url(license_url))
    # Commons and friends state the licence a second and third way — a human-readable
    # short name and the prose usage terms. The app walks all three in order, so all
    # three travel; dropping the weaker ones would make CDN rows resolve worse than
    # live ones for exactly the files whose licence is hardest to read.
    put("ln", clean(license_short_name))
    put("lt", clean(license_terms))
    put("d", clean(description)[:600] if clean(description) else None)
    put("at", clean(attribution))

    if tags:
        seen: list[str] = []
        for tag in tags:
            t = clean(tag)
            if not t:
                continue
            t = t.lower()
            if len(t) < 2 or t in seen:
                continue
            seen.append(t)
            if len(seen) >= 18:
                break
        put("tg", seen)

    if rank:
        record["r"] = round(float(rank), 3)

    # Nothing to show and nothing to play is nothing to put in a grid — except for the
    # kinds the app draws itself. A font tile *is* its name set in the typeface and an
    # audio tile is a waveform, so those are complete records without an image.
    if type not in SELF_RENDERING_TYPES:
        if not record.get("th") and not record.get("pv") and not record.get("ap"):
            return None

    return record


# Asset types whose tile is drawn from metadata rather than from a picture. Mirrors the
# branches in the app's AssetTile.
SELF_RENDERING_TYPES = {"FONT", "UI_KIT", "AUDIO", "MUSIC"}


def write_json(path: str, payload: Any) -> int:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # separators: the catalogue is machine-read only, so every space is wasted bytes
    # on someone's mobile data.
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    size = len(text.encode("utf-8"))
    log(f"  wrote {path} — {size / 1024:.0f} KB")
    return size


def guard(name: str, fn, *args, **kwargs):
    """Runs one source and converts a total failure into an empty result.

    A source being down must never fail the whole build — the app already knows how
    to work from a catalogue that is missing a provider, and shipping yesterday's
    file for one source beats shipping nothing for all of them.
    """
    started = time.time()
    try:
        items = fn(*args, **kwargs) or []
        log(f"[{name}] {len(items)} assets in {time.time() - started:.0f}s")
        return items
    except Exception as e:  # noqa: BLE001
        print(f"[{name}] FAILED: {e}", file=sys.stderr, flush=True)
        return []
