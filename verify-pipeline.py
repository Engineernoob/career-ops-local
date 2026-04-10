#!/usr/bin/env python3
"""
verify-pipeline.py — Check pipeline integrity.

Checks:
  1. Required files exist
  2. All report links in tracker resolve to files
  3. No duplicate company+role entries
  4. All statuses are canonical
  5. Orphaned reports (in reports/ but not in tracker)

Run: python verify-pipeline.py
"""

import re
import yaml
from pathlib import Path
from collections import Counter

ROOT      = Path(__file__).parent
APPS      = ROOT / "data" / "applications.md"
REPORTS   = ROOT / "reports"
OUTPUT    = ROOT / "output"
STATES    = ROOT / "templates" / "states.yml"


def load_canonical_states() -> set:
    if not STATES.exists():
        return {"Evaluated", "Applied", "Responded", "Interview",
                "Offer", "Rejected", "Discarded", "SKIP"}
    with open(STATES) as f:
        data = yaml.safe_load(f)
    return {s["name"] for s in data.get("states", [])}


def main():
    issues = []
    warnings = []

    # 1. Required files
    required = [
        ROOT / "cv.md",
        ROOT / "config" / "profile.yml",
        ROOT / "portals.yml",
        APPS,
    ]
    for f in required:
        if not f.exists():
            issues.append(f"Missing required file: {f.relative_to(ROOT)}")

    if not APPS.exists():
        print("✗ applications.md missing — cannot verify tracker")
        _print_summary(issues, warnings)
        return

    # 2. Parse tracker
    lines = APPS.read_text().splitlines()
    rows = []
    seen_keys = []
    canonical = load_canonical_states()

    for i, line in enumerate(lines, 1):
        if not line.startswith("|") or "---" in line or "| #" in line:
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) < 7:
            warnings.append(f"Line {i}: malformed row (only {len(cols)} columns)")
            continue

        num, date, company, role = cols[0], cols[1], cols[2], cols[3]
        score, status = cols[4], cols[5]
        report_col = cols[7] if len(cols) > 7 else ""
        rows.append({"num": num, "company": company, "role": role,
                     "status": status, "report": report_col, "line": i})

        # Canonical status check
        if status and status not in canonical:
            issues.append(f"Line {i}: non-canonical status '{status}' for {company} — {role}")

        # Duplicate check
        key = f"{company.lower()}|{role.lower()}"
        seen_keys.append(key)

    dupes = [k for k, v in Counter(seen_keys).items() if v > 1]
    for d in dupes:
        issues.append(f"Duplicate entry: {d}")

    # 3. Report link resolution
    for row in rows:
        report_md = row["report"]
        if not report_md:
            continue
        # Extract path from markdown link [001](reports/001-company-2026-01-01.md)
        m = re.search(r"\((.+?)\)", report_md)
        if m:
            report_path = ROOT / m.group(1)
            if not report_path.exists():
                issues.append(f"Broken report link: {report_path.relative_to(ROOT)} "
                              f"(row: {row['company']} — {row['role']})")

    # 4. Orphaned reports
    tracked_reports = set()
    for row in rows:
        m = re.search(r"\((.+?)\)", row["report"])
        if m:
            tracked_reports.add(ROOT / m.group(1))

    for report_file in REPORTS.glob("*.md"):
        if report_file not in tracked_reports:
            warnings.append(f"Orphaned report (not in tracker): {report_file.name}")

    # Print results
    print(f"\n{'='*50}")
    print(f"  Pipeline Health Check")
    print(f"{'='*50}")
    print(f"  Tracker rows:    {len(rows)}")
    print(f"  Reports on disk: {len(list(REPORTS.glob('*.md')))}")
    print(f"  CVs generated:   {len(list(OUTPUT.glob('*.pdf')) + list(OUTPUT.glob('*.html')))}")
    print(f"{'='*50}\n")

    _print_summary(issues, warnings)


def _print_summary(issues, warnings):
    if not issues and not warnings:
        print("  ✓ Pipeline healthy — no issues found\n")
        return

    if issues:
        print(f"  ✗ {len(issues)} issue(s) found:\n")
        for issue in issues:
            print(f"    ✗ {issue}")
        print()

    if warnings:
        print(f"  ⚠ {len(warnings)} warning(s):\n")
        for w in warnings:
            print(f"    ⚠ {w}")
        print()

    if issues:
        print("  Run: python ops.py setup — to fix missing files")
        print("  Run: python merge-tracker.py — to re-merge tracker\n")


if __name__ == "__main__":
    main()
