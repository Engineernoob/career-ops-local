# Career-Ops — Local LLM Job Search Pipeline

## What This Is

AI-powered job search automation running entirely on **local models via Ollama**.
No cloud. No API keys. No data leaving your machine.

Architecture mirrors the original career-ops by santifer — skill files as scoped
system prompts, markdown as the data layer, YAML for config.

## Workflow Overview

Career-Ops automates the repetitive parts of a modern job search while keeping the developer in control.

```text
Job URL / Job Description
            │
            ▼
    Parse & Normalize
            │
            ▼
     Local LLM (Ollama)
            │
 ┌──────────┼──────────┬────────────┐
 ▼          ▼          ▼            ▼
Score   Tailor CV   Company Research Interview Prep
 └──────────┼──────────┴────────────┘
            ▼
   Generate Reports & Resume
            │
            ▼
 Update Application Tracker
```

Every stage executes locally using Ollama and Markdown-based project data.

## Core Files

| File                           | Purpose                                                         |
| ------------------------------ | --------------------------------------------------------------- |
| `cv.md`                        | Your CV — canonical source of truth. All evaluations read this. |
| `config/profile.yml`           | Your name, targets, salary, archetypes                          |
| `portals.yml`                  | Companies and search queries for the scanner                    |
| `data/applications.md`         | Application tracker (never edit to add — use TSV flow)          |
| `data/pipeline.md`             | Inbox of URLs pending evaluation                                |
| `data/scan-history.tsv`        | Dedup log for scanner                                           |
| `templates/cv-template.html`   | HTML template → PDF via WeasyPrint                              |
| `interview-prep/story-bank.md` | STAR stories accumulated across evaluations                     |
| `reports/`                     | One markdown report per evaluated offer                         |
| `modes/`                       | Skill files — scoped prompts for each operation                 |

## Directory Layout

```text
career-ops/
├── config/
├── data/
├── docs/
├── interview-prep/
├── modes/
├── reports/
├── templates/
├── cv.md
└── README.md
```

## Modes

| User action          | Mode loaded                                         |
| -------------------- | --------------------------------------------------- |
| Paste URL or JD text | `auto-pipeline` → evaluate + report + PDF + tracker |
| `ops evaluate`       | `oferta` — single offer deep evaluation             |
| `ops compare`        | `ofertas` — compare multiple offers                 |
| `ops scan`           | `scan` — search portals for new openings            |
| `ops pipeline`       | `pipeline` — process pending URLs from pipeline.md  |
| `ops batch <file>`   | `batch` — parallel evaluation of URL list           |
| `ops pdf <id>`       | `pdf` — generate tailored CV PDF for a report       |
| `ops tracker`        | `tracker` — view/filter application status          |
| `ops interview <id>` | `interview` — pull STAR stories matching a role     |
| `ops negotiate <id>` | `negotiate` — build salary negotiation script       |
| `ops deep <company>` | `deep` — company research before applying           |
| `ops contact`        | `contact` — LinkedIn outreach message               |
| `ops status`         | health check — verify pipeline integrity            |

## Processing Pipeline

Each operation follows the same high-level pipeline:

1. Receive a job URL or job description.
2. Parse and normalize the posting.
3. Retrieve your profile and CV.
4. Evaluate the opportunity with a local LLM.
5. Produce structured Markdown reports.
6. Tailor your resume.
7. Generate interview preparation.
8. Update the application tracker.

## Scoring

All offers scored 0.0–5.0:

- **4.5–5.0** → A — Strong match, prioritize
- **3.5–4.4** → B — Good match, worth applying
- **2.5–3.4** → C — Partial match, apply selectively
- **1.5–2.4** → D — Weak match, skip unless exceptional reason
- **0.0–1.4** → F — Poor fit, do not apply

**System strongly recommends against applying below 3.0.**

## Design Principles

Career-Ops follows several guiding principles:

- Local-first AI execution.
- Human review before every application.
- Markdown as the primary data format.
- Modular prompt design through modes.
- Reproducible evaluations.
- Privacy by default.

## Ethical Use

- NEVER submit without user reviewing first
- AI filters noise, humans provide judgment
- Quality over quantity — 5 targeted beats 50 generic

## Related Documentation

Additional guides are available in the `docs/` directory:

- Architecture
- Configuration
- CLI Reference
- Resume Tailoring
- Interview Preparation
- Company Research
- FAQ
- Troubleshooting
