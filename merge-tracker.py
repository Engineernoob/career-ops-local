#!/usr/bin/env python3
"""
merge-tracker.py — Merge all TSV files from batch/tracker-additions/
into data/applications.md, deduplicating by company+role.

Run after any batch evaluation:
  python merge-tracker.py
"""

import sys
import re
from pathlib import Path

ROOT      = Path(__file__).parent
APPS      = ROOT / "data" / "applications.md"
BATCH_DIR = ROOT / "batch" / "tracker-additions"

HEADER = (
    "# Applications Tracker\n\n"
    "| # | Date | Company | Role | Score | Status | PDF | Report | Notes |\n"
    "|---|------|---------|------|-------|--------|-----|--------|-------|\n"
)


def load_existing_keys() -> set:
    keys = set()
    if not APPS.exists():
        return keys
    for line in APPS.read_text().splitlines():
        if not line.startswith("|") or "---" in line or "Company" in line:
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) >= 4:
            key = f"{cols[2].lower()}|{cols[3].lower()}"
            keys.add(key)
    return keys


def main():
    tsv_files = sorted(BATCH_DIR.glob("*.tsv"))
    if not tsv_files:
        print("No TSV files to merge.")
        return

    existing = load_existing_keys()

    if not APPS.exists():
        APPS.write_text(HEADER)
        print(f"Created {APPS}")

    added = 0
    skipped = 0
    processed = []

    for tsv in tsv_files:
        line = tsv.read_text().strip()
        if not line:
            tsv.unlink()
            continue

        cols = line.split("\t")
        if len(cols) < 9:
            print(f"  ⚠ Skipping malformed TSV: {tsv.name}")
            continue

        num, date, company, role, status, score, pdf_e, report, notes = cols[:9]
        key = f"{company.lower()}|{role.lower()}"

        if key in existing:
            print(f"  → Skip (duplicate): {company} — {role}")
            skipped += 1
            tsv.unlink()
            continue

        # TSV order: num, date, company, role, status, score, pdf, report, notes
        # Table order: #, date, company, role, score, status, pdf, report, notes
        row = f"| {num} | {date} | {company} | {role} | {score} | {status} | {pdf_e} | {report} | {notes} |"
        with open(APPS, "a") as f:
            f.write(row + "\n")

        existing.add(key)
        added += 1
        processed.append(tsv)
        print(f"  ✓ Added: {company} — {role} ({score})")

    for tsv in processed:
        tsv.unlink()

    print(f"\nDone. Added: {added} | Skipped (dupes): {skipped}")


if __name__ == "__main__":
    main()
