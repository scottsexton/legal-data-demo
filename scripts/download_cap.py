"""Download the CAP demo slice locally, then (optionally) upload it to the Unity Catalog Volume.

Usage:
    uv run python scripts/download_cap.py                     # download only, to data/cap
    uv run python scripts/download_cap.py --upload            # download, then upload
    uv run python scripts/download_cap.py --upload-only       # upload what's already in data/cap
    uv run python scripts/download_cap.py --max-cases 50      # small test run

Default slice: Indiana Supreme Court opinions of at least 5,000 characters (this skips one-line
"Transfer denied" orders) in N.E.3d, newest volume (130) first, capped at 500 cases.
Re-running skips files already downloaded.
"""

from __future__ import annotations

import argparse
import io
import json
from datetime import date
from pathlib import Path

from legal_demo.cap import DEFAULT_COURT, DEFAULT_MIN_CHARS, DEFAULT_REPORTER, download_cases

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VOLUME_PATH = "/Volumes/legal_demo/raw/cap"


def upload_dir(local_dir: Path, volume_path: str) -> int:
    """Upload every file under local_dir to volume_path, keeping relative paths."""
    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient()
    files = sorted(p for p in local_dir.rglob("*") if p.is_file())
    for i, path in enumerate(files, 1):
        target = f"{volume_path}/{path.relative_to(local_dir).as_posix()}"
        w.files.upload(target, io.BytesIO(path.read_bytes()), overwrite=True)
        if i % 100 == 0 or i == len(files):
            print(f"uploaded {i}/{len(files)}")
    return len(files)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--reporter", default=DEFAULT_REPORTER)
    p.add_argument("--court", default=DEFAULT_COURT)
    p.add_argument("--min-chars", type=int, default=DEFAULT_MIN_CHARS, help="skip short orders")
    p.add_argument("--start-vol", type=int, default=130, help="first (newest) volume to check")
    p.add_argument("--end-vol", type=int, default=1, help="last (oldest) volume to check")
    p.add_argument("--max-cases", type=int, default=500)
    p.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "cap")
    p.add_argument("--upload", action="store_true", help="upload to the UC Volume afterwards")
    p.add_argument("--upload-only", action="store_true", help="skip downloading; just upload")
    p.add_argument("--volume-path", default=DEFAULT_VOLUME_PATH)
    args = p.parse_args()

    if args.upload_only:
        n = upload_dir(args.out, args.volume_path)
        print(f"uploaded {n} files to {args.volume_path}")
        return

    step = -1 if args.start_vol >= args.end_vol else 1
    volumes = range(args.start_vol, args.end_vol + step, step)
    result = download_cases(
        args.out,
        reporter=args.reporter,
        court_name=args.court,
        min_chars=args.min_chars,
        volumes=volumes,
        max_cases=args.max_cases,
    )
    rows = (args.out / "manifest.jsonl").read_text().splitlines()
    dates = sorted(json.loads(r)["decision_date"] for r in rows)
    print(
        f"\nvolumes checked: {result.volumes_checked} (missing: {result.volumes_missing})\n"
        f"cases in manifest: {len(rows)}  newly downloaded: {result.cases_saved}  "
        f"already present: {result.cases_skipped_existing}\n"
        f"decision dates: {dates[0] if dates else '-'} to {dates[-1] if dates else '-'}"
    )
    (args.out / "DOWNLOADED_ON").write_text(date.today().isoformat() + "\n")

    if args.upload:
        n = upload_dir(args.out, args.volume_path)
        print(f"uploaded {n} files to {args.volume_path}")


if __name__ == "__main__":
    main()
