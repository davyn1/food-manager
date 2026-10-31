# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Primary: Elaine**, who forgets what's in her fridge and pantry until it has gone bad.
  The app is built mainly for her. Her main moment is checking what she needs to use up
  before it spoils, and logging food after shopping so the app can remember for her.
- **Secondary:** the owner (Davy, the admin) and a small group of friends, about 4-5
  people in total. Each person has their own private pantry; they join only through a
  one-time invite link from the admin.

## Product Purpose

A phone app that remembers when food will go bad, so less of it gets thrown out. It
estimates an expiration date for everything logged, including food with no printed date,
puts whatever needs using soonest first, and (Phase 2, planned) suggests meals that use
up what's about to expire.

Success means two things: less food thrown out, and easy meal ideas built from what's
expiring.

## Positioning

Most pantry apps only know the date you type in. This one estimates a date for anything
from its name, where it's stored and whether it's opened, using USDA FoodKeeper
shelf-life data, and stays conservative. A printed date the user enters always wins over
the estimate. Recipe suggestions (planned) are ranked by how much of the soon-to-expire
food they use, not by popularity.

## Operating Context

- Used on a phone, mostly one-handed, from the home-screen app (installed PWA) or the
  phone's browser. Typical moments: in the kitchen deciding what to eat, and putting
  groceries away.
- Adding is a few words of typing ("chicken thighs"); the app guesses where it's stored
  and when it expires, and the user can correct the match.
- Each person sees only their own pantry. The admin creates invite links in Settings.
- Hosted at https://elaineisforgetful-pantry.fly.dev on one small Fly.io machine that
  sleeps when idle (first visit after a quiet spell takes a second or two).

## Capabilities and Constraints

- Today: add items (name, optional amount, unit, location, opened, printed date,
  category), live preview of match and estimate, move between pantry/fridge/freezer,
  mark opened, set or clear a printed date, correct the shelf-life match, use some, mark
  used, throw out; lists for "use soon", all items (filter by location, sort by date or
  name) and expired; per-person "use soon" window; invites; change password.
- Terminology in the app: pantry, fridge, freezer; "use soon"; "past its date"/expired;
  "used it all"; "threw it out"/"toss"; "printed date" (date on the package) versus
  "estimated".
- Planned (Phase 2): recipe suggestions from expiring items, in an automatic mode
  (soonest-expiring items) and a manual mode (pick items to use up); shows which
  ingredients you have and which you'd need; a user-editable staples list (salt, pepper,
  oil...) counted as always available.
- Future (Phase 3, design only): adding items from a photo or receipt, always confirmed
  by the user before saving.
- No notifications (iOS only allows them for installed apps on 16.4+, with a server
  scheduler); the app shows what's expiring when opened.
- No email: forgotten passwords are reset by the admin.
- Pages need a connection; offline shows an offline page.
- Shelf-life data is USDA FoodKeeper data version 128 (2018). Estimates are guidance,
  not food-safety guarantees.

## Brand Commitments

- **Voice: playful and teasing**, leaning into the joke that Elaine is forgetful:
  affectionate ribbing, never mean, and never at the cost of clarity. Dates, warnings and
  errors stay plain and exact.
- **Name:** shows as "Pantry" on the home screen and in the app; the address is
  `elaineisforgetful-pantry`. Whether the in-app name should change to match the joke is
  undecided.
- **Existing assets:** app icon (a jar on green) in `app/web/static/icons/`, drawn by
  `scripts/make_icons.py`.

## Evidence on Hand

- Real shelf-life data: `data/shelf_life.json` (661 FoodKeeper products) and curated
  aliases in `data/aliases_extra.json`.
- No user research, testimonials, usage numbers or food-waste savings exist yet. Don't
  invent any.

## Product Principles

1. **Nothing goes bad unnoticed.** Whatever needs using soonest is always the first thing
   you see.
2. **Logging is faster than forgetting.** Adding food takes a few words and one tap; the
   app fills in the rest and lets you fix it later.
3. **Tease, but never confuse.** The joke lives in the friendly copy; dates, amounts and
   errors are always plain.
4. **Careful with food safety.** Estimates lean conservative, and the date on the package
   always wins.
5. **Your pantry is yours.** Each person's food is private; joining is by invite only.
