# Scaling notes

The app is built for the owner plus a handful of friends (about 2-6 people) on one small
Fly.io machine. Nothing below needs doing now. Each item says what it is today, what would
make it a problem, and what to change then.

## Accounts and access

| Area | Today | When it becomes a problem | What to change |
|---|---|---|---|
| **Joining** | Admins create one-time invite links (7 days) in Settings > Invite friends. | Many invites a week, or friends inviting friends. | Let non-admins invite (with a per-user limit), or add an approval step. |
| **Forgotten passwords** | No email. An admin runs `python -m app.manage set-password <name>` on the server. | You're asked to reset passwords often, or you're unavailable. | Add email (e.g. Resend/Postmark) for reset links, or let admins generate a one-time "reset link" in the app like invites. |
| **Admins** | Set with `add-user --admin` / `set-admin`. Admins can only manage invites. | You need to remove someone or see who's active. | An admin page: list accounts, disable/delete an account (items are deleted with it), last sign-in time. |
| **Deleting an account** | Only by hand in the database. | Someone leaves and wants their data gone. | Self-service "Delete my account" in Settings, plus the admin page above. |
| **Signing out other devices** | Changing a password signs out everywhere else. | Someone loses a phone but doesn't want to change their password. | A "Sign out all other devices" button (bump `session_version` without a password change). |
| **Login lockout** | In memory: 10 failures lock a username for 15 minutes, per machine; resets on restart. | More than one machine, or someone deliberately locking out a friend's username. | Store failures in the database; lock by username + IP; consider a short delay instead of a lock. |

## Data and sharing

| Area | Today | When it becomes a problem | What to change |
|---|---|---|---|
| **Separate pantries** | Every item has one owner. | Two friends live together and want one shared fridge. | A "household" that several accounts belong to; items owned by the household. Needs a migration and changes to `PantryService` scoping. |
| **Learned name corrections** | Shared by everyone (one person teaching "smoked salmon" changes it for all). | Someone's odd correction keeps confusing others. | Store learned aliases per user (or per household), falling back to shared ones. |
| **Admin can read all data** | The database is one file; whoever runs the server can read every pantry. | Friends expect real privacy from the operator. | Be upfront about it. True privacy from the operator would mean end-to-end encryption, which isn't worth it for a pantry. |

## Server, database and cost

| Area | Today | When it becomes a problem | What to change |
|---|---|---|---|
| **One machine** | One 256 MB Fly machine (peak about 124 MB measured). It stops when idle. | Pages feel slow, or memory errors in `fly logs`. | `fly scale memory 512` (about double the machine cost). Keep it to one machine while on SQLite. |
| **Cold starts** | The first visit after a quiet spell takes 1-2 s. | People find it annoying. | Set `min_machines_running = 1` in `fly.toml` (the machine runs all month; still a few dollars). |
| **SQLite** | One database file on a 1 GB volume attached to one machine. | Dozens of active users writing at once, wanting more than one machine or region, or wanting zero-downtime deploys. | Move to Postgres (e.g. the Neon account you already have): add a driver, set `FOOD_MANAGER_DATABASE_URL`, run the Alembic migrations, copy the data over. The code uses SQLAlchemy, so most of it doesn't change. |
| **Downtime** | One machine and one volume: if that host has a problem, the app is down until it's back. A deploy restarts it (a few seconds). | People rely on it at all hours. | Postgres plus two machines (see above). |
| **Backups** | Fly takes daily volume snapshots, kept 5 days. | You want history older than 5 days, or a copy outside Fly. | Raise retention (`fly volumes update <id> --snapshot-retention <days>`), or stream the database elsewhere with Litestream (to S3/R2), or a nightly `sqlite3 .backup` job. Test a restore once. |
| **Storage** | 1 GB volume; a pantry uses kilobytes. | Phase 3 photos, if they're ever stored. | Store images in object storage (Fly Tigris / S3), not the volume; or grow it with `fly volumes extend`. |
| **Password hashing memory** | Each login uses about 32 MB briefly (scrypt). | Several people signing in at the same instant on a 256 MB machine. | Unlikely at this size. If it shows up: more memory, or lower the scrypt cost a little. |

## Phase 2 and beyond

| Area | Today | When it becomes a problem | What to change |
|---|---|---|---|
| **Recipe source** | Planned: TheMealDB, catalog cached locally. | Before sharing the app more widely. | Check TheMealDB's terms: its free test key is meant for development and education, and a public app should use a supporter key. Spoonacular or a local dataset are alternatives (see DESIGN.md section 4). |
| **Notifications** | None; the app shows expiring items when opened. | People want reminders. | Web Push (iOS 16.4+ only for the installed app) with VAPID keys and a daily scheduled job, or a daily email digest. |
| **Monitoring** | `fly logs` and the `/health` check. | Problems go unnoticed. | Fly's metrics dashboard, an uptime checker on `/health`, and error reporting (e.g. Sentry's free tier). |
| **Fonts** | Atkinson Hyperlegible and Permanent Marker load from Google Fonts, so each visit tells Google the visitor's IP; offline, the system font is used. | Privacy matters to the group, or you want the fonts offline. | Self-host the `.woff2` files in `app/web/static/fonts/` (both are OFL-licensed) and add them to the service worker's precache list. |
| **Abuse** | Only invited people can sign up; no other rate limits. | The link to the site is shared publicly. | Rate-limit adding items and other writes per user; invites already stop strangers from joining. |
