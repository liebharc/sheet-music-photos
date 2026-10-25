"""Real scans of printed sheet music from the Internet Archive.

    python -m smp.ia search                 # freeze the candidate list in sources/ia-candidates.json
    python -m smp.ia add --count 10         # add the next 10 scans in the fixed order
    python -m smp.ia reproduce              # download again and compare every page.pdf

Only institutional collections whose items carry the Public Domain Mark or CC0 and were
published in 1929 or earlier are used. The order of candidates is fixed by the seed and
alternates between collections, so adding more scans later continues the same sequence.
"""

import argparse
import datetime
import hashlib
import io
import json
import os
import random
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request

import numpy as np
from PIL import Image
from pypdf import PdfReader, PdfWriter


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER_AGENT = "sheet-music-photos/0.1 (sheet music dataset; https://github.com/)"
CANDIDATES = os.path.join(ROOT, "sources", "ia-candidates.json")
SCANS = os.path.join(ROOT, "scans")
# Libraries and archives; community uploads are left out because their license claims
# are not checked by an institution.
COLLECTIONS = ["gaylordmusiclibrary", "uno-sheet-music", "uclamusiclibrary", "canadiansheetmusic",
               "uoftsheetmusic", "bostonpubliclibrary", "smithsonian", "newberry", "conncollsheetmusic"]
LICENSES = {"publicdomain/mark/1.0": "PDM-1.0", "publicdomain/zero/1.0": "CC0-1.0"}
QUERY = ('mediatype:texts AND date:[1800-01-01 TO 1929-12-31] AND licenseurl:*publicdomain* AND '
         '(subject:"sheet music" OR subject:"piano music" OR subject:"songs with piano" OR '
         'subject:"violin music" OR subject:"popular music" OR subject:"marches" OR subject:"music")')
MAX_PDF_BYTES = 150_000_000


def single_page(pdf: bytes, index: int) -> bytes:
    """One page of `pdf`, without links, document info or IDs, so that output is reproducible."""
    writer = PdfWriter()
    page = writer.add_page(PdfReader(io.BytesIO(pdf)).pages[index])
    if "/Annots" in page:
        del page["/Annots"]
    writer._info = None  # no producer or creation date
    writer._ID = None
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _get(url: str, params: dict | None = None) -> bytes:
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
        except OSError:
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))
    raise AssertionError


def _license(url: str) -> str | None:
    url = url.replace(" ", "")
    return next((name for key, name in LICENSES.items() if key in url), None)


def search() -> None:
    docs = json.loads(_get("https://archive.org/advancedsearch.php", {
        "q": QUERY, "fl[]": ["identifier", "collection", "licenseurl", "date", "title"],
        "rows": 20000, "output": "json"}))["response"]["docs"]
    candidates = []
    for d in docs:
        collections = d.get("collection", [])
        collections = [collections] if isinstance(collections, str) else collections
        collection = next((c for c in collections if c in COLLECTIONS), None)
        license_name = _license(str(d.get("licenseurl", "")))
        if collection and license_name:
            candidates.append({"identifier": d["identifier"], "collection": collection,
                               "license": license_name, "date": str(d.get("date", ""))[:10],
                               "title": str(d.get("title", ""))[:200]})
    candidates.sort(key=lambda c: c["identifier"])
    os.makedirs(os.path.dirname(CANDIDATES), exist_ok=True)
    with open(CANDIDATES, "w", encoding="utf-8") as f:
        json.dump({"searched": datetime.date.today().isoformat(), "query": QUERY,
                   "collections": COLLECTIONS, "candidates": candidates}, f, indent=1, ensure_ascii=False)
        f.write("\n")
    by_collection: dict[str, int] = {}
    for c in candidates:
        by_collection[c["collection"]] = by_collection.get(c["collection"], 0) + 1
    print(f"{len(candidates)} candidates: {by_collection}")


def ordered(candidates: list[dict], seed: int) -> list[dict]:
    """Candidates shuffled within each collection, then taken from the collections in turn."""
    groups: dict[str, list[dict]] = {}
    for c in candidates:
        groups.setdefault(c["collection"], []).append(c)
    for name, group in groups.items():
        random.Random(f"{seed}:{name}").shuffle(group)
    result = []
    while any(groups.values()):
        for name in sorted(groups):
            if groups[name]:
                result.append(groups[name].pop(0))
    return result


def rasterize(pdf: bytes, dpi: int = 200) -> Image.Image:
    with tempfile.TemporaryDirectory(prefix="smp-gs-") as tmp:
        src, out = os.path.join(tmp, "page.pdf"), os.path.join(tmp, "page.png")
        with open(src, "wb") as f:
            f.write(pdf)
        # Library PDFs often hold the whole scanned sheet and mark the page with a crop box.
        subprocess.run(["gs", "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER", "-dUseCropBox",
                        "-sDEVICE=pnggray", f"-r{dpi}", "-o", out, src], check=True, capture_output=True)
        return Image.open(out).copy()


def staff_count(image: Image.Image) -> int:
    """Rough number of five-line staves: groups of five long, evenly spaced dark rows."""
    gray = np.asarray(image.convert("L"), dtype=np.float32)
    dark = gray < min(160, gray.mean() - 40)
    rows = np.flatnonzero(dark.mean(axis=1) > 0.35)
    lines = []
    for r in rows:  # merge thick lines
        if lines and r - lines[-1][-1] <= 2:
            lines[-1].append(r)
        else:
            lines.append([r])
    centers = [sum(line) / len(line) for line in lines]
    staves, i = 0, 0
    while i + 4 < len(centers):
        gaps = np.diff(centers[i:i + 5])
        if gaps.min() > 3 and gaps.max() < 1.4 * gaps.min():
            staves += 1
            i += 5
        else:
            i += 1
    return staves


def _pdf_file(metadata: dict) -> dict | None:
    pdfs = [f for f in metadata["files"] if f["name"].lower().endswith(".pdf") and "sha1" in f
            and int(f.get("size", 0)) <= MAX_PDF_BYTES]
    # Prefer the original scan PDF over derived ones.
    pdfs.sort(key=lambda f: (f.get("source") != "original", "Text PDF" in f.get("format", "")))
    return pdfs[0] if pdfs else None


def add_scan(candidate: dict, seed: int) -> dict:
    identifier = candidate["identifier"]
    metadata = json.loads(_get(f"https://archive.org/metadata/{identifier}"))
    meta = metadata["metadata"]
    license_name = _license(str(meta.get("licenseurl", "")))
    if not license_name:
        raise RuntimeError("no Public Domain Mark or CC0 on the item")
    pdf_file = _pdf_file(metadata)
    if pdf_file is None:
        raise RuntimeError("no PDF")
    pdf = _get(f"https://archive.org/download/{identifier}/{urllib.parse.quote(pdf_file['name'])}")
    if hashlib.sha1(pdf).hexdigest() != pdf_file["sha1"]:
        raise RuntimeError("PDF does not match the SHA-1 the Internet Archive lists")
    pages = list(range(len(PdfReader(io.BytesIO(pdf)).pages)))
    random.Random(f"{seed}:{identifier}").shuffle(pages)
    for page in pages:
        page_pdf = single_page(pdf, page)
        image = rasterize(page_pdf)
        staves = staff_count(image)
        if staves >= 3:
            break
    else:
        raise RuntimeError("no page with at least three staves")
    scan_id = f"ia-{identifier}-p{page + 1}"
    folder = os.path.join(SCANS, scan_id)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "page.pdf"), "wb") as f:
        f.write(page_pdf)

    def field(name: str) -> str:
        value = meta.get(name, "")
        return "; ".join(value) if isinstance(value, list) else str(value)

    info = {
        "id": scan_id,
        "source": {
            "collection": "Internet Archive", "ia_collection": candidate["collection"],
            "identifier": identifier, "url": f"https://archive.org/details/{identifier}",
            "file": pdf_file["name"], "file_sha1": pdf_file["sha1"], "page": page + 1,
            "page_count": len(pages), "title": field("title"), "creator": field("creator"),
            "date": field("date"), "publisher": field("publisher"),
            "contributor": field("contributor"), "license": license_name,
            "license_url": field("licenseurl"),
        },
        "detected_staves": staves,
        "files": {"page.pdf": hashlib.sha256(page_pdf).hexdigest()},
    }
    with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2, ensure_ascii=False)
        f.write("\n")
    from smp.printable import update  # imported here: printable imports this module
    update(folder)
    return info


def add(count: int, seed: int) -> None:
    with open(CANDIDATES, encoding="utf-8") as f:
        candidates = json.load(f)["candidates"]
    done_file = os.path.join(SCANS, "attempted.json")
    attempted: dict[str, str] = {}
    if os.path.exists(done_file):
        with open(done_file, encoding="utf-8") as f:
            attempted = json.load(f)
    added = 0
    for candidate in ordered(candidates, seed):
        if added >= count:
            break
        if candidate["identifier"] in attempted:
            continue
        try:
            info = add_scan(candidate, seed)
            attempted[candidate["identifier"]] = info["id"]
            added += 1
            print(f"[{added}/{count}] {info['id']} ({candidate['collection']}, {info['source']['date']})",
                  flush=True)
        except Exception as e:  # noqa: BLE001 - a candidate that does not work is skipped
            attempted[candidate["identifier"]] = f"skipped: {e}"
            print(f"skipped {candidate['identifier']}: {e}", flush=True)
        os.makedirs(SCANS, exist_ok=True)
        with open(done_file, "w", encoding="utf-8") as f:
            json.dump(attempted, f, indent=1, sort_keys=True)
            f.write("\n")


def reproduce() -> None:
    """Downloads every scan's source PDF again and checks that page.pdf comes out the same."""
    differ = 0
    for name in sorted(os.listdir(SCANS)):
        meta_file = os.path.join(SCANS, name, "meta.json")
        if not os.path.exists(meta_file):
            continue
        with open(meta_file, encoding="utf-8") as f:
            meta = json.load(f)
        source = meta["source"]
        if source.get("collection") != "Internet Archive":
            continue  # contributed scans have no public source to download
        pdf = _get(f"https://archive.org/download/{source['identifier']}/{urllib.parse.quote(source['file'])}")
        if hashlib.sha1(pdf).hexdigest() != source["file_sha1"]:
            status = "source PDF changed on the Internet Archive"
        elif hashlib.sha256(single_page(pdf, source["page"] - 1)).hexdigest() != meta["files"]["page.pdf"]:
            status = "page.pdf differs"
        else:
            status = "ok"
        differ += status != "ok"
        print(f"{name}: {status}", flush=True)
    print(f"{differ} scans differ")
    if differ:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["search", "add", "reproduce"])
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    if args.command == "search":
        search()
    elif args.command == "reproduce":
        reproduce()
    else:
        add(args.count, args.seed)


if __name__ == "__main__":
    main()
