# Food Manager

Pantry tracker that estimates expiration dates and recommends recipes for food that
needs using up. Mobile-first PWA with a Python (FastAPI) backend.

See [docs/DESIGN.md](docs/DESIGN.md) for the approved architecture and build plan.

## Setup (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
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
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000/health
