"""Checks every scan: hashes, licenses, and contributed photos.

    python -m smp.check
"""

import hashlib
import json
import os

from PIL import Image

from smp.ia import LICENSES as SCAN_LICENSES
from smp.ia import ROOT
from smp.photos import MAX_SIDE
from smp.scan import CONFIRMATION

FOLDERS = {"scans": set(SCAN_LICENSES.values())}


def _sha256(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def check_item(folder: str, licenses: set[str]) -> list[str]:
    problems = []
    with open(os.path.join(folder, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    if meta["source"]["license"] not in licenses:
        problems.append(f"license {meta['source']['license']} is not allowed")
    if meta["source"].get("collection") == "contributed":
        confirmation = meta.get("confirmation", {})
        if confirmation.get("statement") != CONFIRMATION or not confirmation.get("by"):
            problems.append("contributed scan without the contributor's confirmation (add it with smp.scan --confirm)")
    for name, digest in meta["files"].items():
        path = os.path.join(folder, name)
        if not os.path.exists(path):
            problems.append(f"{name} is missing")
        elif _sha256(path) != digest:
            problems.append(f"{name} does not match its SHA-256 in meta.json")
    photos = os.path.join(folder, "photos")
    if os.path.isdir(photos):
        index_file = os.path.join(photos, "photos.json")
        listed = {}
        if os.path.exists(index_file):
            with open(index_file, encoding="utf-8") as f:
                listed = {p["file"]: p for p in json.load(f)["photos"]}
        for name in sorted(os.listdir(photos)):
            if name == "photos.json":
                continue
            path = os.path.join(photos, name)
            entry = listed.get(name)
            if entry is None:
                problems.append(f"photos/{name} is not in photos.json (add photos with smp.photos)")
                continue
            if entry.get("license") != "CC0-1.0" or not entry.get("contributor"):
                problems.append(f"photos/{name} lacks a contributor or the CC0 dedication")
            if _sha256(path) != entry.get("sha256"):
                problems.append(f"photos/{name} does not match its SHA-256 in photos.json")
            with Image.open(path) as im:
                if im.getexif() or "exif" in im.info:
                    problems.append(f"photos/{name} still has EXIF metadata")
                if max(im.size) > MAX_SIDE:
                    problems.append(f"photos/{name} is larger than {MAX_SIDE} px")
        for name in listed:
            if not os.path.exists(os.path.join(photos, name)):
                problems.append(f"photos.json lists the missing photos/{name}")
    return problems


def main() -> None:
    checked = failed = 0
    for top, licenses in FOLDERS.items():
        root = os.path.join(ROOT, top)
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            folder = os.path.join(root, name)
            if not os.path.exists(os.path.join(folder, "meta.json")):
                continue
            problems = check_item(folder, licenses)
            for problem in problems:
                print(f"{top}/{name}: {problem}")
            checked += 1
            failed += bool(problems)
    print(f"{checked} pages checked, {failed} with problems")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
