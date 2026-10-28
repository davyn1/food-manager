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

To try it on your phone over your home Wi-Fi (works in the browser, but installing to
the home screen needs HTTPS; see below):

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 0.0.0.0
```

Then open `http://<your PC's local IP>:8000` on the phone. Windows Firewall may ask
to allow Python on private networks.

## Install on a phone

Installing needs the app served over HTTPS. Once it is:

- **iPhone (Safari):** open the site, tap **Share**, then **Add to Home Screen**.
- **Android (Chrome):** open the site and tap **Install** in the banner, or use the
  menu's **Install app** / **Add to Home screen**.

The app has no login yet, so only serve it somewhere private (or add a login before
putting it on a public URL). See [docs/DESIGN.md](docs/DESIGN.md) for iOS limitations.

### Private HTTPS with Tailscale

Tailscale gives this PC an HTTPS address that only your own signed-in devices can reach.
The phone can use the app whenever the PC is on and the app is running.

1. Install Tailscale on the PC from https://tailscale.com/download/windows and sign in.
2. Install the Tailscale app on the phone (App Store / Play Store) and sign in with the
   same account. Leave it connected.
3. In the admin console's DNS page (https://login.tailscale.com/admin/dns), make sure
   **MagicDNS** is on and enable **HTTPS Certificates**. (If you skip this,
   `tailscale serve` will send you to a page to enable it.)
4. Start the app on the PC. It only needs to listen on the PC itself:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --port 8000
   ```

5. In a second terminal (open a new one after installing so `tailscale` is on PATH),
   share it to your devices over HTTPS. `--bg` keeps sharing on until you turn it off:

   ```powershell
   tailscale serve --bg 8000
   ```

6. See the address, which looks like `https://<pc-name>.<tailnet-name>.ts.net`:

   ```powershell
   tailscale serve status
   ```

7. On the phone, open that address and install (iPhone: Safari, Share, Add to Home
   Screen; Android: Chrome, Install). The first load can take a few seconds while the
   certificate is issued.

To stop sharing:

```powershell
tailscale serve reset
```

Notes: the HTTPS certificate is public record (certificate transparency logs), so the PC
and tailnet names are visible, though nobody outside your tailnet can connect. If the
PC sleeps or the app stops, the phone shows the offline page until it's back.

## Regenerate icons

```powershell
.\.venv\Scripts\python.exe scripts\make_icons.py
```
