"""Adds photos of a printed page to its folder.

    python -m smp.photos scans/<id> --by "Your Name or handle" photo1.jpg photo2.jpg ...

Each photo is re-encoded without metadata (EXIF holds GPS position and device serial
numbers), oriented upright, limited to 1920 px on the longer side, and saved as photos/<n>.jpg. The
contributor and their CC0 dedication are recorded in photos/photos.json.
"""

import argparse
import hashlib
import json
import os

from PIL import Image, ImageOps

MAX_SIDE = 1920  # the longer side; homr works at 1920 px width, testdata photos are 1920x1440
DEDICATION = ("I took these photos myself and dedicate my rights in them to the public domain "
              "under CC0 1.0 (https://creativecommons.org/publicdomain/zero/1.0/).")
CONDITIONS = ["flat", "stand", "curved", "folded", "crumpled", "tilted", "shadow", "dim", "glare",
              "background", "neighbor", "annotated", "other"]


def add(item: str, files: list[str], contributor: str, conditions: list[str]) -> list[str]:
    folder = os.path.join(item, "photos")
    os.makedirs(folder, exist_ok=True)
    index_file = os.path.join(folder, "photos.json")
    index = {"photos": []}
    if os.path.exists(index_file):
        with open(index_file, encoding="utf-8") as f:
            index = json.load(f)
    added = []
    for path in files:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((MAX_SIDE, MAX_SIDE))
            name = f"{len(index['photos']) + 1:02d}.jpg"
            target = os.path.join(folder, name)
            im.save(target, "JPEG", quality=90, optimize=True)  # no exif= argument: metadata is dropped
        with open(target, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        index["photos"].append({"file": name, "sha256": digest, "contributor": contributor,
                                "conditions": conditions, "license": "CC0-1.0",
                                "dedication": DEDICATION})
        added.append(target)
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return added


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("item", help="page folder, e.g. scans/ia-b88454551-p5")
    parser.add_argument("photos", nargs="+")
    parser.add_argument("--by", required=True, help="name or handle to credit")
    parser.add_argument("--conditions", nargs="*", default=[], choices=CONDITIONS,
                        help="what the photos show, e.g. curved shadow")
    args = parser.parse_args()
    if not os.path.exists(os.path.join(args.item, "page.pdf")):
        raise SystemExit(f"{args.item} is not a page folder")
    print(DEDICATION)
    for target in add(args.item, args.photos, args.by, args.conditions):
        print(f"added {target}")


if __name__ == "__main__":
    main()
