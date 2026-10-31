"""Account management from the command line (there is no sign-up page).

    python -m app.manage add-user <username> [--admin]
    python -m app.manage set-password <username>
    python -m app.manage set-admin <username> [--off]
    python -m app.manage list-users

Admins can create one-time invite links in the app (Settings > Invite friends).

Passwords are asked for interactively and never echoed. Uses FOOD_MANAGER_DATABASE_URL
like the app, and brings the database schema up to date first.
"""

import argparse
import getpass
import sys

from app.config import database_url
from app.db.migrate import upgrade_to_head
from app.db.session import make_engine, make_session_factory
from app.services.users import UserError, UserService


def _ask_password() -> str:
    first = getpass.getpass("Password: ")
    second = getpass.getpass("Repeat password: ")
    if first != second:
        raise UserError("Passwords don't match")
    return first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.manage")
    commands = parser.add_subparsers(dest="command", required=True)
    add_user = commands.add_parser("add-user", help="create an account")
    add_user.add_argument("username")
    add_user.add_argument("--admin", action="store_true", help="can create invite links")
    commands.add_parser("set-password", help="change an account's password").add_argument("username")
    set_admin = commands.add_parser("set-admin", help="make an account an admin")
    set_admin.add_argument("username")
    set_admin.add_argument("--off", action="store_true", help="remove admin instead")
    commands.add_parser("list-users", help="list accounts")
    args = parser.parse_args(argv)

    url = database_url()
    upgrade_to_head(url)
    engine = make_engine(url)
    try:
        with make_session_factory(engine)() as session, session.begin():
            users = UserService(session)
            if args.command == "add-user":
                user = users.create_user(args.username, _ask_password(), is_admin=args.admin)
                print(f"Created {user.username}" + (" (admin)" if user.is_admin else ""))
            elif args.command == "set-password":
                users.set_password(args.username, _ask_password())
                print(f"Password changed for {args.username.lower()} (signed out everywhere)")
            elif args.command == "set-admin":
                users.set_admin(args.username, not args.off)
                print(f"{args.username.lower()} is {'no longer ' if args.off else ''}an admin")
            else:
                for user in users.list_users():
                    print(user.username + (" (admin)" if user.is_admin else ""))
    except UserError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
