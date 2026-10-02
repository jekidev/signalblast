#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOOLS = ROOT / "tools"


def run(cmd: list[str]) -> int:
    print("$", " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT, check=False).returncode


def account() -> str:
    value = os.getenv("SIGNAL_NUMBER", "").strip()
    if value:
        return value
    return input("Signal-konto (+landekode...): ").strip()


def doctor() -> int:
    print("== Signalblast doctor ==")
    checks = {
        "python": sys.executable,
        "uv": shutil.which("uv"),
        "docker": shutil.which("docker"),
        "signal-cli": shutil.which("signal-cli"),
    }
    for name, value in checks.items():
        print(f"{name:12}: {value or 'ikke fundet'}")
    print(f"SIGNAL_NUMBER: {'sat' if os.getenv('SIGNAL_NUMBER') else 'mangler'}")

    if checks["signal-cli"]:
        return 0
    if checks["docker"]:
        result = subprocess.run(
            ["docker", "compose", "ps", "-q", "signal-cli-rest-api"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        print(f"docker Signal API: {'kører' if result.stdout.strip() else 'ikke startet'}")
        return 0 if result.stdout.strip() else 1
    return 1


def bootstrap() -> int:
    print("== Bootstrap ==")
    if shutil.which("uv"):
        rc = run(["uv", "sync"])
    else:
        rc = run([sys.executable, "-m", "pip", "install", "-e", "."])
    if rc != 0:
        return rc

    if shutil.which("docker"):
        rc = run(["docker", "compose", "pull", "signal-cli-rest-api"])
        if rc != 0:
            return rc
        return run(["docker", "compose", "up", "-d", "signal-cli-rest-api"])

    if shutil.which("signal-cli"):
        print("[+] native signal-cli er allerede installeret")
        return 0

    print("[-] hverken Docker eller native signal-cli blev fundet.")
    print("    Installer Docker eller signal-cli og kør bootstrap igen.")
    return 1


def list_groups() -> int:
    sys.path.insert(0, str(TOOLS))
    from signal_cli import SignalCli, SignalCliError, group_id

    acc = account()
    if not acc:
        return 2
    try:
        groups = SignalCli(acc).list_groups()
    except SignalCliError as exc:
        print(f"[-] {exc}")
        return exc.returncode or 1

    for item in groups:
        print(f"- {item.get('name') or '<uden navn>'}: {group_id(item) or '<uden id>'}")
    return 0


def export_members() -> int:
    src = input("Gruppe (navn eller id): ").strip()
    out = input("Output-fil [members.json]: ").strip() or "members.json"
    env = os.environ.copy()
    env["SIGNAL_NUMBER"] = account()
    return subprocess.run(
        [sys.executable, str(TOOLS / "signal_group_scrape.py"), src, out],
        cwd=ROOT,
        env=env,
        check=False,
    ).returncode


def review_invites() -> int:
    dst = input("Målgruppe-id: ").strip()
    members = input("Medlemsfil [members.json]: ").strip() or "members.json"
    env = os.environ.copy()
    env["SIGNAL_NUMBER"] = account()
    return subprocess.run(
        [sys.executable, str(TOOLS / "signal_group_invite.py"), dst, members],
        cwd=ROOT,
        env=env,
        check=False,
    ).returncode


def start_bot() -> int:
    if not shutil.which("docker"):
        print("[-] Docker mangler")
        return 1
    return run(["docker", "compose", "up", "-d", "signalblast"])


def logs() -> int:
    if not shutil.which("docker"):
        print("[-] Docker mangler")
        return 1
    return run(["docker", "compose", "logs", "--tail", "100", "-f", "signalblast"])


def menu() -> int:
    actions = {
        "1": ("Doctor / diagnostics", doctor),
        "2": ("Bootstrap / auto-setup", bootstrap),
        "3": ("List Signal-grupper", list_groups),
        "4": ("Eksporter medlemsoversigt", export_members),
        "5": ("Review og inviter valgte modtagere", review_invites),
        "6": ("Start Signalblast bot", start_bot),
        "7": ("Følg Signalblast logs", logs),
    }

    while True:
        print("\n=== Signalblast Launcher ===")
        for key, (label, _) in actions.items():
            print(f"{key}. {label}")
        print("0. Afslut")
        choice = input("> ").strip()
        if choice == "0":
            return 0
        action = actions.get(choice)
        if not action:
            print("Ugyldigt valg")
            continue
        print()
        rc = action[1]()
        print(f"[i] exit={rc}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        nargs="?",
        choices=["menu", "doctor", "bootstrap", "groups", "export", "invite", "start", "logs"],
        default="menu",
    )
    args = parser.parse_args()
    commands = {
        "menu": menu,
        "doctor": doctor,
        "bootstrap": bootstrap,
        "groups": list_groups,
        "export": export_members,
        "invite": review_invites,
        "start": start_bot,
        "logs": logs,
    }
    return commands[args.command]()


if __name__ == "__main__":
    raise SystemExit(main())
