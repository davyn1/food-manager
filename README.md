# Food Manager

Pantry tracker that estimates expiration dates and recommends recipes for food that
needs using up. Mobile-first PWA with a Python (FastAPI) backend.

See [docs/DESIGN.md](docs/DESIGN.md) for the approved architecture and build plan.

## Setup (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Create and seed the database

Creates `data/food_manager.db` (set `FOOD_MANAGER_DATABASE_URL` to use another
location), then loads shelf-life data, staples and default settings. Both are safe to
re-run.

```powershell
.\.venv\Scripts\alembic.exe upgrade head
```

```powershell
.\.venv\Scripts\python.exe -m app.db.seed
```

After changing models in `app/db/models.py`, generate a migration with:

```powershell
.\.venv\Scripts\alembic.exe revision --autogenerate -m "describe the change"
```

## Run tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Regenerate shelf-life data

`data/shelf_life.json` is committed. To rebuild it, save the USDA FoodKeeper JSON as
`data/raw/foodkeeper.json` (see [docs/DESIGN.md](docs/DESIGN.md)), then:

```powershell
.\.venv\Scripts\python.exe scripts\import_foodkeeper.py
```

## Run the dev server

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --reload
```

Then open http://127.0.0.1:8000. On startup the app migrates and seeds the database
automatically, so the two database commands above are only needed for manual setup.

To try it on your phone over your home Wi-Fi (no install as an app yet; that needs
HTTPS, which comes with step 8):

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 0.0.0.0
```

Then open `http://<your PC's local IP>:8000` on the phone. Windows Firewall may ask
to allow Python on private networks.
