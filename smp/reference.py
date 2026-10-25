"""Creates a reference transcription for each scan with homr.

    python -m smp.reference --homr ~/projects/homr

The reference is homr's reading of the clean scan. It is not verified: scores against it
measure how much a photo changes the result, not whether the result is right. A corrected
reference becomes page.musicxml, and meta.json records it as verified.
"""

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from smp.ia import SCANS, rasterize

WORKERS = 3  # homr processes sharing the GPU


def _homr_version(homr: str) -> dict:
    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", homr, *args], capture_output=True, text=True,
                              check=True).stdout.strip()

    return {"commit": git("rev-parse", "HEAD"), "modified": bool(git("status", "--porcelain", "homr"))}


def _transcribe(homr: str, name: str, commit: str) -> str:
    """Runs homr on one page. Several images in one call would be merged into one score."""
    with tempfile.TemporaryDirectory(prefix="smp-homr-") as tmp:
        image = os.path.join(tmp, f"{name}.png")
        with open(os.path.join(SCANS, name, "page.pdf"), "rb") as f:
            rasterize(f.read()).save(image)  # 200 dpi grayscale, as for all references so far
        # Without VIRTUAL_ENV, Poetry uses homr's environment and not the caller's.
        env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
        began = time.time()
        result = subprocess.run(["poetry", "run", "homr", "--no-title", image], cwd=homr, env=env,
                                capture_output=True, text=True, check=False)
        output = image[:-4] + ".musicxml"
        meta_file = os.path.join(SCANS, name, "meta.json")
        with open(meta_file, encoding="utf-8") as f:
            meta = json.load(f)
        if result.returncode == 0 and os.path.exists(output):
            shutil.copy(output, os.path.join(SCANS, name, "reference.musicxml"))
            meta["reference"] = {"kind": "homr-unverified", "homr_commit": commit,
                                 "seconds": round(time.time() - began, 1)}
            status = "ok"
        else:
            meta["reference"] = {"kind": "missing", "homr_commit": commit,
                                 "error": result.stderr.strip()[-300:]}
            status = "failed"
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
            f.write("\n")
    return status


def run(homr: str, redo: bool, workers: int) -> None:
    version = _homr_version(homr)
    if version["modified"]:
        raise SystemExit("homr has local changes in homr/; references must come from a commit")
    todo = sorted(name for name in os.listdir(SCANS)
                  if os.path.isdir(os.path.join(SCANS, name))
                  and (redo or not os.path.exists(os.path.join(SCANS, name, "reference.musicxml"))))
    print(f"{len(todo)} scans to transcribe with homr {version['commit'][:10]}", flush=True)
    with ThreadPoolExecutor(workers) as pool:
        futures = {pool.submit(_transcribe, homr, name, version["commit"]): name for name in todo}
        for i, future in enumerate(as_completed(futures), start=1):
            print(f"[{i}/{len(todo)}] {futures[future]}: {future.result()}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--homr", required=True, help="path to a homr checkout")
    parser.add_argument("--redo", action="store_true", help="replace existing references")
    parser.add_argument("--workers", type=int, default=WORKERS)
    args = parser.parse_args()
    run(os.path.expanduser(args.homr), args.redo, args.workers)


if __name__ == "__main__":
    main()
