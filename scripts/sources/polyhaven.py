"""Poly Haven — the whole library, in three requests.

`/assets?t=…` returns every asset of a type in one response, so this source is
indexed exhaustively rather than sampled. It is also the one place where a
provider-wide licence claim is trustworthy: Poly Haven states plainly that the entire
library is CC0, so the record carries `lk = cc0_provider` and the app builds the same
`DECLARED_BY_PROVIDER` licence its live provider does — a provider-level guarantee,
recorded as such, never upgraded to a per-asset one.
"""

from __future__ import annotations

from ..common import LK_CC0_PROVIDER, Http, asset, log

BASE = "https://api.polyhaven.com"
CDN = "https://cdn.polyhaven.com"
PROVIDER = "polyhaven"

# Poly Haven's own numeric type ids.
TYPE_HDRI = 0
TYPE_TEXTURE = 1
TYPE_MODEL = 2

KINDS = {
    "hdris": ("TEXTURE", "HDR", "HDRI environment map"),
    "textures": ("TEXTURE", "PNG", "Seamless PBR texture set"),
    "models": ("MODEL_3D", "BLEND", "3D model with PBR textures"),
}


def fetch(http: Http) -> list[dict]:
    out: list[dict] = []

    for kind, (asset_type, file_format, blurb) in KINDS.items():
        try:
            catalogue = http.get_json(f"{BASE}/assets", {"t": kind}) or {}
        except Exception as e:  # noqa: BLE001
            log(f"  [polyhaven] {kind}: {e}")
            continue

        for slug, entry in catalogue.items():
            if not isinstance(entry, dict):
                continue

            authors = list((entry.get("authors") or {}).keys())
            max_res = entry.get("max_resolution") or []
            width = max_res[0] if len(max_res) >= 2 and isinstance(max_res[0], int) else None
            height = max_res[1] if len(max_res) >= 2 and isinstance(max_res[1], int) else None
            downloads = entry.get("download_count") or 0

            record = asset(
                provider=PROVIDER,
                provider_asset_id=slug,
                title=entry.get("name") or slug.replace("_", " "),
                type=asset_type,
                thumbnail=f"{CDN}/asset_img/thumbs/{slug}.png?width=480&height=270",
                preview=f"{CDN}/asset_img/primary/{slug}.png?width=1200",
                source_url=f"https://polyhaven.com/a/{slug}",
                # Files are published per resolution and format. The app links to the
                # asset page and lets the user choose rather than guessing a URL.
                direct_file=None,
                file_format=file_format,
                width=width,
                height=height,
                author=authors[0] if authors else None,
                lk=LK_CC0_PROVIDER,
                tags=[*(entry.get("tags") or []), *(entry.get("categories") or [])],
                description=blurb + (f" by {', '.join(authors)}" if authors else ""),
                # CC0 — there is nothing to require, so nothing is claimed.
                attribution=None,
                rank=downloads / 1000,
            )
            if record:
                out.append(record)

        log(f"  [polyhaven] {kind}: {len(catalogue)}")

    return out
