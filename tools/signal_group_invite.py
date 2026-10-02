#!/usr/bin/env python3
"""
Review-baseret invitation af medlemmer fra en JSON-liste til en Signal-gruppe.

Hver modtager skal bekræftes manuelt før updateGroup kaldes.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from signal_cli import SignalCli, SignalCliError


def load_members(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("members", [])
    if not isinstance(payload, list):
        raise ValueError("members-filen skal indeholde en JSON-liste")
    return [item for item in payload if isinstance(item, dict)]


def recipient_of(member: dict[str, Any]) -> str | None:
    value = member.get("number") or member.get("uuid") or member.get("aci") or member.get("recipient")
    return str(value) if value else None


def load_done(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def append_done(path: Path, recipient: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(recipient + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("group_id")
    parser.add_argument("members_file")
    parser.add_argument("--account", default=os.getenv("SIGNAL_NUMBER"))
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--log", default="invited.log")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.account:
        print("[-] SIGNAL_NUMBER eller --account mangler")
        return 2
    if args.limit < 1:
        print("[-] --limit skal være mindst 1")
        return 2

    try:
        members = load_members(Path(args.members_file))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"[-] kunne ikke læse medlemsfil: {exc}")
        return 2

    client = SignalCli(args.account, timeout=args.timeout)
    done_path = Path(args.log)
    done = load_done(done_path)

    ok = fail = skipped = reviewed = 0

    for member in members:
        recipient = recipient_of(member)
        if not recipient or recipient in done:
            skipped += 1
            continue
        if reviewed >= args.limit:
            print(f"[i] review-limit nået ({args.limit})")
            break

        reviewed += 1
        label = member.get("name") or recipient
        if args.dry_run:
            print(f"[dry-run] kandidat: {label} ({recipient})")
            continue

        answer = input(f"Inviter {label} ({recipient})? [y/N/q]: ").strip().casefold()
        if answer == "q":
            break
        if answer not in {"y", "yes", "j", "ja"}:
            skipped += 1
            continue

        try:
            client.run(["updateGroup", "-g", args.group_id, "-m", recipient])
        except SignalCliError as exc:
            fail += 1
            print(f"[-] fejl {recipient} ({exc.returncode}): {exc}")
            if exc.returncode == 6:
                print("[!] CAPTCHA-fejl: stopper.")
                return 6
            if exc.returncode == 5:
                print("[!] rate-limit: venter 60 sekunder før næste manuelle review.")
                time.sleep(60)
        else:
            ok += 1
            append_done(done_path, recipient)
            done.add(recipient)
            print(f"[+] inviteret: {recipient}")

    print(f"\n[i] ok={ok} fejl={fail} sprunget-over={skipped} reviewed={reviewed}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
