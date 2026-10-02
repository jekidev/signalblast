#!/usr/bin/env python3
"""
Tilføj medlemmer fra en JSON-liste til en Signal-gruppe.

Brug:
  python3 tools/signal_group_invite.py <gruppe-id> <members.json> [delay-sek]
  python3 tools/signal_group_invite.py --account +45... <gruppe-id> <members.json>
"""
from __future__ import annotations

import argparse
import json
import os
import random
import time
from pathlib import Path
from typing import Any

from signal_cli import SignalCli, SignalCliError

DEFAULT_DELAY_MIN = 8.0
DEFAULT_DELAY_MAX = 25.0


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
    parser.add_argument("delay", nargs="?", type=float)
    parser.add_argument("--account", default=os.getenv("SIGNAL_NUMBER"))
    parser.add_argument("--delay-min", type=float, default=DEFAULT_DELAY_MIN)
    parser.add_argument("--delay-max", type=float, default=DEFAULT_DELAY_MAX)
    parser.add_argument("--max-backoff", type=float, default=900.0)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--log", default="invited.log")
    parser.add_argument("--limit", type=int, default=0, help="0 = ingen ekstra limit")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.account:
        print("[-] SIGNAL_NUMBER eller --account mangler")
        return 2
    if args.delay_min < 0 or args.delay_max < args.delay_min:
        print("[-] ugyldigt delay-interval")
        return 2

    try:
        members = load_members(Path(args.members_file))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"[-] kunne ikke læse medlemsfil: {exc}")
        return 2

    client = SignalCli(args.account, timeout=args.timeout)
    done_path = Path(args.log)
    done = load_done(done_path)

    ok = fail = skipped = processed = 0
    consecutive_failures = 0
    rate_limit_streak = 0

    for member in members:
        recipient = recipient_of(member)
        if not recipient or recipient in done:
            skipped += 1
            continue
        if args.limit and processed >= args.limit:
            break

        processed += 1
        if args.dry_run:
            print(f"[dry-run] ville invitere: {recipient}")
            continue

        try:
            client.run(["updateGroup", "-g", args.group_id, "-m", recipient])
        except SignalCliError as exc:
            fail += 1
            consecutive_failures += 1
            print(f"[-] fejl {recipient} ({exc.returncode}): {exc}")

            if exc.returncode == 6:
                print("[!] CAPTCHA blev afvist/kræves. Stopper i stedet for at gentage.")
                return 6

            if exc.returncode == 5:
                rate_limit_streak += 1
                backoff = min(args.max_backoff, 60.0 * (2 ** (rate_limit_streak - 1)))
                print(f"[!] rate-limit: backoff {backoff:.0f}s")
                time.sleep(backoff)
            elif consecutive_failures >= 3:
                backoff = min(args.max_backoff, 15.0 * (2 ** (consecutive_failures - 3)))
                print(f"[!] {consecutive_failures} fejl i træk: backoff {backoff:.0f}s")
                time.sleep(backoff)
        else:
            ok += 1
            consecutive_failures = 0
            rate_limit_streak = 0
            append_done(done_path, recipient)
            done.add(recipient)
            print(f"[+] inviteret: {recipient}")

        delay = args.delay if args.delay is not None else random.uniform(args.delay_min, args.delay_max)
        if delay > 0:
            time.sleep(delay)

    print(f"\n[i] ok={ok} fejl={fail} sprunget-over={skipped} behandlet={processed}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
