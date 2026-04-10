# Career-Ops — Local LLM Job Search Pipeline

## What This Is

AI-powered job search automation running entirely on **local models via Ollama**.
No cloud. No API keys. No data leaving your machine.

Architecture mirrors the original career-ops by santifer — skill files as scoped
system prompts, markdown as the data layer, YAML for config.

## Core Files

| File | Purpose |
|------|---------|
| `cv.md` | Your CV — canonical source of truth. All evaluations read this. |
| `config/profile.yml` | Your name, targets, salary, archetypes |
| `portals.yml` | Companies and search queries for the scanner |
| `data/applications.md` | Application tracker (never edit to add — use TSV flow) |
| `data/pipeline.md` | Inbox of URLs pending evaluation |
| `data/scan-history.tsv` | Dedup log for scanner |
| `templates/cv-template.html` | HTML template → PDF via WeasyPrint |
| `interview-prep/story-bank.md` | STAR stories accumulated across evaluations |
| `reports/` | One markdown report per evaluated offer |
| `modes/` | Skill files — scoped prompts for each operation |

## Modes

| User action | Mode loaded |
|-------------|-------------|
| Paste URL or JD text | `auto-pipeline` → evaluate + report + PDF + tracker |
| `ops evaluate` | `oferta` — single offer deep evaluation |
| `ops compare` | `ofertas` — compare multiple offers |
| `ops scan` | `scan` — search portals for new openings |
| `ops pipeline` | `pipeline` — process pending URLs from pipeline.md |
| `ops batch <file>` | `batch` — parallel evaluation of URL list |
| `ops pdf <id>` | `pdf` — generate tailored CV PDF for a report |
| `ops tracker` | `tracker` — view/filter application status |
| `ops interview <id>` | `interview` — pull STAR stories matching a role |
| `ops negotiate <id>` | `negotiate` — build salary negotiation script |
| `ops deep <company>` | `deep` — company research before applying |
| `ops contact` | `contact` — LinkedIn outreach message |
| `ops status` | health check — verify pipeline integrity |

## Scoring

All offers scored 0.0–5.0:
- **4.5–5.0** → A — Strong match, prioritize
- **3.5–4.4** → B — Good match, worth applying
- **2.5–3.4** → C — Partial match, apply selectively
- **1.5–2.4** → D — Weak match, skip unless exceptional reason
- **0.0–1.4** → F — Poor fit, do not apply

**System strongly recommends against applying below 3.0.**

## Ethical Use

- NEVER submit without user reviewing first
- AI filters noise, humans provide judgment
- Quality over quantity — 5 targeted beats 50 generic
