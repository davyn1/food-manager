# Food Manager: project guide

Personal pantry tracker + recipe recommender. Mobile-first PWA, Python backend.
Tracks food at home, estimates expiration dates from USDA FoodKeeper data, and (Phase 2)
recommends recipes that use up what's expiring.

- **How to set up and run:** [README.md](README.md)
- **Architecture, schema, data and all design decisions:** [docs/DESIGN.md](docs/DESIGN.md)
- **What to do next:** the "Next steps" section at the bottom of this file
- **What may need changing with more users:** [docs/SCALING.md](docs/SCALING.md). Add to
  it when you notice a new limit.
- **Who it's for, voice and product principles:** [PRODUCT.md](PRODUCT.md) (read before
  any UI or copy work).

## Status (as of 2026-11-05)

Phase 1 (pantry tracker) is built, tested and live: steps 1-8 in docs/DESIGN.md section 7,
plus accounts (login, separate pantry per person, one-time invite links, change
password), the "day dots" visual design, the playful voice, undo for Used/Toss, and asking
for a date when food isn't recognized, and editing items. 389 tests pass; everything is
pushed to `main` on
https://github.com/davyn1/food-manager.

Users: mainly Elaine (forgetful; the app remembers for her), plus the owner (Davy, admin)
and a few friends, 4-5 people in total, each with their own pantry. Friends join through
invite links from Settings > Invite friends.

Live at **https://elaineisforgetful-pantry.fly.dev** (Fly app `elaineisforgetful-pantry`,
region `lax`, volume `pantry_data` 1 GB with daily snapshots kept 5 days, secret
`FOOD_MANAGER_SECRET_KEY` set). Last deployed 2026-11-06 with everything above. The first
app, `davy-pantry`, was destroyed (Fly apps can't be renamed). Ship changes with
`fly deploy --depot=false`. flyctl is installed on the dev PC and signed in.

Accounts (as of 2026-11-05): `davy` (admin) and `elaine`. Still to do: inviting the other
friends and installing on everyone's phones (the owner's tasks).

## How to work on this project

- **Phases:** build in phases. Don't start a later phase until the current one works and
  is tested. Phase 3 (camera/receipt input) is design-only; don't build it yet.
- **Small steps:** build one small working piece at a time, with pytest tests.
- **Commit and push after each finished part,** to `main` on origin.
- **Commit messages:** well written, or brief and explanatory. A short subject that says
  what changed (and why, if not obvious), then a few lines of body only when needed. No
  file-by-file lists. End with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Split commits** when it makes the history clearer: e.g. a logic change, its UI, and
  its docs can be separate commits. Don't bundle unrelated changes.
- **Deploys** are public-facing: ask the owner before each `fly deploy`.
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
  services/      pantry.py: PantryService for one owner (add/move/open/date/use/discard
                 + queries); users.py: accounts, login, invites, password changes
  manage.py      CLI: add-user [--admin] / set-password / set-admin / list-users
  inputs/        InputSource protocol (Phase 3 seam: every source yields ItemDraft)
  web/           FastAPI pages (pages.py), login/logout/sign-up (auth.py), password and
                 invites (account.py), PWA routes (pwa.py), display helpers incl. day
                 dots (templating.py), templates (partials/: dot, icons, item_row,
                 preview, date_chips), static
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
- **Separate pantries:** `PantryService` is built for one user; every items query goes
  through `_items()` / `_row()`, which filter on `owner_id`. Another user's item must
  behave exactly like a missing one (404). Never query `ItemRow` without the owner filter.
- **Login:** pages get the user via the `get_pantry` dependency, which redirects to
  `/login` when signed out. Only `/login`, `/signup/<token>`, `/health`, the PWA files,
  `/offline` and `/static` are public. Sign people in with `deps.sign_in` so the cookie
  carries `session_version`; bumping it (password change/reset) signs out other devices.
- **Invites:** only the SHA-256 of a token is stored, so a link is shown once (the create
  route renders the page rather than redirecting). Only admins manage invites.
- **Storage clock:** only freezer moves restart it (`restarts_clock`). Pantry <-> fridge
  keeps the original date.
- **Conservative estimates:** use FoodKeeper's minimum days. Perishable categories get 0
  pantry days. Unknown food defaults to the fridge.
- **Don't guess unknown food:** a match must cover more than half the name and name the
  product (`MIN_SCORE`, `_plausible_partial`). With no match, no category and no date,
  `add_item` raises `NeedsDate` and the UI asks "When does it go bad?".
- **Voice (PRODUCT.md):** playful and teasing in empty states and confirmations; dates,
  warnings and errors stay plain. Notice text is fixed in `pages.NOTICES`.
- **Visual design:** "day dots" (docs/DESIGN.md, "Visual design"), dressed as
  "kitchen labels": masking-tape page titles, marker section names on shelf edges,
  shelves with a front lip. The dot stays the loudest element; marker never goes on
  body text, dates or buttons. Colors are CSS variables in `app.css`, with a dark mode; keep text
  contrast at 4.5:1 or more. The Impeccable design hook runs after UI edits
  (`.impeccable/config.json`).
- **Enums in the DB:** stored as strings, so new categories need no migration.
- **Web pages:** forms post and 303-redirect; `hx-boost` swaps pages. Notices use
  `?done=<key>&item=<id>` with fixed text; never echo text from the URL. `next` redirects
  must be local paths (`pages.safe_next`).
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
- **`fly ssh console` needs a running machine.** It stops when idle, so wake it first
  (e.g. `curl https://elaineisforgetful-pantry.fly.dev/health`).
- **Fly builds:** the default Depot builder fails from this PC (TLS "certificate signed by
  unknown authority"); always deploy with `--depot=false`. Piping text into
  `fly secrets import` from PowerShell adds a BOM; use `fly secrets set` instead.
- **Running a Python check on the server:** quoting `python -c "..."` through PowerShell
  and `fly ssh console -C` breaks. Pipe a script instead, after
  `$OutputEncoding = New-Object Text.UTF8Encoding $false` (no BOM):
  `Get-Content check.py -Raw | fly ssh console -C "python -"`.
- **Demo data for screenshots** lives in a scratch DB via `.claude/launch.json`
  (`food-manager-demo`), never the real dev or live database.
- **Uvicorn on Windows expands a bare `*`** in arguments into file names, so locally use
  `--forwarded-allow-ips=*`. The Dockerfile's exec form passes `*` through fine on Linux.
- **Tests lower the scrypt cost** (autouse fixture in conftest) so password hashing is fast.
  `tests/conftest.py` has `make_app` and `signed_in_client` for web tests.
- **Starlette deprecation warning** about `httpx` in tests is known and harmless; switching
  to `httpx2` would be a new dependency, so ask first.

## Next steps

### Now: accounts and install on the phones
- [x] Deploy to Fly.io (README.md, "Deploy to Fly.io"): launch, volume, secret, deploy.
- [x] Deploy the invites/password work (2026-10-31, to `elaineisforgetful-pantry`).
      Every deploy needs the owner's go-ahead (public-facing).
- [x] Owner creates their admin account (`davy`, 2026-10-31):
      `fly ssh console --pty -C "python -m app.manage add-user davy --admin"`.
      The owner types the password; never enter or choose passwords for them.
- [ ] Owner sends each friend an invite link from Settings > Invite friends.
- [ ] Install from each phone: iPhone via Safari > Share > Add to Home Screen; Android via
      Chrome > Install. Check that it opens full screen with the jar icon.
- [ ] Use it for a few days and note anything awkward one-handed.

### Phase 1 backlog (small, do as needed)
Suggested next: Phase 2 (recipes).
- [ ] Quick-add buttons for frequently added items, under the add box.
- [ ] Date shortcuts (3 days / 1 week / 1 month) next to every date field, not only for
      unknown food (`partials/date_chips.html` already exists).
- [ ] Search on All items.
- [ ] The baked goods and condiments category fallbacks are rough (they only apply when
      nothing matches and the user picks that category).
- [ ] An unknown item with category "Other" moved to the pantry gets 180 days (the "other"
      median). Make that fallback much more cautious.
- [ ] Undecided: whether the in-app name stays "Pantry" or leans into the
      "elaineisforgetful" joke (PRODUCT.md).
- [x] Edit an item (name, amount, unit, category, notes; renaming re-matches and
      recalculates). Deployed 2026-11-05.
- [x] Fix common name misses (bread, smoked salmon, cheese, spring mix, corn, pasta
      sauce, cooked chicken, ...) with curated aliases. Deployed 2026-11-06.
- [x] Undo for "Used" / "Toss" (Undo button in the notice, 10 s).
- [x] Ask for a date when food isn't recognized (one-tap 3 days / 1 week / ...).
- [x] Password change from the app (Settings > Change password).
- [x] Visual redesign ("day dots") and playful copy.

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

### Later, as the group grows
Not scheduled; see docs/SCALING.md: expiry notifications or a daily email, password reset
without the admin, shared household pantries, self-hosted fonts, longer backups, an admin
page for accounts.
