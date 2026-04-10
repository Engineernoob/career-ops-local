# Mode: auto-pipeline

**Triggered when:** User pastes a URL or raw JD text (no explicit command needed)

## What This Mode Does

Runs the full pipeline in sequence:
1. Fetch/parse the job description
2. Evaluate fit against cv.md (10 dimensions, 0–5 score)
3. Write a structured report to reports/{###}-{slug}-{date}.md
4. Generate a tailored CV PDF
5. Write a TSV entry to batch/tracker-additions/
6. Confirm next steps to user

## Execution Steps

### Step 1 — Fetch JD
- If URL: scrape with requests + BeautifulSoup. Try Greenhouse/Lever/Ashby APIs first.
- If raw text: use as-is
- Extract: company name, role title, location, salary (if present), full JD text

### Step 2 — Evaluate
Load modes/_shared.md scoring dimensions.
Load cv.md and config/profile.yml.
Score each dimension 0.0–0.5 with reasoning.
Sum to get final score X.X/5.
Map to grade: ≥4.5=A, ≥3.5=B, ≥2.5=C, ≥1.5=D, <1.5=F

### Step 3 — Write Report
Format per _shared.md report template.
Filename: `reports/{###}-{company-slug}-{YYYY-MM-DD}.md`
Number = max existing report number + 1, zero-padded to 3 digits.

### Step 4 — Generate PDF
Load templates/cv-template.html.
Apply cv-tailoring rules from _shared.md.
Inject keywords, reorder bullets, shift archetype framing.
Render HTML → output/{###}-{company-slug}-cv.pdf via WeasyPrint.

### Step 5 — Write TSV
Write to batch/tracker-additions/{###}-{company-slug}.tsv:
`{num}\t{date}\t{company}\t{role}\tEvaluated\t{score}/5\t✅\t[{num}](reports/{num}-{slug}-{date}.md)\t{one-line note}`

### Step 6 — Confirm
Print to user:
- Score + grade
- Top 2 strengths
- Top 1 gap
- Path to report and PDF
- Recommendation: APPLY / SKIP / HOLD

## Key Rules
- NEVER submit an application
- If score < 3.0, explicitly warn user and recommend skipping
- If URL is behind auth wall, ask user to paste JD text directly
