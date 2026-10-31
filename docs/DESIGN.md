# Food Manager — Design (approved 2026-10-27)

Personal pantry tracker + recipe recommender. Mobile-first PWA, Python backend.
Built in phases; a later phase starts only when the current one works and is tested.

## 1. Architecture

FastAPI + SQLite (SQLAlchemy 2.0, Alembic) + server-rendered Jinja templates with HTMX.

```
app/
  core/            # PURE logic, no DB/web imports, fully unit-tested
    schemas.py     # Pydantic: ItemDraft, ItemCreate, Item, Recipe, RecipeMatch...
    normalize.py   # name normalization (shared by shelf-life + recipes)
    shelf_life.py  # name -> shelf-life entry (alias -> keyword -> fuzzy -> category fallback)
    expiration.py  # estimate(entry, location, state, dates) -> date
    ranking.py     # recipe scoring/ranking, auto-mode ingredient picking
  inputs/          # item input sources (Phase 3 seam): InputSource -> list[ItemDraft]
  recipes/         # RecipeSource protocol + implementations (TheMealDB first)
  db/              # SQLAlchemy models, session, repositories
  services/        # glue between core and db
  web/             # FastAPI routers, templates/, static/ (htmx, css, icons, manifest, sw.js)
data/shelf_life.json        # generated from FoodKeeper, committed
scripts/import_foodkeeper.py
tests/
migrations/                 # Alembic
```

Dependencies: fastapi, uvicorn[standard], sqlalchemy, alembic, pydantic, jinja2,
python-multipart, rapidfuzz, httpx; dev: pytest. HTMX is vendored as a static file (no npm).

## 2. Database schema (SQLite)

**items**: id, name, normalized_name, shelf_life_id (FK, nullable), category, quantity,
unit, location (pantry/fridge/freezer), state (unopened/opened), added_on, opened_on,
location_since, estimated_expires_on, user_expires_on, expires_on (effective, indexed),
expiration_source (user/estimated), status (active/used/discarded), finished_on,
input_source, notes.

- `estimated_expires_on` is always recalculated on move/open.
- `user_expires_on` is never touched by automation.
- `expires_on` = user date if set, else estimate.

**item_events**: id, item_id, type (added/opened/moved/partially_used/used/discarded/
date_overridden), quantity_delta, from_location, to_location, occurred_at.

**shelf_life_products**: FoodKeeper id, category, name, subtitle, keywords, durations in
days (min/max) for pantry, pantry_opened, fridge, fridge_opened, fridge_after_thaw,
freezer; tips; raw JSON.

**shelf_life_aliases**: alias (normalized) -> product_id, origin (foodkeeper/curated/learned).

**category_defaults**: (category, location, state) -> days.

**staples**: name (seeded: salt, pepper, oil, water, sugar, flour).

**settings**: key/value (e.g. `expiring_soon_days = 3`).

**recipes / recipe_ingredients**: local cache of fetched recipes (Phase 2).

Implementation notes (step 5):
- Models in `app/db/models.py`; initial Alembic migration in `migrations/versions/`.
- `items.thawed` (bool) added: selects FoodKeeper's "after thawing" figure.
- `shelf_life_products` stores `keywords`, `storage` and `tips` as JSON shaped like the
  Pydantic `ShelfLifeProduct`, instead of 18 duration columns. They're never queried by
  column, only loaded into the matcher.
- Enums are stored as strings (no DB enum types), so new categories need no migration.
- SQLite foreign keys are enforced (`PRAGMA foreign_keys=ON` on every connection).
- `python -m app.db.seed` is idempotent: it upserts products and defaults, replaces
  curated aliases (learned aliases win), and only inserts missing staples and settings.

## 3. Shelf-life data (USDA FoodKeeper)

- `scripts/import_foodkeeper.py` downloads FoodKeeper once, converts durations to days
  (Weeks x7, Months x30, Years x365), maps non-numeric values to null + tip, and writes
  `data/shelf_life.json` (committed). The app seeds the DB from it; no network at runtime.
- `data/aliases_extra.json`: hand-curated common names FoodKeeper lacks.
- `category_defaults` derived from per-category medians.

Import notes (step 3):
- fsis.usda.gov blocks scripted downloads (Akamai 403), so the file was taken from the
  Wayback Machine snapshot of the official URL (2025-07-02). Data version 128,
  modified 2018-09-06. URL and SHA-256 are recorded in `data/shelf_life.json`.
- Conversion logic is in `app/core/foodkeeper.py` (pure, tested); the script only does I/O.
- "DOP_" (from date of purchase) values are preferred; plain values are the fallback.
- Non-numeric values become notes: `indefinite`, `package_date`, `when_ripe`,
  `not_recommended`. Hours round down to 0 days.
- Categories added beyond the original list: `shelf_stable`, `deli`, `plant_protein`.
  FoodKeeper's "Baking and Cooking" (flour, oils, spices) maps to `shelf_stable`.
- Perishable categories (dairy, meat, poultry, seafood, deli, frozen) get 0 pantry days
  by default, since their only pantry data comes from canned/dried variants.
- Leftovers use USDA guidance: fridge 3 days, freezer 90 days, pantry 0.

Matching and estimation notes (step 4):
- `app/core/shelf_life.py`: the last word of a name (head noun) weighs double, so
  "apple pie" is a pie. A product must cover at least half the weighted tokens. Ties go to
  the category hint, then the product whose name best matches, then the most generic one.
  Typos are corrected against the dataset vocabulary (rapidfuzz ratio >= 85, words of 4+
  letters). If nothing covers every word, an alias for the head noun wins
  ("skim milk" -> milk).
- `data/aliases_extra.json`: about 20 curated aliases for ambiguous common names
  (milk, rice, ham, lemons, onions...).
- `app/core/expiration.py`: the storage clock restarts only on freezer moves. Opening
  doesn't shorten an item whose product has no separate opened figure (e.g. butter).
  "Indefinitely" becomes 10 years so it still sorts. Notes become UI flags
  (`use_package_date`, `when_ripe`, `not_recommended`, `indefinite`).

Matching: lowercase, strip punctuation, singularize, drop descriptor words
(boneless, skinless, fresh, organic, ...), then exact alias -> token-set match ->
rapidfuzz fuzzy match (threshold) -> category fallback. User corrections are saved as
learned aliases.

Estimation:
- Unopened: `location_since + duration[location]`
- Opened: `min(unopened estimate, opened_on + duration[location_opened])`
- Freezer -> fridge uses "after thawing" when available
- Missing value: category default
- **Decision:** use the minimum of FoodKeeper's range (conservative).
- **Decision:** opening an item with a user date keeps the user date; show a warning if
  the opened estimate is sooner.

Pantry service notes (step 6):
- `app/services/pantry.py`: `PantryService` adds items (with a no-save `preview` for the
  add form), moves, opens, sets or clears the user date, corrects the matched product,
  records partial use, marks used or discarded, and lists all / expiring soon / expired.
- Every change goes through one recalculation, so the "user date always wins" rule lives
  in one place. Methods flush; the caller (API layer) commits.
- When no location is given, it's suggested: frozen -> freezer; leftovers and unknown
  food -> fridge; else pantry if the product can be kept there, otherwise the fridge.
- Choosing a product other than the automatic match saves a learned alias.
- Using up the whole quantity marks the item used. Finished items can't be changed.
- `items.estimate_flags` (JSON, migration 2) stores the latest estimate's UI flags.
- Phase 3 seam: `ItemDraft` (any input source) -> `ItemCreate.from_draft` after the user
  confirms -> `add_items`. `app/inputs/base.py` defines the `InputSource` protocol.

UI notes (step 7):
- `app/web/pages.py`: server-rendered pages; forms post and redirect (303). `hx-boost`
  turns that into in-place page swaps. The only partial is the add form's live preview
  (`GET /add/preview`, 300 ms after typing stops).
- Pages: Home (quick add + expired + expiring soon), All items (filter by location,
  sort by date or A-Z), Expired (one-tap Toss), item page (used / threw out / used some
  / open / move / printed date / change match), change-match search, Settings.
- After adding, the name field is focused again so several items can be entered in a row.
- Post-action notices use fixed text keyed by `?done=...&item=<id>`; nothing from the URL
  is echoed. Redirect targets (`next`) must be local paths.
- Form errors return 422 and re-render in place (htmx is configured to swap 422).
- The app is built by `create_app()` (`uvicorn --factory`), which migrates and seeds on
  startup. HTMX 2.0.4 is vendored at `app/web/static/vendor/htmx.min.js`
  (SRI sha384-HGfztofotfshcF7+8n44JQL2oJmowVChPTg48S+jvZoztPfvwD79OC/LTtG6dMp+).
- Light/dark follows the phone setting. Tap targets are at least 48 px; the bottom tab bar
  is reachable one-handed. Checked at 375 px wide: no horizontal scrolling.

Accounts and hosting (decided 2026-10-30):
- Hosted on Fly.io (owner already uses it), not Tailscale, so a friend can use it too.
  One `shared-cpu-1x` 256 MB machine that stops when idle, SQLite on a 1 GB volume at
  `/data`, HTTPS at `<app>.fly.dev`. Measured locally: ~1.9 s startup on a fresh DB,
  ~124 MB peak memory including a login.
- Accounts: `users` table; passwords hashed with stdlib scrypt (`app/core/passwords.py`);
  no sign-up page, accounts made with `python -m app.manage add-user`. Failed logins
  lock a username for 15 minutes after 10 attempts (in memory, `app/core/throttle.py`).
- Sessions: Starlette `SessionMiddleware` (signed cookie via `itsdangerous`), HttpOnly,
  SameSite=Lax (blocks cross-site form posts), Secure in production, ~6 months.
  Key from the `FOOD_MANAGER_SECRET_KEY` Fly secret; locally a gitignored
  `data/.secret_key`.
- Separate pantries: `items.owner_id`; `PantryService` is constructed for one user and
  every query is scoped to them; another user's item id is a 404. The expiring-soon
  window is per user. Learned shelf-life aliases are shared.
- Public without login: `/login`, `/health`, manifest, `/sw.js`, `/offline`, `/static`,
  so the app installs and works offline before signing in.

Invites and passwords (decided 2026-10-31, planning for 4-5 friends):
- One-time invite links instead of a shared code: admins (`users.is_admin`) create them
  in Settings > Invite friends. A link works once and expires after 7 days; only its
  SHA-256 is stored, so it's shown once. Used/expired/cancelled links explain themselves.
- Change password in Settings (current + new twice). `users.session_version` is copied
  into the login cookie; a password change or admin reset bumps it, signing out other
  devices while keeping the current one signed in.
- Referrer policy `same-origin` so sign-up tokens never leave the site in headers.
- Limits to revisit as the group grows: docs/SCALING.md.

Visual design: "day dots" (2026-10-31):
- Concept: kitchens label food with colored dot stickers and a marker. Each item gets a
  round dot (`partials/dot.html`): color is urgency, the marker number is time left.
  The dot is the only loud element; the rest stays quiet.
- Dot levels (`dot_level`): expired (red), now = today/tomorrow (orange), soon = within
  the user's window (yellow), ok (green), later = 60+ days (slate). Text (`dot_parts`):
  a marker number plus a small lowercase unit ("3" / "days", "4" / "mo"), because the
  marker face is capitals-only and "3D" read like 3-D. Full text stays in the page for
  screen readers.
- Colors: fridge-enamel page `#edf1f2`, white shelves, marker-navy ink `#1c2430`,
  painter's-tape blue `#2f6db5` for actions and the active tab. Dark mode is the same
  roles at night (`#10151b` page, `#6fa5ea` tape).
- Type: Atkinson Hyperlegible (Braille Institute's legibility face, fitting an app for a
  forgetful user) for everything; Permanent Marker only inside dots. Both load from
  Google Fonts (system-font fallback offline). Self-hosting them would remove the Google
  request; see docs/SCALING.md.
- Lists are one white shelf with thin dividers (not a card per item). Location is an
  icon plus word; the tab bar has icons. Confirmation notices fade after 4 seconds.
  No middle-dot separators or all-caps labels.

## 4. Recipes

**Decision:** TheMealDB first; fetch the whole catalog once (by first letter a–z) into
the local `recipes` table and rank locally. Other sources (local Food.com subset,
Spoonacular) can be added behind the `RecipeSource` interface later.

Ranking (pure): 1) more selected/expiring ingredients used, 2) fewer missing,
3) ties to sooner-expiring, 4) more other pantry items used. Staples count as owned.
Auto mode picks the N soonest-expiring items (default 5), excluding expired and staples.

## 5. Phase 3 seam

Every input source returns `list[ItemDraft]`; all drafts go through one review/confirm
screen before `pantry_service.add_items()`. Manual entry is one such source.

## 6. PWA

Manifest (standalone, theme color, 192/512 + maskable icons), service worker (app shell
cache + offline page), HTTPS in production, `apple-touch-icon` + apple meta tags.
iOS: manual install via Share -> Add to Home Screen; Web Push only on 16.4+ for installed
PWAs and needs a server-side scheduler. **Decision:** no notifications in Phase 1.
Camera (Phase 3): prefer `<input type="file" accept="image/*" capture="environment">`.

Implementation notes (step 8):
- `GET /manifest.webmanifest` (`app/web/pwa.py`): standalone, start_url `/`, theme
  `#2f6f4e`, icons 192/512 (`any`) and 512 (`maskable`), shortcuts to Expired and All items.
- Icons are drawn by `scripts/make_icons.py` (pure Python, no image library): a jar on
  green. The apple-touch-icon (180) and maskable icon fill the square; iOS rounds corners
  itself and shows transparency as black.
- `GET /sw.js` is served from the root (scope `/`), `Cache-Control: no-cache`, with the
  static version injected. Static assets are cache-first under `pantry-<version>`; the
  version is a hash of app.css, app.js and htmx, and asset URLs carry `?v=<version>`, so a
  deploy reaches phones on the next visit and old caches are deleted on activate.
- Pages are never cached (pantry data must be current). With no network, full page loads
  and hx-boost page swaps get the cached `/offline` page instead of failing silently.
- Install hints (`app/web/static/app.js`): Android/desktop Chrome shows an Install
  button (from `beforeinstallprompt`); iOS Safari shows "Share -> Add to Home Screen";
  nothing shows once installed. The home banner can be dismissed (remembered in
  localStorage); Settings always has an "Install app" section.
- `HEAD /` and `HEAD /health` return 200 for hosting health checks.

iOS limitations that affect this app:
- No install prompt: installing is manual (Share -> Add to Home Screen), so the app shows
  a hint. On iOS 17+ other browsers can also add to the home screen; older iOS needs Safari.
- Push notifications for expiring items need iOS 16.4+, an installed (home-screen) app,
  permission requested from a tap, a VAPID key pair, and a server-side scheduler to send
  them. There is no background sync / periodic sync on iOS, so the app can't wake itself
  to check dates. Phase 1 has no notifications (decision 6).
- iOS keeps separate storage for the home-screen app and for Safari. That doesn't matter
  here (data is on the server), except that a dismissed install hint in Safari stays
  dismissed only in Safari.
- Camera in an installed app (Phase 3): `getUserMedia` has historically been unreliable in
  standalone mode, so the plan is a file input with `capture="environment"`.
- HTTPS is required to install and for the service worker on a phone (localhost is
  exempt only on the computer itself).

## 7. Phase 1 build order

1. Project skeleton, venv, deps, empty FastAPI app, pytest running
2. `normalize.py` + tests
3. FoodKeeper import script -> `data/shelf_life.json`
4. `shelf_life.py` matching + `expiration.py` + tests
5. DB models, Alembic migration, seeding
6. Pantry service: add, move, open, override date, use / partial use / discard
7. UI: home (expiring soon), quick add, list sorted by expiry, expired list
8. PWA manifest, icons, service worker; install test on phone
