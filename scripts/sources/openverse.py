"""Openverse — the widest licence-clean source there is.

Openverse has no browse endpoint, so breadth comes from running a spread of seed
queries and keeping the union. The seeds are chosen to cover what people actually
search this app for rather than to maximise the row count.

Every result carries a machine-readable licence code, version and deed URL. Those
three travel verbatim as `lc`/`lv`/`lu` and resolve on the device, so a CDN row and a
live row for the same photo produce the same badge.
"""

from __future__ import annotations

from ..common import LK_RAW, Http, asset, clean, http_url, log

BASE = "https://api.openverse.org/v1"
PROVIDER = "openverse"

PAGE_SIZE = 20
PAGES_PER_SEED = 2

IMAGE_SEEDS = [
    ("nature", "PHOTO"), ("mountains", "PHOTO"), ("ocean", "PHOTO"),
    ("forest", "PHOTO"), ("city skyline", "PHOTO"), ("architecture", "PHOTO"),
    ("portrait", "PHOTO"), ("food", "PHOTO"), ("coffee", "PHOTO"),
    ("workspace desk", "PHOTO"), ("technology", "PHOTO"), ("flowers", "PHOTO"),
    ("animals", "PHOTO"), ("sunset", "WALLPAPER"), ("night sky", "WALLPAPER"),
    ("abstract background", "WALLPAPER"), ("gradient", "WALLPAPER"),
    ("minimal", "WALLPAPER"), ("texture", "TEXTURE"), ("wood texture", "TEXTURE"),
    ("stone wall", "TEXTURE"), ("fabric", "TEXTURE"), ("paper texture", "TEXTURE"),
    ("seamless pattern", "PATTERN"), ("geometric pattern", "PATTERN"),
    ("floral pattern", "PATTERN"), ("botanical illustration", "ILLUSTRATION"),
    ("vintage illustration", "ILLUSTRATION"), ("map", "ILLUSTRATION"),
    ("diagram", "ILLUSTRATION"), ("poster", "ILLUSTRATION"),
    ("watercolour", "ILLUSTRATION"), ("street", "PHOTO"), ("travel", "PHOTO"),
]

AUDIO_SEEDS = [
    ("ambient", "MUSIC"), ("piano", "MUSIC"), ("guitar", "MUSIC"),
    ("electronic", "MUSIC"), ("cinematic", "MUSIC"),
    ("footsteps", "AUDIO"), ("rain", "AUDIO"), ("birds", "AUDIO"),
    ("ui click", "AUDIO"), ("whoosh", "AUDIO"), ("crowd", "AUDIO"),
]

CATEGORY_TO_TYPE = {
    "illustration": "ILLUSTRATION",
    "digitized_artwork": "ILLUSTRATION",
    "digitised_artwork": "ILLUSTRATION",
    "photograph": "PHOTO",
}


def _image_type(item: dict, fallback: str) -> str:
    mapped = CATEGORY_TO_TYPE.get((item.get("category") or "").lower())
    # The seed knows what we were looking for; the category only overrides it when it
    # disagrees about the *kind* of picture, not about how we intend to file it.
    if mapped and fallback in ("PHOTO", "WALLPAPER") and mapped == "ILLUSTRATION":
        return "ILLUSTRATION"
    return fallback


def _audio_type(item: dict, fallback: str) -> str:
    category = (item.get("category") or "").lower()
    if category == "music" or item.get("genres"):
        return "MUSIC"
    if category in ("sound_effect", "sound"):
        return "AUDIO"
    return fallback


def _map_image(item: dict, asset_type: str, rank: float) -> dict | None:
    landing = http_url(item.get("foreign_landing_url")) or http_url(item.get("url"))
    creator = clean(item.get("creator"))
    title = clean(item.get("title")) or (f"Untitled by {creator}" if creator else "Untitled")
    width, height = item.get("width"), item.get("height")

    return asset(
        provider=PROVIDER,
        provider_asset_id=item.get("id") or "",
        title=title,
        type=_image_type(item, asset_type),
        thumbnail=item.get("thumbnail") or item.get("url"),
        preview=item.get("url"),
        source_url=landing or "",
        direct_file=item.get("url"),
        file_format=(clean(item.get("filetype")) or "").upper() or None,
        width=width if isinstance(width, int) else None,
        height=height if isinstance(height, int) else None,
        size_bytes=item.get("filesize") if isinstance(item.get("filesize"), int) else None,
        author=creator,
        author_url=item.get("creator_url"),
        lk=LK_RAW,
        license_code=item.get("license"),
        license_version=item.get("license_version"),
        license_url=item.get("license_url"),
        tags=[t.get("name") for t in (item.get("tags") or []) if isinstance(t, dict)],
        description=f"From {item['source']} via Openverse" if item.get("source") else None,
        # Openverse composes its own attribution line; it is more precise than
        # anything we would assemble, so it is carried through as-is.
        attribution=clean(item.get("attribution")),
        rank=rank,
    )


def _map_audio(item: dict, asset_type: str, rank: float) -> dict | None:
    landing = http_url(item.get("foreign_landing_url")) or http_url(item.get("url"))
    creator = clean(item.get("creator"))
    duration = item.get("duration")

    return asset(
        provider=PROVIDER,
        provider_asset_id=item.get("id") or "",
        title=clean(item.get("title")) or (f"Untitled by {creator}" if creator else "Untitled"),
        type=_audio_type(item, asset_type),
        audio_preview=item.get("url"),
        source_url=landing or "",
        direct_file=item.get("url"),
        file_format=(clean(item.get("filetype")) or "").upper() or None,
        duration_ms=duration if isinstance(duration, int) else None,
        author=creator,
        author_url=item.get("creator_url"),
        lk=LK_RAW,
        license_code=item.get("license"),
        license_version=item.get("license_version"),
        license_url=item.get("license_url"),
        tags=[t.get("name") for t in (item.get("tags") or []) if isinstance(t, dict)],
        description=f"From {item['source']} via Openverse" if item.get("source") else None,
        attribution=clean(item.get("attribution")),
        rank=rank,
    )


def _harvest(http: Http, media: str, seeds, mapper) -> list[dict]:
    out: list[dict] = []
    for seed, asset_type in seeds:
        got = 0
        for page in range(1, PAGES_PER_SEED + 1):
            try:
                data = http.get_json(
                    f"{BASE}/{media}/",
                    {"q": seed, "page": page, "page_size": PAGE_SIZE, "mature": "false"},
                )
            except Exception as e:  # noqa: BLE001
                log(f"  [openverse] {media} '{seed}' p{page}: {e}")
                break

            results = data.get("results") or []
            if not results:
                break
            for position, item in enumerate(results):
                # Rank falls off within a seed so the top of each query stays the
                # top of the rail it feeds.
                record = mapper(item, asset_type, max(0.0, 40 - (page - 1) * PAGE_SIZE - position))
                if record:
                    out.append(record)
                    got += 1
        log(f"  [openverse] {media} '{seed}': {got}")
    return out


def fetch(http: Http) -> list[dict]:
    return (
        _harvest(http, "images", IMAGE_SEEDS, _map_image)
        + _harvest(http, "audio", AUDIO_SEEDS, _map_audio)
    )
