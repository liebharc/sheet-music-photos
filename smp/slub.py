"""Real scans of printed sheet music from SLUB Dresden (sachsen.digital).

    python -m smp.slub search               # freeze the candidate list in sources/slub-candidates.json
    python -m smp.slub add --count 10       # add the next 10 scans in the fixed order
    python -m smp.slub reproduce            # download again and compare every page.pdf

The Saxon State and University Library Dresden states a license for each digitized item
in its METS/MODS record. Only items marked with the Public Domain Mark or CC0, with a
publisher (a printed edition) and published in 1929 or earlier are used. The page image
is SLUB's original JPEG, without the banner SLUB adds to its PDF downloads; page.pdf
embeds it unchanged.
"""

import argparse
import datetime
import hashlib
import html
import io
import json
import os
import random
import re
import urllib.parse
from xml.etree import ElementTree as ET

from PIL import Image

from smp.ia import LICENSES, ROOT, SCANS, _get, rasterize, staff_count

CANDIDATES = os.path.join(ROOT, "sources", "slub-candidates.json")
SITE = "https://sachsen.digital"
OAI = "https://digital.slub-dresden.de/oai/"
# Searches in SLUB's collection "Musik"; their results together are the candidates.
QUERIES = ["Lieder", "Volkslieder", "Kinderlieder", "Weihnachtslieder", "Choralbuch", "Gesangbuch",
           "Klavier", "Walzer", "Marsch", "Männerchor", "Tänze"]
MAX_YEAR = 1929
MAX_PAGES_TRIED = 40  # pages looked at per item before it is skipped
NS = {"mets": "http://www.loc.gov/METS/", "mods": "http://www.loc.gov/mods/v3",
      "xlink": "http://www.w3.org/1999/xlink"}


def _text(data: bytes) -> str:
    return data.decode("utf-8", "replace")


def _results(query: str) -> dict[str, str]:
    """Works found by `query` in the collection Musik, as {werk number: title}, all result pages."""
    url = f"{SITE}/suche?" + urllib.parse.urlencode({
        "tx_find_find[q][default]": query, "tx_find_find[searchMode]": "metadata",
        "tx_find_find[controller]": "Search", "tx_find_find[action]": "index"})
    page = _text(_get(url))
    facet = re.search(r'href="(/suche\?[^"]*facet%5D%5Bcollection%5D%5BMusik%5D=1[^"]*)"', page)
    if not facet:
        return {}
    found: dict[str, str] = {}
    url, number = SITE + html.unescape(facet.group(1)), 1
    while url:
        page = _text(_get(url))
        for werk, title in re.findall(
                r'<a href="/werk/(\d+)/1\?[^"]*">\s*<dt class="tx-dlf-title">[^<]*</dt>\s*'
                r'<dd class="tx-dlf-title">\s*(.*?)\s*</dd>', page, re.S):
            found.setdefault(werk, html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", title))))
        for werk in re.findall(r'href="/werk/(\d+)/1\?', page):
            found.setdefault(werk, "")
        number += 1
        following = re.search(r'href="(/suche\?[^"]*tx_find_find%5Bpage%5D=' + str(number) + r'&[^"]*)"', page)
        url = SITE + html.unescape(following.group(1)) if following else None
    return found


def search() -> None:
    werke: dict[str, dict] = {}
    for query in QUERIES:
        found = _results(query)
        print(f"{query}: {len(found)}", flush=True)
        for werk, title in found.items():
            werke.setdefault(werk, {"werk": werk, "title": title, "query": query})
    candidates = []
    for werk, entry in sorted(werke.items(), key=lambda w: int(w[0])):
        page = _text(_get(f"{SITE}/werk/{werk}/1"))
        record = re.search(r"identifier=(oai:de:slub-dresden:db:id-[0-9X]+)", html.unescape(page))
        if record:  # works without a METS record are left out
            candidates.append({"record": record.group(1), **entry})
    os.makedirs(os.path.dirname(CANDIDATES), exist_ok=True)
    with open(CANDIDATES, "w", encoding="utf-8") as f:
        json.dump({"searched": datetime.date.today().isoformat(), "site": SITE, "collection": "Musik",
                   "queries": QUERIES, "candidates": candidates}, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"{len(candidates)} candidates")


def _mets(record: str) -> ET.Element:
    data = _get(OAI, {"verb": "GetRecord", "metadataPrefix": "mets", "identifier": record})
    return ET.fromstring(data).find(".//mets:mets", NS)


def _description(mets: ET.Element) -> dict:
    """The record's own MODS: the first dmdSec, which describes the whole item."""
    mods = mets.find(".//mets:dmdSec//mods:mods", NS)

    def first(path: str) -> str:
        node = mods.find(path, NS)
        return re.sub(r"\s+", " ", node.text or "").strip() if node is not None else ""

    names = []
    for name in mods.findall("mods:name[@type='personal']", NS):
        parts = {p.get("type"): p.text or "" for p in name.findall("mods:namePart", NS)}
        names.append(", ".join(v for v in (parts.get("family"), parts.get("given")) if v))
    license_node = mods.find("mods:accessCondition[@type='use and reproduction']", NS)
    license_url = license_node.get(f"{{{NS['xlink']}}}href", "") if license_node is not None else ""
    title = first("mods:titleInfo/mods:title")
    if first("mods:titleInfo/mods:subTitle"):
        title += " : " + first("mods:titleInfo/mods:subTitle")
    # A volume of a multi-volume work names only the volume ("Iter Band") or nothing.
    work = mets.find(".//mets:structMap[@TYPE='LOGICAL']/mets:div[@TYPE='multivolume_work']", NS)
    if work is not None and work.get("LABEL"):
        title = work.get("LABEL") + (" : " + title if title else "")
    return {"title": title, "creator": "; ".join(n for n in names if n),
            "date": first("mods:originInfo/mods:dateIssued"),
            "publisher": first("mods:originInfo/mods:publisher"),
            "place": first("mods:originInfo/mods:place/mods:placeTerm"),
            "license_url": license_url,
            "license": next((n for k, n in LICENSES.items() if k in license_url), None)}


def _page_images(mets: ET.Element) -> list[str]:
    """URLs of the original JPEGs, in the order of the physical pages."""
    files = {f.get("ID"): f.find("mets:FLocat", NS).get(f"{{{NS['xlink']}}}href")
             for f in mets.findall(".//mets:fileGrp[@USE='ORIGINAL']/mets:file", NS)}
    pages = mets.findall(".//mets:structMap[@TYPE='PHYSICAL']//mets:div[@TYPE='page']", NS)
    pages.sort(key=lambda d: int(d.get("ORDER", 0)))
    urls = []
    for page in pages:
        url = next((files[p.get("FILEID")] for p in page.findall("mets:fptr", NS) if p.get("FILEID") in files),
                   None)
        if url:
            urls.append(url)
    return urls


def jpeg_pdf(jpeg: bytes) -> bytes:
    """A one-page PDF that holds `jpeg` unchanged, sized by its resolution (300 dpi if unknown)."""
    with Image.open(io.BytesIO(jpeg)) as im:
        if im.format != "JPEG":
            raise RuntimeError(f"page image is {im.format}, not JPEG")
        colors = {"L": "/DeviceGray", "RGB": "/DeviceRGB"}.get(im.mode)
        if colors is None:
            raise RuntimeError(f"page image has mode {im.mode}")
        width, height = im.size
        dpi = im.info.get("dpi", (300, 300))[0] or 300
    w, h = round(width * 72 / dpi, 2), round(height * 72 / dpi, 2)
    content = f"q {w} 0 0 {h} 0 0 cm /Im0 Do Q".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w} {h}] "
        f"/Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>".encode(),
        f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} /ColorSpace {colors} "
        f"/BitsPerComponent 8 /Filter /DCTDecode /Length {len(jpeg)} >>\nstream\n".encode()
        + jpeg + b"\nendstream",
        f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def _year(date: str) -> int | None:
    years = re.findall(r"1[5-9]\d\d|20\d\d", date)
    return max(int(y) for y in years) if years else None


def add_scan(candidate: dict, seed: int) -> dict:
    record = candidate["record"]
    mets = _mets(record)
    info = _description(mets)
    if not info["license"]:
        raise RuntimeError(f"no Public Domain Mark or CC0 on the item ({info['license_url'] or 'none'})")
    year = _year(info["date"])
    if year is None or year > MAX_YEAR:
        raise RuntimeError(f"published {info['date'] or 'in an unknown year'}")
    if not info["publisher"]:
        raise RuntimeError("no publisher, possibly a manuscript")
    images = _page_images(mets)
    if not images:
        raise RuntimeError("no page images")
    order = list(range(len(images)))
    random.Random(f"{seed}:{record}").shuffle(order)
    for index in order[:MAX_PAGES_TRIED]:
        jpeg = _get(images[index])
        page_pdf = jpeg_pdf(jpeg)
        staves = staff_count(rasterize(page_pdf))
        if staves >= 3:
            break
    else:
        raise RuntimeError("no page with at least three staves")
    ppn = record.rsplit("id-", 1)[1]
    slug = re.sub(r"[^a-z0-9]+", "-", info["title"].lower().replace("ä", "ae").replace("ö", "oe")
                  .replace("ü", "ue").replace("ß", "ss")).strip("-")[:40].strip("-")
    scan_id = f"slub-{ppn.lower()}-{slug}-p{index + 1}"
    folder = os.path.join(SCANS, scan_id)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "page.pdf"), "wb") as f:
        f.write(page_pdf)
    meta = {
        "id": scan_id,
        "source": {
            "collection": "SLUB Dresden", "record": record,
            "url": f"https://digital.slub-dresden.de/id{ppn}",
            "file": images[index], "file_sha256": hashlib.sha256(jpeg).hexdigest(),
            "page": index + 1, "page_count": len(images), "title": info["title"],
            "creator": info["creator"], "date": info["date"], "publisher": info["publisher"],
            "place": info["place"], "license": info["license"], "license_url": info["license_url"],
        },
        "detected_staves": staves,
        "files": {"page.pdf": hashlib.sha256(page_pdf).hexdigest()},
    }
    with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
        f.write("\n")
    from smp.printable import update  # imported here: printable imports smp.ia
    update(folder)
    return meta


def add(count: int, seed: int) -> None:
    with open(CANDIDATES, encoding="utf-8") as f:
        candidates = json.load(f)["candidates"]
    random.Random(f"{seed}:slub").shuffle(candidates)
    done_file = os.path.join(SCANS, "attempted.json")
    with open(done_file, encoding="utf-8") as f:
        attempted: dict[str, str] = json.load(f)
    added = 0
    for candidate in candidates:
        if added >= count:
            break
        key = f"slub:{candidate['record']}"
        if key in attempted:
            continue
        try:
            meta = add_scan(candidate, seed)
            attempted[key] = meta["id"]
            added += 1
            print(f"[{added}/{count}] {meta['id']} ({meta['source']['date']})", flush=True)
        except Exception as e:  # noqa: BLE001 - a candidate that does not work is skipped
            attempted[key] = f"skipped: {e}"
            print(f"skipped {candidate['record']} {candidate['title'][:50]}: {e}", flush=True)
        with open(done_file, "w", encoding="utf-8") as f:
            json.dump(attempted, f, indent=1, sort_keys=True)
            f.write("\n")


def reproduce() -> int:
    """Downloads every SLUB page image again and checks that page.pdf comes out the same."""
    differ = 0
    for name in sorted(os.listdir(SCANS)):
        meta_file = os.path.join(SCANS, name, "meta.json")
        if not os.path.exists(meta_file):
            continue
        with open(meta_file, encoding="utf-8") as f:
            meta = json.load(f)
        source = meta["source"]
        if source.get("collection") != "SLUB Dresden":
            continue
        jpeg = _get(source["file"])
        if hashlib.sha256(jpeg).hexdigest() != source["file_sha256"]:
            status = "page image changed at SLUB"
        elif hashlib.sha256(jpeg_pdf(jpeg)).hexdigest() != meta["files"]["page.pdf"]:
            status = "page.pdf differs"
        else:
            status = "ok"
        differ += status != "ok"
        print(f"{name}: {status}", flush=True)
    print(f"{differ} SLUB scans differ")
    return differ


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["search", "add", "reproduce"])
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    if args.command == "search":
        search()
    elif args.command == "reproduce":
        if reproduce():
            raise SystemExit(1)
    else:
        add(args.count, args.seed)


if __name__ == "__main__":
    main()
