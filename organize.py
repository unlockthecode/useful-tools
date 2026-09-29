#!/usr/bin/env python3
"""
organize.py

Organizes screenshots and pictures into dated folders based on the date the
photo was taken (EXIF data), or the file's modification/creation date as a
fallback.

Default layout (day-level):
    YYYY/MM-MonthName/DD/

Use --by-month for:
    YYYY/MM-MonthName/

Use --flat for:
    YYYY-MM-DD/

If no source is given, it organizes the folder the script lives in.

Usage:
    python organize.py                          # organize script's own folder
    python organize.py /path/to/source          # organize a specific folder
    python organize.py /path/to/source /path/to/dest
    python organize.py --by-month
    python organize.py --flat
    python organize.py --dry-run
    python organize.py --move
"""

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image
    from PIL.ExifTags import TAGS
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif",
    ".webp", ".heic", ".heif", ".raw", ".cr2", ".nef", ".arw",
}

DATE_TAGS = ("DateTimeOriginal", "DateTimeDigitized", "DateTime")

SCRIPT_PATH = Path(__file__).resolve()


def get_exif_date(file_path: Path):
    """Return a datetime from EXIF data, or None if unavailable."""
    if not PIL_AVAILABLE:
        return None
    try:
        with Image.open(file_path) as img:
            exif = img.getexif()
            if not exif:
                return None
            for tag_id, value in exif.items():
                tag = TAGS.get(tag_id, tag_id)
                if tag in DATE_TAGS and value:
                    try:
                        return datetime.strptime(str(value), "%Y:%m:%d %H:%M:%S")
                    except (ValueError, TypeError):
                        continue
    except Exception:
        return None
    return None


def get_file_date(file_path: Path):
    """Fallback: earlier of creation time and modification time."""
    stat = file_path.stat()
    try:
        birth = stat.st_birthtime  # macOS / BSD
    except AttributeError:
        birth = stat.st_ctime
    return datetime.fromtimestamp(min(birth, stat.st_mtime))


def get_photo_date(file_path: Path):
    """Best available date for the photo."""
    return get_exif_date(file_path) or get_file_date(file_path)


def build_destination(base: Path, dt: datetime, layout: str) -> Path:
    """Construct the target folder path for a given date and layout."""
    month_dir = base / f"{dt.year:04d}" / f"{dt.month:02d}-{dt.strftime('%B')}"

    if layout == "flat":
        return base / dt.strftime("%Y-%m-%d")
    if layout == "month":
        return month_dir
    # default: day
    return month_dir / f"{dt.day:02d}"


def unique_destination(dest_dir: Path, filename: str) -> Path:
    """Avoid overwriting: append _1, _2, ... if a file already exists."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / filename
    if not target.exists():
        return target
    stem, suffix = Path(filename).stem, Path(filename).suffix
    counter = 1
    while True:
        candidate = dest_dir / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def already_organized(file_path: Path, source: Path) -> bool:
    """Skip files that already live inside a YYYY.../ folder."""
    try:
        rel_parts = file_path.relative_to(source).parts
    except ValueError:
        return False
    return bool(rel_parts) and rel_parts[0][:4].isdigit()


def organize(source: Path, destination: Path, layout: str, move: bool, dry_run: bool):
    if not source.is_dir():
        print(f"Error: {source} is not a directory.", file=sys.stderr)
        sys.exit(1)

    files = []
    for f in source.rglob("*"):
        if not f.is_file():
            continue
        if f.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        if f.resolve() == SCRIPT_PATH:
            continue
        if already_organized(f, source):
            continue
        files.append(f)

    if not files:
        print(f"No image files found in {source}")
        return

    print(f"Source:      {source}")
    print(f"Destination: {destination}")
    print(f"Layout:      {layout}")
    print(f"Found {len(files)} image(s) to organize.\n")

    stats = {"processed": 0, "errors": 0}
    action = "Move" if move else "Copy"

    for file_path in files:
        try:
            dt = get_photo_date(file_path)
            dest_dir = build_destination(destination, dt, layout)
            target = unique_destination(dest_dir, file_path.name)

            try:
                rel = target.relative_to(destination)
            except ValueError:
                rel = target

            print(f"[{action}] {file_path.name}  ->  {rel}")

            if not dry_run:
                if move:
                    shutil.move(str(file_path), str(target))
                else:
                    shutil.copy2(str(file_path), str(target))
            stats["processed"] += 1

        except Exception as e:
            print(f"[ERROR] {file_path}: {e}", file=sys.stderr)
            stats["errors"] += 1

    print("\n" + "=" * 50)
    print(f"Processed: {stats['processed']}")
    print(f"Errors:    {stats['errors']}")
    if dry_run:
        print("(Dry run - no files were actually modified.)")


def main():
    parser = argparse.ArgumentParser(
        description="Organize screenshots/photos into folders based on their dates.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "source", type=Path, nargs="?", default=SCRIPT_PATH.parent,
        help="Directory containing the images. Default: the folder this script is in.",
    )
    parser.add_argument(
        "destination", type=Path, nargs="?", default=None,
        help="Where to put organized files (default: same as source).",
    )

    layout_group = parser.add_mutually_exclusive_group()
    layout_group.add_argument(
        "--by-month", action="store_true",
        help="Group by month only (YYYY/MM-Month/).",
    )
    layout_group.add_argument(
        "--flat", action="store_true",
        help="Flat layout (YYYY-MM-DD/).",
    )

    parser.add_argument("--move", action="store_true",
                        help="Move files instead of copying them.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would happen without touching any files.")

    args = parser.parse_args()

    if args.by_month:
        layout = "month"
    elif args.flat:
        layout = "flat"
    else:
        layout = "day"

    source = args.source.resolve()
    destination = (args.destination or source).resolve()

    if not PIL_AVAILABLE:
        print("Note: Pillow not installed - falling back to file timestamps.")
        print("      Install with: pip install Pillow\n")

    organize(
        source=source,
        destination=destination,
        layout=layout,
        move=args.move,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()