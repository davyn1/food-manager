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

## 3. Shelf-life data (USDA FoodKeeper)

- `scripts/import_foodkeeper.py` downloads FoodKeeper once, converts durations to days
  (Weeks x7, Months x30, Years x365), maps non-numeric values to null + tip, and writes
  `data/shelf_life.json` (committed). The app seeds the DB from it; no network at runtime.
- `data/aliases_extra.json`: hand-curated common names FoodKeeper lacks.
- `category_defaults` derived from per-category medians.

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

## 7. Phase 1 build order

1. Project skeleton, venv, deps, empty FastAPI app, pytest running
2. `normalize.py` + tests
3. FoodKeeper import script -> `data/shelf_life.json`
4. `shelf_life.py` matching + `expiration.py` + tests
5. DB models, Alembic migration, seeding
6. Pantry service: add, move, open, override date, use / partial use / discard
7. UI: home (expiring soon), quick add, list sorted by expiry, expired list
8. PWA manifest, icons, service worker; install test on phone
