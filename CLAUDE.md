# Food Manager: project guide

Personal pantry tracker + recipe recommender. Mobile-first PWA, Python backend.
Tracks food at home, estimates expiration dates from USDA FoodKeeper data, and (Phase 2)
recommends recipes that use up what's expiring.

- **How to set up and run:** [README.md](README.md)
- **Architecture, schema, data and all design decisions:** [docs/DESIGN.md](docs/DESIGN.md)
- **What to do next:** the "Next steps" section at the bottom of this file

## Status (as of 2026-10-28)

Phase 1 (pantry tracker) is built and tested: steps 1-8 in docs/DESIGN.md section 7 are
done, 226 tests pass, everything is pushed to `main` on
https://github.com/davyn1/food-manager.

Not done yet: installing on a real phone. That needs HTTPS. The chosen route is Tailscale
(private to the owner's devices). Step-by-step instructions are in README.md, "Private
HTTPS with Tailscale". Tailscale was not installed on the dev PC yet.

## How to work on this project

- **Phases:** build in phases. Don't start a later phase until the current one works and
  is tested. Phase 3 (camera/receipt input) is design-only; don't build it yet.
- **Small steps:** build one small working piece at a time, with pytest tests.
- **Commit and push after each finished part,** to `main` on origin. End commit messages
  with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Ask first** before adding paid APIs or new major dependencies.
- **Exact commands:** give the owner exact copy-paste commands (Windows PowerShell).
- **Propose before building:** for each new phase, propose the plan and wait for approval.

## Code map

```
app/
  core/          Pure logic. Must NOT import app.db, app.web, or do I/O.
    normalize.py   food-name normalization (plurals, descriptors, accents)
    foodkeeper.py  FoodKeeper JSON -> shelf-life schema (used by the import script)
    shelf_life.py  ShelfLifeIndex: name -> product matching, search, location suggestion
    expiration.py  expiration estimates, user-date resolution, expiry status
    schemas.py     all Pydantic models and enums
  db/            SQLAlchemy models, session, seeding, migrations helper, alias repo
  services/      pantry.py: PantryService (add/move/open/date/use/discard + queries)
  inputs/        InputSource protocol (Phase 3 seam: every source yields ItemDraft)
  web/           FastAPI pages (pages.py), PWA routes (pwa.py), templates, static
  main.py        create_app() factory: migrates + seeds on startup
data/
  shelf_life.json      generated from FoodKeeper (committed)
  aliases_extra.json   curated name -> product aliases
  raw/                 downloaded source data (gitignored)
migrations/      Alembic (batch mode for SQLite)
scripts/         import_foodkeeper.py, make_icons.py
tests/           pytest; conftest.py has a seeded-DB template fixture and a Clock
```

## Rules the code relies on

- **User dates always win.** Every change that affects expiration goes through
  `PantryService._recalculate`. Never write `expires_on` anywhere else.
- **Transactions:** service methods flush; the caller (web route) commits.
- **Storage clock:** only freezer moves restart it (`restarts_clock`). Pantry <-> fridge
  keeps the original date.
- **Conservative estimates:** use FoodKeeper's minimum days. Perishable categories get 0
  pantry days. Unknown food defaults to the fridge.
- **Enums in the DB:** stored as strings, so new categories need no migration.
- **Web pages:** forms post and 303-redirect; `hx-boost` swaps pages. Notices use
  `?done=<key>&item=<id>` with fixed text; never echo text from the URL. `next` redirects
  must be local paths (`_safe_next`).
- **Static assets:** CSS/JS URLs carry `?v=STATIC_VERSION` (hash of the files), which also
  names the service worker cache. Pages are never cached by the service worker.

## Common commands (PowerShell, from the repo root)

```powershell
.\.venv\Scripts\python.exe -m pytest
```

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --reload
```

```powershell
.\.venv\Scripts\alembic.exe revision --autogenerate -m "describe the change"
```

First-time setup on a new machine is in README.md ("Setup").

## Gotchas

- **Commit messages on Windows PowerShell 5.1:** a here-string message containing double
  quotes gets split into separate arguments and the commit fails. Write the message to a
  file and use `git commit -F <file>`.
- **FoodKeeper download:** fsis.usda.gov blocks scripted downloads (Akamai 403). The data
  came from the Wayback Machine snapshot of the official URL (2025-07-02). It is data
  version 128, last modified 2018. Source URL and SHA-256 are in `data/shelf_life.json`.
  Don't try to bypass the block.
- **No module-level `app`:** run uvicorn with `app.main:create_app --factory`. Importing
  `app.main` must not touch the real database.
- **Web tests** use `TestClient(app, follow_redirects=False)` so redirects can be asserted.
- **Without `--reload`,** uvicorn won't pick up Python changes; restart it.
- **`.claude/` is gitignored** (machine-specific paths, e.g. launch.json).
- **Starlette deprecation warning** about `httpx` in tests is known and harmless; switching
  to `httpx2` would be a new dependency, so ask first.

## Next steps

### Now: install on the phone
- [ ] Install Tailscale on PC and phone, enable HTTPS certificates, run the app, and
      `tailscale serve --bg 8000` (README.md, "Private HTTPS with Tailscale").
- [ ] Install from the phone: iPhone via Safari > Share > Add to Home Screen; Android via
      Chrome > Install. Check that it opens full screen with the jar icon.
- [ ] Use it for a few days and note anything awkward one-handed.

### Phase 1 backlog (small, do as needed)
- [ ] Edit an item after adding: name, quantity, unit, category, notes. There is no edit
      form yet; changing the name should re-match and recalculate.
- [ ] Undo for "Used" / "Toss" (e.g. a short-lived undo link in the notice).
- [ ] Matching misses: "smoked salmon" matches fresh fish (1 day instead of 14).
      FoodKeeper only has homemade bread. The baked goods and condiments fallbacks are
      rough. Fix with curated aliases in `data/aliases_extra.json`.
- [ ] Login, if the app will ever be on a public URL (not needed behind Tailscale).

### Phase 2: recipe recommendations (propose first, then build)
Decisions already approved (docs/DESIGN.md section 4):
- **Source:** TheMealDB first, behind a `RecipeSource` interface so other sources can be
  added or combined. Fetch the whole catalog once (list by first letter a-z) into local
  `recipes` / `recipe_ingredients` tables and rank locally. This avoids TheMealDB's
  premium multi-ingredient filter and needs no paid key.
- **Ranking** (pure module `app/core/ranking.py` with pytest tests):
  1. more selected/expiring ingredients used,
  2. fewer missing ingredients,
  3. ties go to the sooner-expiring,
  4. more other pantry items used.
  Staples count as owned. Recipes don't need to use every ingredient.
- **Ingredient matching:** the same `normalize.py` as shelf life, plus a small hierarchy
  so "chicken thigh" satisfies "chicken".
- **Modes:** Auto picks the N soonest-expiring items (default 5; excludes expired items
  and staples). Manual lets the user select specific items to use up.
- **Show** which ingredients the user has and which are missing, for each recipe.
- **Staples:** seeded (salt, pepper, oil, water, sugar, flour) in the `staples` table.
  The UI needs a page to edit them.

Suggested order: RecipeSource protocol + TheMealDB client -> catalog import into new tables
(Alembic migration) -> ranking module + tests -> staples editing -> recipe pages
(auto/manual) -> commit and push after each.

### Phase 3 (future, design only)
Camera/receipt input. Each new source implements `InputSource` and returns `ItemDraft`s.
The user always confirms or edits drafts before `PantryService.add_items` saves them.
