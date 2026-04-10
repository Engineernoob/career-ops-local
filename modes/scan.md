# Mode: scan

**Triggered by:** `ops scan` or `ops scan --company Stripe`

## What This Mode Does

Searches configured companies across Greenhouse, Lever, Ashby, and Wellfound
for open positions matching the candidate's target roles.
Deduplicates against data/scan-history.tsv.
Returns a ranked list of new openings.

## Execution Steps

### Step 1 — Load Config
Read portals.yml: company list, search queries, title filters.
Read config/profile.yml: target roles, excluded keywords.

### Step 2 — Scan Each Company
For each company in portals.yml:
  - Try Greenhouse API: `boards-api.greenhouse.io/v1/boards/{slug}/jobs`
  - Try Lever API: `api.lever.co/v0/postings/{slug}`
  - Try Ashby API: `api.ashbyhq.com/posting-api/job-board/{slug}`
  - Polite delay: 0.5s between requests

### Step 3 — Filter
Apply title_filter.positive (must match at least one)
Apply title_filter.negative (must match none)
Skip titles that are clearly seniority mismatches.

### Step 4 — Deduplicate
Load data/scan-history.tsv.
Skip any URL already in history.
Append new URLs to history with today's date.

### Step 5 — Rank Results
Sort by: archetype match first, then company tier (configured in portals.yml).

### Step 6 — Present
Show table: Company | Role | Location | Portal | URL
Ask: "Add any of these to your pipeline for evaluation? (y/n or list numbers)"
If yes, append selected URLs to data/pipeline.md.

## portals.yml Structure

```yaml
title_filter:
  positive:
    - "engineer"
    - "developer"
    - "architect"
  negative:
    - "intern"
    - "junior"
    - "manager"  # remove if targeting EM roles

companies:
  - name: Stripe
    greenhouse_slug: stripe
    tier: 1
  - name: Vercel
    lever_slug: vercel
    tier: 1
  - name: Linear
    ashby_slug: linear
    tier: 1
```
