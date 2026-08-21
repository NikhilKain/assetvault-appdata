# assetvault-appdata

The prebuilt catalogue behind [AssetVault](https://github.com/NikhilKain/AssetVault).

A nightly GitHub Action queries every open source the app supports, normalises the
results, and publishes them as static JSON on GitHub Pages. The app reads that first
and the live APIs second.

**CDN base:** `https://nikhilkain.github.io/assetvault-appdata`

---

## Why this exists

AssetVault's home screen used to issue five parallel browse requests, each of which
fanned out to seven provider APIs with a twelve-second timeout. Thirty-five calls,
and the grid could not paint until the slowest of them answered — over a phone
connection that is several seconds of empty screen, every launch, for a feed whose
contents barely change hour to hour.

None of that work needed to happen on the device. It happens here instead, once a
night, and the phone does one conditional GET against a static host.

---

## What it serves

| File | Holds | Rough size |
| --- | --- | --- |
| `data/meta.json` | Counts and a build timestamp | 1 KB |
| `data/home.json` | The home feed — hero and rails, as whole records | 150 KB |
| `data/type/<TYPE>.json` | One file per browsable category | 60–200 KB |
| `data/index.json` | The whole catalogue, for offline search | 3–5 MB |

`home.json` is what the app fetches on launch, and it is small enough to arrive and
parse before the first frame settles. `index.json` warms in the background afterwards
and is what makes search answer from disk.

---

## The licence rule

This repo does not decide what a licence means.

Every record carries the raw signals its source gave us — the licence code, its
version, the deed URL, and where a source states it in prose, the short name and
usage terms — tagged with a `lk` ("licence kind") that names which of the app's
*existing* resolution paths to run:

| `lk` | Means |
| --- | --- |
| `raw` | Resolve `lc` / `lv` / `lu` / `ln` / `lt` through `LicenseRegistry` |
| `cc0_asset` | The source flagged this individual item as open-access CC0 |
| `cc0_provider` | The whole catalogue is CC0 (Poly Haven) — a provider-level claim, recorded as one |
| `nasa` | NASA media guidelines — permissive with conditions, *not* a public-domain dedication |
| `reserved` | The source says rights are reserved; the app shows it as unverified |

Resolution then happens on the device, in the same `LicenseRegistry` the live
providers use. A catalogue row and a live row for the same asset produce the same
badge, and an unrecognised licence string still lands as **Unverified** rather than
as something permissive. Porting that logic into Python would have forked the one
rule the app is built on, so it stays in one place.

Images are **not** mirrored. Thumbnails load from each source's own host, as they
always did — this repo carries metadata only.

---

## Sources

| Source | What it contributes | How it's indexed |
| --- | --- | --- |
| Iconify | Icons and SVGs from the 18 most-used open sets | ~260 icons per set, in the sets' own order |
| Openverse | Photos, illustrations, wallpapers, textures, audio | 45 seed queries, two pages each |
| Poly Haven | HDRIs, PBR textures, 3D models | The entire library — three requests |
| Wikimedia Commons | Photos, SVGs, historical work | 20 seed queries via the MediaWiki API |
| Art Institute of Chicago | Open-access artwork | 12 pages of the collection |
| The Met | Open-access artwork | 14 seed searches, objects fetched in a pool |
| NASA | Space and mission imagery | 17 seed queries |
| Google Fonts | ~1,800 open typefaces | One call, needs a key — see below |

Every one is a documented public API used within its published limits, with a
descriptive `User-Agent` and a contact URL, matching the rule the app itself keeps:
nothing here scrapes rendered HTML, bypasses a paywall or login, ignores robots
directives, or works around rate limiting.

### The one key

Google Fonts is the exception, and it earns it: it is the *only* font source AssetVault
has, it needs the user's own key, and it is off by default — so before this, a fresh
install tapping "Fonts" got nothing at all. Indexing it here means one key serves every
install, and it never leaves the Action.

Add a [Google Fonts Developer API key](https://developers.google.com/fonts/docs/developer_api)
as a repository secret named `GOOGLE_FONTS_KEY`. Without it the source skips itself and
the build still succeeds — everything else is keyless by design.

The remaining keyed sources — Pexels, Pixabay, Unsplash, Freesound — stay live-only and
per-user in Settings › Sources. Each of those has a keyless alternative already in the
catalogue; fonts did not.

---

## Running it

```bash
pip install -r requirements.txt
python -m scripts.build_catalog              # everything
python -m scripts.build_catalog polyhaven    # one source, for a quick check
```

Output lands in `data/`, which is gitignored on `main` — it is published to the
`gh-pages` branch by the workflow, which force-pushes a freshly built tree each run.

To rebuild on demand: **Actions → Build catalogue → Run workflow**.

### Two guards on publishing

Because the deploy force-pushes a fresh tree, a bad build doesn't degrade the catalogue,
it *replaces* it. Both of these exist because both nearly happened:

- **A filtered run is never published.** The `sources` input is for checking one fetcher;
  publishing a one-source build would erase the other six.
- **A run that loses most of a source fails instead of shipping.** Counts are compared
  against the live `meta.json`, and a provider dropping below 40% of what it had aborts
  the build. Two Met runs back to back tripped the museum's rate limiting, every object
  fetch quietly returned nothing, and a run carrying 73 objects instead of 1,295
  published straight over a working file. Pass **allow_collapse** when a drop is
  deliberate.

---

## Adding a source

1. Write `scripts/sources/<name>.py` exposing `fetch(http) -> list[dict]`, building
   each row with `common.asset(...)`.
2. Pick the `lk` tag that matches what the source actually tells you. If it tells you
   nothing, pass `lk=LK_RAW` with no code — the app will say so.
3. Register it in `SOURCES` in `scripts/build_catalog.py`.
4. Make sure `provider=` matches the id in the app's `ProviderIds`. Asset ids embed
   it, and the app resolves detail lookups through it.
