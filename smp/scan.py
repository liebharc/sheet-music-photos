"""Adds a clean scan that you contribute, as a new page to photograph.

    python -m smp.scan scan.pdf --page 2 --title "Song title" --by "Your name" \
        --source "Scanned from my copy, printed 1912 by ..." --license CC0-1.0 --confirm

The page is cut out of the PDF unchanged and stored with its metadata. Then create a
reference with `make references`, or add a verified page.musicxml.
"""

import argparse
import hashlib
import json
import os
import re

from smp.ia import LICENSES, SCANS, rasterize, single_page, staff_count
from smp.printable import update

CONFIRMATION = (
    "I confirm that this metadata is correct; that the page is a real scan of a printed "
    "edition published in 1929 or earlier, not rendered or generated; that I may share it "
    "under the license stated; and that any transcription I add was checked by me against "
    "the page and is dedicated under CC0 1.0.")


def add(pdf_path: str, page: int, title: str, by: str, source: str, url: str, published: str,
        license_name: str) -> str:
    with open(pdf_path, "rb") as f:
        page_pdf = single_page(f.read(), page - 1)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50]
    scan_id = f"own-{slug}-p{page}"
    folder = os.path.join(SCANS, scan_id)
    if os.path.exists(folder):
        raise SystemExit(f"{folder} exists already")
    os.makedirs(folder)
    with open(os.path.join(folder, "page.pdf"), "wb") as f:
        f.write(page_pdf)
    image = rasterize(page_pdf)
    meta = {
        "id": scan_id,
        "source": {"collection": "contributed", "title": title, "published": published,
                   "source": source, "url": url, "page": page, "contributor": by,
                   "license": license_name},
        "confirmation": {"by": by, "statement": CONFIRMATION},
        "detected_staves": staff_count(image),
        "files": {"page.pdf": hashlib.sha256(page_pdf).hexdigest()},
    }
    with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
        f.write("\n")
    update(folder)
    return folder


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdf")
    parser.add_argument("--page", type=int, default=1, help="page number in the PDF, from 1")
    parser.add_argument("--title", required=True)
    parser.add_argument("--by", required=True, help="your name or handle")
    parser.add_argument("--source", required=True,
                        help="where the scan comes from: your own copy (edition, year) or an archive")
    parser.add_argument("--url", default="", help="record of the scan in an archive, if any")
    parser.add_argument("--published", required=True, help="year the printed edition was published")
    parser.add_argument("--license", required=True, choices=sorted(LICENSES.values()))
    parser.add_argument("--confirm", action="store_true", help=f"agree to: {CONFIRMATION}")
    args = parser.parse_args()
    if not args.confirm:
        raise SystemExit(f"Adding a scan needs --confirm, which records this statement:\n{CONFIRMATION}")
    print(add(args.pdf, args.page, args.title, args.by, args.source, args.url, args.published,
              args.license))


if __name__ == "__main__":
    main()
