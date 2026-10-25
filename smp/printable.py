"""Makes print.pdf from a scan: white paper, black ink, no scan margins, fitted to A4.

    python -m smp.printable              # all scans
    python -m smp.printable scans/<id>   # one scan

page.pdf stays the unchanged source. print.pdf is derived from it and can be recreated
at any time; the result only depends on page.pdf and this code.
"""

import hashlib
import io
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image

from smp.ia import SCANS, rasterize, single_page

DPI = 300
A4_MM = (210.0, 297.0)
MARGIN_MM = 10.0


def clean(gray: np.ndarray) -> np.ndarray:
    """Removes uneven paper color and shadows, and returns black ink on white."""
    # Paper brightness, estimated with a closing that erases the thin ink strokes.
    # The kernel (about 6 mm) is larger than dense beam groups, so they stay ink.
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, np.ones((71, 71), np.uint8))
    background = cv2.GaussianBlur(background, (0, 0), 25)
    flat = cv2.divide(gray, background, scale=255)
    # Paper becomes white and ink black. The cut between them is chosen per page (Otsu);
    # faint staff lines are about 75% as bright as the paper, so it stays at 78% or below.
    otsu, _ = cv2.threshold(flat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    cut = min(otsu + 30, 200)
    low = 2 * cut - 255
    return np.clip((flat.astype(np.float32) - low) * (255 / (255 - low)), 0, 255).astype(np.uint8)


def dark_regions(gray: np.ndarray) -> np.ndarray:
    """Areas far darker than printed music: scan borders, holes, burns and large stains."""
    local = cv2.blur(gray, (151, 151))  # wider than any group of beams
    paper = np.percentile(gray, 90)  # most of a page is paper
    mask = (local < 0.45 * paper).astype(np.uint8)
    return cv2.dilate(mask, np.ones((25, 25), np.uint8)).astype(bool)


def remove_edge_marks(ink: np.ndarray) -> np.ndarray:
    """Whitens specks and ink along the image border: paper grain and sheet edges, not print."""
    h, w = ink.shape
    mask = (ink < 128).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    edge = np.zeros(count, bool)
    for i in range(1, count):
        x, y, bw, bh, _ = stats[i]
        touches = x <= 2 or y <= 2 or x + bw >= w - 2 or y + bh >= h - 2
        # Sheet edges are thin strips along the border; music touching the border is kept.
        strip = bw < 0.03 * w or bh < 0.03 * h
        in_band = x + bw < 0.05 * w or x > 0.95 * w or y + bh < 0.05 * h or y > 0.95 * h
        speck = stats[i][4] < 40  # paper grain; staccato dots are several times larger
        edge[i] = (touches and (strip or in_band)) or speck
    out = ink.copy()
    out[edge[labels]] = 255
    return out


def content_box(ink: np.ndarray) -> tuple[int, int, int, int]:
    """Bounding box of the printed content, without scan borders and specks."""
    h, w = ink.shape
    mask = (ink < 128).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    keep = np.zeros(count, bool)
    for i in range(1, count):
        x, y, bw, bh, area = stats[i]
        touches_edge = x <= 2 or y <= 2 or x + bw >= w - 2 or y + bh >= h - 2
        dense = area > 0.5 * bw * bh and bw * bh > 0.01 * w * h  # dark scan border or stain
        if touches_edge or dense or area < 12:
            continue
        keep[i] = True
    content = keep[labels]
    rows = np.flatnonzero(content.sum(axis=1) > 2)
    cols = np.flatnonzero(content.sum(axis=0) > 2)
    if len(rows) == 0 or len(cols) == 0:
        return 0, 0, w, h
    pad = DPI // 25  # 1 mm
    return (max(cols[0] - pad, 0), max(rows[0] - pad, 0),
            min(cols[-1] + pad, w), min(rows[-1] + pad, h))


def make(pdf: bytes) -> bytes:
    gray = np.asarray(rasterize(pdf, dpi=DPI).convert("L"))
    ink = clean(gray)
    ink[dark_regions(gray)] = 255
    ink = remove_edge_marks(ink)
    x0, y0, x1, y1 = content_box(ink)
    # Outside the content box nothing is printed; inside, specks and borders stay as they are.
    crop = ink[y0:y1, x0:x1]
    page_w = round((A4_MM[0] - 2 * MARGIN_MM) / 25.4 * DPI)
    page_h = round((A4_MM[1] - 2 * MARGIN_MM) / 25.4 * DPI)
    scale = min(page_w / crop.shape[1], page_h / crop.shape[0])
    size = (round(crop.shape[1] * scale), round(crop.shape[0] * scale))
    crop = cv2.resize(crop, size, interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
    sheet = np.full((round(A4_MM[1] / 25.4 * DPI), round(A4_MM[0] / 25.4 * DPI)), 255, np.uint8)
    top = round(MARGIN_MM / 25.4 * DPI)
    left = (sheet.shape[1] - size[0]) // 2
    sheet[top:top + size[1], left:left + size[0]] = crop
    out = io.BytesIO()
    Image.fromarray(sheet).convert("1", dither=Image.Dither.NONE).save(out, "PDF", resolution=DPI)
    return single_page(out.getvalue(), 0)  # drops the creation date, so output is reproducible


def update(folder: str) -> None:
    with open(os.path.join(folder, "page.pdf"), "rb") as f:
        printable = make(f.read())
    with open(os.path.join(folder, "print.pdf"), "wb") as f:
        f.write(printable)
    meta_file = os.path.join(folder, "meta.json")
    with open(meta_file, encoding="utf-8") as f:
        meta = json.load(f)
    meta["files"]["print.pdf"] = hashlib.sha256(printable).hexdigest()
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
        f.write("\n")


def main() -> None:
    folders = sys.argv[1:] or [os.path.join(SCANS, n) for n in sorted(os.listdir(SCANS))
                               if os.path.exists(os.path.join(SCANS, n, "page.pdf"))]
    for folder in folders:
        update(folder)
        print(folder)


if __name__ == "__main__":
    main()
