"""Art Institute of Chicago.

The museum publishes an `is_public_domain` flag per artwork, which is a per-asset
declaration and the strongest tier the app recognises. Everything else is recorded as
rights-reserved — not omitted, because a missing row reads as permission by silence.
"""

from __future__ import annotations

from ..common import LK_CC0_PER_ASSET, LK_RESERVED, Http, asset, clean, log

BASE = "https://api.artic.edu/api/v1"
DEFAULT_IIIF = "https://www.artic.edu/iiif/2"
PROVIDER = "artic"

FIELDS = (
    "id,title,image_id,artist_title,is_public_domain,thumbnail,term_titles,"
    "classification_title,date_display,medium_display"
)

PAGE_SIZE = 100
PAGES = 12


def _classify(classification: str | None) -> str:
    lower = (classification or "").lower()
    if "photograph" in lower:
        return "PHOTO"
    if "textile" in lower:
        return "PATTERN"
    return "ILLUSTRATION"


def fetch(http: Http) -> list[dict]:
    out: list[dict] = []

    for page in range(1, PAGES + 1):
        try:
            data = http.get_json(
                f"{BASE}/artworks",
                {"page": page, "limit": PAGE_SIZE, "fields": FIELDS},
            )
        except Exception as e:  # noqa: BLE001
            log(f"  [artic] page {page}: {e}")
            break

        iiif = (data.get("config") or {}).get("iiif_url") or DEFAULT_IIIF
        items = data.get("data") or []
        if not items:
            break

        got = 0
        for position, item in enumerate(items):
            image_id = item.get("image_id")
            artwork_id = item.get("id")
            title = clean(item.get("title"))
            # No image is nothing to put in a grid, whatever the licence says.
            if not image_id or not artwork_id or not title:
                continue

            public_domain = bool(item.get("is_public_domain"))
            artist = clean(item.get("artist_title"))
            thumbnail = item.get("thumbnail") or {}

            record = asset(
                provider=PROVIDER,
                provider_asset_id=str(artwork_id),
                title=title,
                type=_classify(item.get("classification_title")),
                thumbnail=f"{iiif}/{image_id}/full/400,/0/default.jpg",
                preview=f"{iiif}/{image_id}/full/1686,/0/default.jpg",
                source_url=f"https://www.artic.edu/artworks/{artwork_id}",
                direct_file=(
                    f"{iiif}/{image_id}/full/full/0/default.jpg" if public_domain else None
                ),
                file_format="JPG",
                width=thumbnail.get("width") if isinstance(thumbnail.get("width"), int) else None,
                height=thumbnail.get("height") if isinstance(thumbnail.get("height"), int) else None,
                author=artist,
                lk=LK_CC0_PER_ASSET if public_domain else LK_RESERVED,
                tags=item.get("term_titles") or [],
                description=" · ".join(
                    p for p in (clean(item.get("date_display")), clean(item.get("medium_display"))) if p
                ) or None,
                attribution=(
                    f"{title}{f' by {artist}' if artist else ''} — "
                    "Art Institute of Chicago (CC0)"
                ) if public_domain else None,
                # Open-access work is what people can actually use, so it leads.
                rank=(50 if public_domain else 0) + max(0.0, PAGE_SIZE - position) / 10,
            )
            if record:
                out.append(record)
                got += 1

        log(f"  [artic] page {page}: {got}")

    return out
