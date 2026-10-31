"""Finds scans whose homr reference is wrong on a large scale, and replaces them.

    python -m smp.quality            # list scans with large-scale problems
    python -m smp.quality --drop     # remove them; `make scans` then adds replacements

A dropped scan stays in scans/attempted.json with the reason, so the fixed order of
candidates is kept and the scan can be added again once its reference is corrected.
"""

import argparse
import json
import os
import shutil
from xml.etree import ElementTree as ET

from smp.ia import SCANS

MAX_CLEF_CHANGES = 2  # within a one-staff part; band parts print the clef on the first line only


def problems(reference: str) -> list[str]:
    found = []
    root = ET.parse(reference).getroot()
    for index, part in enumerate(root.iter("part"), start=1):
        staves = max((int(s.text) for s in part.iter("staves")), default=1)
        if staves > 1:
            continue
        clefs = [c.findtext("sign", "") + c.findtext("line", "") for c in part.iter("clef")]
        changes = sum(1 for a, b in zip(clefs, clefs[1:]) if a != b)
        if changes > MAX_CLEF_CHANGES:
            found.append(f"part {index} changes clef {changes} times")
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--drop", action="store_true", help="remove the scans with problems")
    args = parser.parse_args()
    attempted_file = os.path.join(SCANS, "attempted.json")
    with open(attempted_file, encoding="utf-8") as f:
        attempted = json.load(f)
    flagged = 0
    for name in sorted(os.listdir(SCANS)):
        reference = os.path.join(SCANS, name, "reference.musicxml")
        if not os.path.exists(reference):
            continue
        found = problems(reference)
        if not found:
            continue
        flagged += 1
        print(f"{name}: {'; '.join(found)}")
        with open(os.path.join(SCANS, name, "meta.json"), encoding="utf-8") as f:
            source = json.load(f)["source"]
        identifier = source.get("identifier") or (f"slub:{source['record']}" if "record" in source else None)
        if args.drop and identifier is None:
            print(f"  {name} is a contributed scan; its reference needs correcting, it is kept")
        elif args.drop:
            attempted[identifier] = f"dropped {name}: homr reference {'; '.join(found)}"
            shutil.rmtree(os.path.join(SCANS, name))
    if args.drop:
        with open(attempted_file, "w", encoding="utf-8") as f:
            json.dump(attempted, f, indent=1, sort_keys=True)
            f.write("\n")
    print(f"{flagged} scans with problems" + (", dropped" if args.drop else ""))


if __name__ == "__main__":
    main()
