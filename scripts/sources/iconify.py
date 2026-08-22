"""Iconify — the icon half of the catalogue.

Icons are what this app gets asked for most, and they are also the cheapest thing to
index: one request per set returns every icon name in it, and the record is a name and
a URL. So the CDN carries a deep slice of the popular sets rather than a sample, and a
search for "chevron" answers from disk.

Licences are declared per *set*, and Iconify returns the SPDX id in the set info. It
travels as `lc`/`lu` and AssetVault resolves it — a set whose SPDX we don't recognise
becomes "Unverified" on the device, exactly as it would from the live API.
"""

from __future__ import annotations

from ..common import LK_RAW, Http, asset, log

BASE = "https://api.iconify.design"
PROVIDER = "iconify"

# The first eighteen are the sets the live provider features, in its order, so the CDN
# home feed and a cold live feed open on the same icons. The rest are here purely for
# depth — testers said the library felt small, and icons are the cheapest thing in the
# catalogue to have more of: a record is a name and a URL, and nothing is fetched per
# icon.
SETS = [
    "lucide", "ph", "solar", "tabler", "mdi", "material-symbols",
    "simple-icons", "logos", "hugeicons", "iconoir", "fluent", "carbon",
    "ri", "bi", "heroicons", "majesticons", "gravity-ui", "streamline",
    "mingcute", "akar-icons", "octicon", "line-md", "pixelarticons", "teenyicons",
    "basil", "uil", "gg", "bx", "clarity", "mynaui",
]

ICONS_PER_SET = 420


def _title(name: str) -> str:
    words = [w for w in name.replace("_", "-").split("-") if w]
    return " ".join(w[:1].upper() + w[1:] for w in words)


def fetch(http: Http) -> list[dict]:
    collections = http.get_json(f"{BASE}/collections") or {}
    out: list[dict] = []

    for rank, prefix in enumerate(SETS):
        meta = collections.get(prefix)
        if not isinstance(meta, dict):
            log(f"  [iconify] {prefix}: not in /collections, skipping")
            continue

        try:
            detail = http.get_json(f"{BASE}/collection", {"prefix": prefix}) or {}
        except Exception as e:  # noqa: BLE001
            log(f"  [iconify] {prefix}: {e}")
            continue

        # Sets expose their icons either flat or grouped into categories; take both.
        names: list[str] = list(detail.get("uncategorized") or [])
        for group in (detail.get("categories") or {}).values():
            names.extend(group or [])
        if not names:
            names = list((detail.get("icons") or {}).keys())
        names = names[:ICONS_PER_SET]

        info = detail.get("info") or meta
        license_info = info.get("license") or {}
        author = info.get("author") or {}
        set_name = info.get("name") or prefix

        # Multicolour sets (brand logos, flags) must not be recoloured. Monochrome sets
        # get the light tint the app's dark icon artboard expects.
        palette = bool(info.get("palette"))
        tint = "" if palette else "?color=%23E8E4FF"

        for position, name in enumerate(names):
            record = asset(
                provider=PROVIDER,
                provider_asset_id=f"{prefix}:{name}",
                title=_title(name),
                type="ICON",
                thumbnail=f"{BASE}/{prefix}/{name}.svg{tint}",
                preview=f"{BASE}/{prefix}/{name}.svg{tint}",
                source_url=f"https://icon-sets.iconify.design/{prefix}/{name}/",
                direct_file=f"{BASE}/{prefix}/{name}.svg",
                file_format="SVG",
                author=author.get("name"),
                author_url=author.get("url"),
                lk=LK_RAW,
                license_code=license_info.get("spdx") or license_info.get("title"),
                license_url=license_info.get("url"),
                tags=[*name.replace("_", "-").split("-"), prefix, "icon", "svg"],
                description=f"From the {set_name} icon set",
                # Earlier sets and earlier icons in a set rank higher: Iconify orders
                # each set by how its authors present it, which beats alphabetical.
                rank=(len(SETS) - rank) * 2 + max(0, 60 - position) / 60,
            )
            if record:
                out.append(record)

        log(f"  [iconify] {prefix}: {len(names)}")

    return out
