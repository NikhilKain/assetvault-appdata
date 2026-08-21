"""The Metropolitan Museum of Art.

The Met's API costs one request per object, which is exactly the shape of source the
CDN exists for: on the device it made the grid wait, here it happens once a night in
a thread pool and arrives as rows in a file. Object ids come from the department
listings and a handful of seed searches; the per-object fetch is what carries
`isPublicDomain` and tells us whether there is a usable image at all.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from ..common import LK_CC0_PER_ASSET, LK_RESERVED, Http, asset, clean, http_url, log

BASE = "https://collectionapi.metmuseum.org/public/collection/v1"
PROVIDER = "metmuseum"  # must match ProviderIds.MET_MUSEUM — asset ids embed it

WORKERS = 8
PER_SEED = 120

SEEDS = [
    "masterpiece", "landscape painting", "portrait", "japanese print",
    "textile pattern", "ceramic", "drawing", "photograph", "sculpture",
    "islamic art", "egyptian", "impressionism", "still life", "armor",
    "botanical", "bird", "flower", "map", "calligraphy", "tapestry",
    "mosaic", "stained glass", "engraving", "watercolor", "gold",
    "greek vase", "roman", "medieval", "renaissance", "art nouveau",
]

# The Met's search is keyword-driven and its keywords are uneven: thirty seeds returned
# forty to ninety ids each and almost all of them the *same* ids — twenty-four of the
# thirty added nothing at all, and the whole seed pass yielded 175 unique objects.
#
# So departments are walked through `/objects?departmentIds=N` instead, which lists every
# object in a wing rather than guessing at keywords. Note this is the listing endpoint,
# not search: `/search?q=*&departmentId=N` looks like it should do the same thing and
# returns zero ids for nineteen of the twenty-one departments, because `*` is matched
# literally.
DEPARTMENTS = list(range(1, 22))

# Sampled evenly across each department rather than taken from the front — object ids
# run in accession order, so the first N of a wing are all from the same era and often
# the same donation.
PER_DEPARTMENT = 130


def _classify(classification: str | None, object_name: str | None) -> str:
    text = f"{classification or ''} {object_name or ''}".lower()
    if "photograph" in text:
        return "PHOTO"
    if "textile" in text or "wallpaper" in text:
        return "PATTERN"
    return "ILLUSTRATION"


def _fetch_object(http: Http, object_id: int, rank: float) -> dict | None:
    try:
        item = http.get_json(f"{BASE}/objects/{object_id}", tries=2)
    except Exception:  # noqa: BLE001 — one missing object is not worth a log line
        return None
    if not isinstance(item, dict):
        return None

    title = clean(item.get("title"))
    primary = http_url(item.get("primaryImage"))
    small = http_url(item.get("primaryImageSmall"))
    if not title or not (primary or small):
        return None

    public_domain = bool(item.get("isPublicDomain"))
    artist = clean(item.get("artistDisplayName"))

    tags = [t.get("term") for t in (item.get("tags") or []) if isinstance(t, dict)]
    tags += [item.get("classification"), item.get("culture"), item.get("medium")]

    return asset(
        provider=PROVIDER,
        provider_asset_id=str(object_id),
        title=title,
        type=_classify(item.get("classification"), item.get("objectName")),
        thumbnail=small or primary,
        preview=primary or small,
        source_url=item.get("objectURL")
        or f"https://www.metmuseum.org/art/collection/search/{object_id}",
        direct_file=primary if public_domain else None,
        file_format="JPG",
        author=artist,
        author_url=item.get("artistWikidata_URL"),
        lk=LK_CC0_PER_ASSET if public_domain else LK_RESERVED,
        tags=[t for t in tags if t],
        description=" · ".join(
            p for p in (
                clean(item.get("objectDate")),
                clean(item.get("medium")),
                clean(item.get("department")),
            ) if p
        ) or None,
        attribution=(
            f"{title}{f' by {artist}' if artist else ''} — "
            "The Metropolitan Museum of Art (CC0)"
        ) if public_domain else None,
        rank=(50 if public_domain else 0) + rank,
    )


def _collect(http: Http, label: str, params: dict, wanted: list[int], seen: set[int]) -> None:
    try:
        data = http.get_json(f"{BASE}/search", params)
    except Exception as e:  # noqa: BLE001
        log(f"  [met] {label}: {e}")
        return

    ids = [i for i in (data.get("objectIDs") or []) if isinstance(i, int)][:PER_SEED]
    added = 0
    for object_id in ids:
        if object_id not in seen:
            seen.add(object_id)
            wanted.append(object_id)
            added += 1
    log(f"  [met] {label}: {len(ids)} ids, {added} new")


def fetch(http: Http) -> list[dict]:
    wanted: list[int] = []
    seen: set[int] = set()

    for seed in SEEDS:
        _collect(
            http,
            f"search '{seed}'",
            {"q": seed, "hasImages": "true", "isPublicDomain": "true"},
            wanted,
            seen,
        )

    for department in DEPARTMENTS:
        try:
            data = http.get_json(f"{BASE}/objects", {"departmentIds": department})
        except Exception as e:  # noqa: BLE001
            log(f"  [met] department {department}: {e}")
            continue

        ids = [i for i in (data.get("objectIDs") or []) if isinstance(i, int)]
        if not ids:
            log(f"  [met] department {department}: empty")
            continue

        step = max(1, len(ids) // PER_DEPARTMENT)
        sampled = ids[::step][:PER_DEPARTMENT]

        added = 0
        for object_id in sampled:
            if object_id not in seen:
                seen.add(object_id)
                wanted.append(object_id)
                added += 1
        log(f"  [met] department {department}: {len(ids)} objects, sampled {added} new")

    log(f"  [met] fetching {len(wanted)} objects with {WORKERS} workers")

    # Each worker gets its own session: requests.Session is not thread-safe, and the
    # shared politeness delay would otherwise serialise the pool anyway.
    pools = [Http(delay=0.15) for _ in range(WORKERS)]

    def job(indexed):
        position, object_id = indexed
        return _fetch_object(pools[position % WORKERS], object_id, max(0.0, 40 - position / 40))

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(job, enumerate(wanted)))

    return [r for r in results if r]
