#!/usr/bin/env python3
"""Sync homeassistant version in requirements_dev.txt to hacs.json."""
import json
import re
from pathlib import Path


def main() -> int:
    root = Path(__file__).parent.parent

    with open(root / "hacs.json") as f:
        expected = json.load(f)["homeassistant"]

    req_path = root / "requirements_dev.txt"
    with open(req_path) as f:
        req_text = f.read()
    new_req = re.sub(r"^homeassistant==.+$", f"homeassistant=={expected}", req_text, flags=re.MULTILINE)
    if new_req != req_text:
        with open(req_path, "w") as f:
            f.write(new_req)
        print(f"Fixed requirements_dev.txt homeassistant -> {expected}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
