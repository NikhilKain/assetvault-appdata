"""Wikimedia Commons, through the MediaWiki Action API.

Commons publishes licences as template-generated strings in `extmetadata`. Rather
than decide here what "PD-USGov-NASA" or "Attribution-Share Alike 3.0" means, the
build forwards the `License`, `LicenseShortName` and `LicenseUrl` fields and lets the
app's registry work through them in the same order its live provider does — machine
code first, then short name, then the prose usage terms. Anything it cannot place
still lands as "Unverified" on the device.
"""

from __future__ import annotations

from ..common import LK_RAW, Http, asset, clean, log, strip_html

API = "https://commons.wikimedia.org/w/api.php"
PROVIDER = "wikimedia"

PAGE_SIZE = 40

SEEDS = [
    ("featured picture", "PHOTO", "bitmap"),
    ("quality image landscape", "PHOTO", "bitmap"),
    ("valued image", "PHOTO", "bitmap"),
    ("panorama", "WALLPAPER", "bitmap"),
    ("aerial photograph", "PHOTO", "bitmap"),
    ("wildlife", "PHOTO", "bitmap"),
    ("architecture photograph", "PHOTO", "bitmap"),
    ("historical photograph", "PHOTO", "bitmap"),
    ("botanical illustration", "ILLUSTRATION", "bitmap"),
    ("vintage poster", "ILLUSTRATION", "bitmap"),
    ("antique map", "ILLUSTRATION", "bitmap"),
    ("scientific diagram", "SVG", "drawing"),
    ("flag svg", "SVG", "drawing"),
    ("coat of arms svg", "SVG", "drawing"),
    ("icon svg", "SVG", "drawing"),
    ("chart svg", "SVG", "drawing"),
    ("seamless texture", "TEXTURE", "bitmap"),
    ("wallpaper pattern", "PATTERN", "bitmap"),
    ("ornament pattern", "PATTERN", "drawing"),
    ("astronomy", "WALLPAPER", "bitmap"),
]


def _meta(extmetadata: dict | None, key: str) -> str | None:
    if not isinstance(extmetadata, dict):
        return None
    entry = extmetadata.get(key)
    if isinstance(entry, dict):
        return clean(entry.get("value"))
    return None


def _classify(mime: str | None, title: str, fallback: str) -> str:
    if mime and "svg" in mime:
        return "SVG"
    lower = title.lower()
    if any(word in lower for word in ("texture", "seamless")):
        return "TEXTURE"
    if "pattern" in lower or "ornament" in lower:
        return "PATTERN"
    if any(word in lower for word in ("diagram", "illustration", "drawing", "map")):
        return "ILLUSTRATION"
    return fallback


def fetch(http: Http) -> list[dict]:
    out: list[dict] = []

    for seed, asset_type, filetype in SEEDS:
        try:
            data = http.get_json(
                API,
                {
                    "action": "query",
                    "format": "json",
                    "formatversion": "2",
                    "generator": "search",
                    "gsrsearch": f"{seed} filetype:{filetype}",
                    "gsrnamespace": "6",
                    "gsrlimit": str(PAGE_SIZE),
                    "prop": "imageinfo",
                    "iiprop": "url|size|mime|extmetadata|user|canonicaltitle",
                    "iiurlwidth": "640",
                    "iiextmetadatafilter": (
                        "License|LicenseShortName|LicenseUrl|UsageTerms|Artist|"
                        "Credit|ImageDescription|ObjectName"
                    ),
                },
            )
        except Exception as e:  # noqa: BLE001
            log(f"  [wikimedia] '{seed}': {e}")
            continue

        pages = ((data.get("query") or {}).get("pages")) or []
        got = 0
        for position, page in enumerate(pages):
            info = (page.get("imageinfo") or [{}])[0]
            description_url = info.get("descriptionurl")
            extmetadata = info.get("extmetadata")

            file_title = (page.get("title") or "").removeprefix("File:")
            # ObjectName is template output and often arrives wrapped in markup —
            # `<div class="fn">…</div>` from the microformat templates especially.
            # Untreated, that markup becomes the card title on the device.
            title = (
                strip_html(_meta(extmetadata, "ObjectName"))
                or clean(file_title.rsplit(".", 1)[0].replace("_", " "))
            )
            if not title:
                continue

            mime = info.get("mime")
            usage_terms = _meta(extmetadata, "UsageTerms")

            record = asset(
                provider=PROVIDER,
                provider_asset_id=str(page.get("pageid") or file_title),
                title=title,
                type=_classify(mime, title, asset_type),
                thumbnail=info.get("thumburl") or info.get("url"),
                preview=info.get("url"),
                source_url=description_url or "",
                direct_file=info.get("url"),
                file_format=(mime or "").rsplit("/", 1)[-1].upper() or None,
                width=info.get("width") if isinstance(info.get("width"), int) else None,
                height=info.get("height") if isinstance(info.get("height"), int) else None,
                size_bytes=info.get("size") if isinstance(info.get("size"), int) else None,
                author=strip_html(_meta(extmetadata, "Artist")) or clean(info.get("user")),
                lk=LK_RAW,
                license_code=_meta(extmetadata, "License"),
                # The short name is the app's second resolution attempt, and the prose
                # usage terms its third. Both travel so neither step is lost.
                license_short_name=_meta(extmetadata, "LicenseShortName"),
                license_terms=usage_terms,
                license_url=_meta(extmetadata, "LicenseUrl"),
                tags=[w for w in title.lower().replace("-", " ").replace(",", " ").split() if len(w) > 2],
                description=(strip_html(_meta(extmetadata, "ImageDescription")) or usage_terms),
                rank=max(0.0, PAGE_SIZE - position),
            )
            if record:
                out.append(record)
                got += 1

        log(f"  [wikimedia] '{seed}': {got}")

    return out
