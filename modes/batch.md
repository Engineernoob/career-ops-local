# Mode: batch

**Triggered by:** `ops batch <url-list-file>` or `ops pipeline`

## What This Mode Does

Processes multiple URLs in parallel (thread pool).
Each URL runs auto-pipeline independently.
Aggregates results into a ranked summary table.

## Execution

### Step 1 — Load URLs
Read from argument file (one URL per line) or data/pipeline.md (## Pending section).
Deduplicate against data/scan-history.tsv.
Skip already-evaluated URLs (check reports/ for existing reports).

### Step 2 — Parallel Evaluation
Run evaluations concurrently with ThreadPoolExecutor (default: 3 workers).
Each worker: fetch JD → score → write report → write TSV.
Progress bar shows status.

### Step 3 — Aggregate
After all workers complete, run: merge tracker additions → update applications.md
Sort all new entries by score descending.
Print ranked table: Rank | Score | Grade | Company | Role | Recommendation

### Step 4 — PDF Batch (optional)
Ask: "Generate PDFs for all offers scoring ≥ 3.5? (y/n)"
If yes, run pdf mode for each qualifying report.

## Performance Notes
- 3 parallel workers is conservative — avoids rate limiting
- Each evaluation: ~30–90s depending on model and JD length
- 10 offers ≈ 5–10 minutes with llama3.2

## pipeline.md Format

```markdown
# Pipeline — Pending Evaluation

## Pending
- https://boards.greenhouse.io/company/jobs/123
- https://lever.co/company/abc
- local:jds/stripe-staff-eng.md

## Processed
- https://... (moved here after evaluation)
```
