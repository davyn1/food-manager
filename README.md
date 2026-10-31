# Food Manager

Pantry tracker that estimates expiration dates and recommends recipes for food that
needs using up. Mobile-first PWA with a Python (FastAPI) backend.

See [docs/DESIGN.md](docs/DESIGN.md) for the approved architecture and build plan, and
[CLAUDE.md](CLAUDE.md) for current status, working conventions and the next-steps list.

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

## Accounts

Each account has its own pantry. There is no open sign-up: an **admin** creates one-time
invite links in the app (Settings > **Invite friends**). A link works once and expires
after 7 days; whoever opens it picks their own username and password.

Create the first (admin) account from the command line. You'll be asked for the password
twice; it isn't shown while you type:

```powershell
.\.venv\Scripts\python.exe -m app.manage add-user davy --admin
```

Other commands: `set-password <username>` (also signs them out everywhere),
`set-admin <username>` (add `--off` to remove), and `list-users`. People can change their
own password in Settings.

How this might need to change with more people: [docs/SCALING.md](docs/SCALING.md).

## Deploy to Fly.io

**Live at https://davy-pantry.fly.dev** (app `davy-pantry`, region `lax`). Steps 1-4
below are already done; to ship changes, just run `fly deploy --depot=false`. To create
your account and invite friends, see steps 5-6.

The app runs on one small Fly machine (256 MB, about $2.20/month) with a 1 GB volume
for the SQLite database (about $0.15/month). It stops when nobody is using it and starts
again on the next visit (a second or two). Fly builds the image remotely, so Docker isn't
needed locally. The commands below use region `lax` (Los Angeles); pick another with
`fly platform regions` if you like, and use it everywhere.

1. Create the app from the config in this repo. The name must be unique on Fly and
   becomes the address `https://<app-name>.fly.dev`:

   ```powershell
   fly launch --no-deploy --copy-config --name <app-name> --region lax
   ```

2. Create the volume for the database:

   ```powershell
   fly volumes create pantry_data --size 1 --region lax --yes
   ```

3. Create the secret key that signs logins (random, never committed):

   ```powershell
   fly secrets set --stage "FOOD_MANAGER_SECRET_KEY=$(.\.venv\Scripts\python.exe -c 'import secrets; print(secrets.token_urlsafe(48))')"
   ```

4. Deploy (one machine, since SQLite lives on one volume). `--depot=false` uses Fly's
   own builder: on this PC the default Depot builder failed with "certificate signed
   by unknown authority".

   ```powershell
   fly deploy --ha=false --depot=false
   ```

5. Open `https://<app-name>.fly.dev` once to wake the machine, then create your own
   admin account. It asks for your password:

   ```powershell
   fly ssh console --pty -C "python -m app.manage add-user davy --admin"
   ```

6. Sign in, go to Settings > **Invite friends**, and send each friend their own link.
   Everyone then installs it on their phone (below).

Later updates: commit, then run `fly deploy --depot=false`. Logs: `fly logs`. Fly keeps automatic
daily snapshots of the volume; list them with `fly volumes list` and
`fly volumes snapshots list <volume-id>`.

## Install on a phone

Installing needs the app served over HTTPS (the Fly.io address above). Then:

- **iPhone (Safari):** open the site, tap **Share**, then **Add to Home Screen**.
- **Android (Chrome):** open the site and tap **Install** in the banner, or use the
  menu's **Install app** / **Add to Home screen**.

On iPhone the installed app keeps its own sign-in, separate from Safari, so you sign in
once more the first time you open it from the home screen. You then stay signed in for
about six months. See [docs/DESIGN.md](docs/DESIGN.md) for iOS limitations.

### Alternative: private HTTPS with Tailscale

Not used for now (the app is hosted on Fly.io), but kept for reference.

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
