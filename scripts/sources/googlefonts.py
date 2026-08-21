"""Google Fonts.

The only source here that needs a key, and the reason it earns one: fonts are the app's
emptiest category. Google Fonts is the sole font provider AssetVault has, it is off by
default because it requires the *user's* own key, and the result is that a fresh install
tapping "Fonts" gets nothing at all. Indexing it here once a night with one repo secret
gives every install ~1,800 families with no setup — the key does the nightly fetch, and
never leaves the Action.

Skipped cleanly when `GOOGLE_FONTS_KEY` is unset, so the build still works for anyone
who clones this repo without one.

Licence: every family is open source, but the API does not say *which* of OFL 1.1,
Apache 2.0 or UFL a given family carries. The record says so (`lk = google_fonts`) and
the app rebuilds the same provider-level licence its live provider uses, rather than
picking one of the three and being wrong for the rest.
"""

from __future__ import annotations

import os

from ..common import LK_GOOGLE_FONTS, Http, asset, clean, log

BASE = "https://www.googleapis.com/webfonts/v1/webfonts"
PROVIDER = "googlefonts"  # must match ProviderIds.GOOGLE_FONTS


def fetch(http: Http) -> list[dict]:
    key = os.environ.get("GOOGLE_FONTS_KEY", "").strip()
    if not key:
        log("  [googlefonts] GOOGLE_FONTS_KEY not set — skipping")
        return []

    # One call returns the entire catalogue, already ordered by popularity, which is the
    # order the app wants anyway.
    data = http.get_json(BASE, {"key": key, "sort": "popularity"})
    items = data.get("items") or []

    out: list[dict] = []
    for position, item in enumerate(items):
        family = clean(item.get("family"))
        if not family:
            continue

        category = clean(item.get("category"))
        variants = item.get("variants") or []
        subsets = item.get("subsets") or []
        files = item.get("files") or {}

        description = category.capitalize() if category else ""
        description += f" · {len(variants)} style{'' if len(variants) == 1 else 's'}"
        if subsets:
            description += f" · {len(subsets)} script{'' if len(subsets) == 1 else 's'}"

        record = asset(
            provider=PROVIDER,
            provider_asset_id=family,
            title=family,
            type="FONT",
            # No thumbnail on purpose: the app renders the family name as a specimen
            # card, which shows the typeface far better than a picture of it would.
            source_url=f"https://fonts.google.com/specimen/{family.replace(' ', '+')}",
            direct_file=files.get("regular") or next(iter(files.values()), None),
            file_format="TTF",
            lk=LK_GOOGLE_FONTS,
            tags=[
                category,
                *subsets[:6],
                "font",
                "typeface",
                *(["italic"] if any("italic" in v for v in variants) else []),
                *(["variable"] if len(variants) > 4 else []),
            ],
            description=description.strip(" ·"),
            rank=max(0.0, len(items) - position) / 100,
        )
        if record:
            out.append(record)

    log(f"  [googlefonts] {len(out)} families")
    return out
