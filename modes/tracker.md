# Mode: tracker

**Triggered by:** `ops tracker` or `ops tracker --status Interview`

## What This Mode Does

Reads data/applications.md and presents a filtered, sorted view.
Also runs pipeline integrity checks.

## Views

### Default View
Table sorted by date descending. Last 20 entries.

### Filtered Views
`--status Applied` — only Applied entries
`--status Interview` — active interview processes
`--status Offer` — offers received
`--grade A` — only A-grade evaluated offers not yet applied
`--company Stripe` — all entries for a company

### Stats View (`ops tracker --stats`)
- Total evaluated
- By status breakdown
- By grade breakdown
- Average score
- Response rate (Responded / Applied)
- Interview rate (Interview / Applied)

## Pipeline Health Check (`ops status`)
1. Verify applications.md exists and is valid markdown table
2. Check all report links in tracker resolve to actual files
3. Check all PDF links resolve to actual files in output/
4. Check for duplicate company+role entries
5. Check for non-canonical status values
Report: "Pipeline healthy" or list of issues found.
