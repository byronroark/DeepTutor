"""Fresh learner-host accounts, run only in a private interactive terminal."""

import argparse
import getpass
import re
import sys

# This reviewed script is mounted in /tmp, outside the image's package root.
sys.path.insert(0, "/app")

from deeptutor.services.auth import add_user, list_users


def password(label):
    while True:
        value = getpass.getpass(label + " password: ")
        if not 8 <= len(value.encode()) <= 72:
            print("Use 8–72 bytes for the password.")
            continue
        if getpass.getpass("Confirm password: ") == value:
            return value
        print("Passwords did not match. Try again.")


def main(learner):
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", learner):
        raise SystemExit("Use a plain learner login name")
    users = list_users()
    if users:
        if any(u["role"] == "admin" for u in users) and any(
            u["username"] == learner and u.get("preset") == "learner" and u["role"] != "admin"
            for u in users
        ):
            print("Existing parent and learner accounts preserved.")
            return
        raise SystemExit(
            "Partial account setup found. Stop and review it; no accounts were overwritten."
        )
    name = input("First parent login name [dad]: ").strip() or "dad"
    if name == learner:
        raise SystemExit("The parent and learner must have different login names.")
    first_password = password("Parent " + name)
    second = input("Second parent login name [mom; leave blank to skip]: ").strip()
    if second:
        if second in {name, learner}:
            raise SystemExit("Each account needs a different login name.")
        second_password = password("Parent " + second)
    learner_password = password("Learner " + learner)
    add_user(name, first_password, role="admin")
    if second:
        add_user(second, second_password, role="admin")
    add_user(learner, learner_password, role="user", preset="learner")
    print(
        "Fresh Family Learning accounts created. No AI connection or old account data was copied."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--learner", required=True)
    main(parser.parse_args().learner)
