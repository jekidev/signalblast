#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any


class SignalCliError(RuntimeError):
    def __init__(self, message: str, returncode: int = 1, stdout: str = "", stderr: str = "") -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@dataclass
class SignalCli:
    account: str
    timeout: int = 30

    @staticmethod
    def _base_command() -> list[str]:
        configured = os.getenv("SIGNAL_CLI_COMMAND")
        if configured:
            return shlex.split(configured)

        native = shutil.which("signal-cli")
        if native:
            return [native]

        docker = shutil.which("docker")
        if docker:
            probe = subprocess.run(
                [docker, "compose", "ps", "-q", "signal-cli-rest-api"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if probe.returncode == 0 and probe.stdout.strip():
                return [docker, "compose", "exec", "-T", "signal-cli-rest-api", "signal-cli"]

        raise SignalCliError(
            "signal-cli blev ikke fundet. Kør launcher.py bootstrap, start Docker-servicen, "
            "eller sæt SIGNAL_CLI_COMMAND til den kommando der skal bruges."
        )

    def run(self, args: list[str], *, json_output: bool = False) -> subprocess.CompletedProcess[str]:
        cmd = self._base_command() + ["-a", self.account]
        if json_output:
            cmd += ["-o", "json"]
        cmd += args

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SignalCliError(f"signal-cli timeout efter {self.timeout}s") from exc

        if result.returncode != 0:
            msg = (result.stderr or result.stdout or "ukendt signal-cli fejl").strip()
            raise SignalCliError(msg, result.returncode, result.stdout, result.stderr)
        return result

    def run_json(self, args: list[str]) -> Any:
        result = self.run(args, json_output=True)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise SignalCliError(
                "signal-cli returnerede ikke gyldig JSON",
                result.returncode,
                result.stdout,
                result.stderr,
            ) from exc

    def list_groups(self) -> list[dict[str, Any]]:
        payload = self.run_json(["listGroups"])
        if not isinstance(payload, list):
            raise SignalCliError("listGroups returnerede et uventet JSON-format")
        return [item for item in payload if isinstance(item, dict)]


def group_id(group: dict[str, Any]) -> str | None:
    value = group.get("id") or group.get("groupId")
    return str(value) if value else None
