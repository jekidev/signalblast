#!/usr/bin/env python3
"""
Eksporter medlemmer fra en Signal-gruppe til JSON.

Brug:
  python3 tools/signal_group_scrape.py <gruppe-id-eller-navn> [output.json]
  python3 tools/signal_group_scrape.py --account +45... <gruppe> [output.json]

SIGNAL_NUMBER kan bruges i stedet for --account.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from signal_cli import SignalCli, SignalCliError, group_id


def find_group(groups: list[dict[str, Any]], query: str) -> dict[str, Any] | None:
    q = query.casefold()
    exact_id = [g for g in groups if (group_id(g) or "").casefold() == q]
    if exact_id:
        return exact_id[0]

    exact_name = [g for g in groups if str(g.get("name") or "").casefold() == q]
    if exact_name:
        return exact_name[0]

    partial = [g for g in groups if q in str(g.get("name") or "").casefold()]
    return partial[0] if len(partial) == 1 else None


def _member_record(value: Any, *, pending: bool, admins: set[str]) -> dict[str, Any] | None:
    if isinstance(value, str):
        record: dict[str, Any] = {"recipient": value}
    elif isinstance(value, dict):
        record = {
            "number": value.get("number") or value.get("phoneNumber"),
            "uuid": value.get("uuid") or value.get("aci"),
            "name": value.get("name") or value.get("profileName"),
        }
        fallback = value.get("recipient") or value.get("id")
        if not record["number"] and not record["uuid"] and fallback:
            record["recipient"] = fallback
    else:
        return None

    identity = record.get("number") or record.get("uuid") or record.get("recipient")
    if not identity:
        return None

    if pending:
        record["pending"] = True
    if str(identity) in admins:
        record["admin"] = True
    return {k: v for k, v in record.items() if v not in (None, False)}


def get_members(group: dict[str, Any]) -> list[dict[str, Any]]:
    admins = {str(x) for x in (group.get("admins") or [])}
    combined: list[dict[str, Any]] = []

    for value in group.get("members") or []:
        record = _member_record(value, pending=False, admins=admins)
        if record:
            combined.append(record)

    for value in group.get("pendingMembers") or []:
        record = _member_record(value, pending=True, admins=admins)
        if record:
            combined.append(record)

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in combined:
        key = str(record.get("number") or record.get("uuid") or record.get("recipient"))
        if key not in seen:
            seen.add(key)
            deduped.append(record)
    return deduped


def _record_key(record: dict[str, Any]) -> str | None:
    value = record.get("number") or record.get("uuid") or record.get("recipient")
    return str(value) if value else None


def save_members(members: list[dict[str, Any]], path: Path) -> tuple[int, int]:
    existing: list[dict[str, Any]] = []
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                existing = [x for x in loaded if isinstance(x, dict)]
        except (OSError, json.JSONDecodeError):
            existing = []

    seen = {key for item in existing if (key := _record_key(item))}
    added = 0
    for member in members:
        key = _record_key(member)
        if key and key not in seen:
            existing.append(member)
            seen.add(key)
            added += 1

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        json.dump(existing, tmp, indent=2, ensure_ascii=False)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)
    return added, len(existing)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("group")
    parser.add_argument("output", nargs="?", default="members.json")
    parser.add_argument("--account", default=os.getenv("SIGNAL_NUMBER"))
    parser.add_argument("--timeout", type=int, default=30)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.account:
        print("[-] SIGNAL_NUMBER eller --account mangler")
        return 2

    client = SignalCli(args.account, timeout=args.timeout)
    try:
        groups = client.list_groups()
    except SignalCliError as exc:
        print(f"[-] listGroups fejl ({exc.returncode}): {exc}")
        return exc.returncode or 1

    group = find_group(groups, args.group)
    if not group:
        print(f"[-] gruppe '{args.group}' blev ikke entydigt fundet")
        print("[i] tilgængelige grupper:")
        for item in groups:
            print(f"    - {item.get('name') or '<uden navn>'}  {group_id(item) or '<uden id>'}")
        return 1

    gid = group_id(group)
    print(f"[+] gruppe: {group.get('name') or '<uden navn>'} ({gid or '<uden id>'})")
    members = get_members(group)
    print(f"[i] {len(members)} medlemmer/pending poster fundet")
    added, total = save_members(members, Path(args.output))
    print(f"[+] {added} nye gemt. Total i {args.output}: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
