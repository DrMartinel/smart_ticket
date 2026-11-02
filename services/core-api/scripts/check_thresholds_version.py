"""Fails when config/thresholds.yaml changed against a base ref but its `version` didn't (F9,
FR-F9-010): an approved change request ships with its id as the version.

    python services/core-api/scripts/check_thresholds_version.py origin/main
"""

from __future__ import annotations

import subprocess
import sys

import yaml

PATH = "services/core-api/config/thresholds.yaml"


def version_of(text: str) -> str:
    return str((yaml.safe_load(text) or {}).get("version"))


def main(base: str) -> int:
    try:
        before = subprocess.run(
            ["git", "show", f"{base}:{PATH}"], capture_output=True, text=True, check=True
        ).stdout
    except subprocess.CalledProcessError:
        print(f"{PATH} is new against {base}; nothing to compare")
        return 0
    with open(PATH, encoding="utf-8") as f:
        after = f.read()
    if before == after:
        print(f"{PATH} unchanged")
        return 0
    if version_of(before) == version_of(after):
        print(
            f"{PATH} changed but its version is still {version_of(after)!r}: "
            "set it to the approved change request's id (CR-YYYY-NNN)"
        )
        return 1
    print(f"{PATH}: version {version_of(before)!r} -> {version_of(after)!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "origin/main"))
