# career-ops — local LLM job search pipeline

> AI-powered job search automation running **entirely on local models via Ollama**.
> No cloud. No API keys. No data leaving your machine.

Inspired by [santifer/career-ops](https://github.com/santifer/career-ops) — rebuilt from the ground up for local LLMs.

```
╔═══════════════════════════════════════════════════════════════╗
║  Paste a URL.                                                 ║
║  Get a score (0–5), a report, and a tailored PDF resume.      ║
║  Track everything in one place.                               ║
║  AI filters noise. You make decisions.                        ║
╚═══════════════════════════════════════════════════════════════╝
```

---

## What it does

- **Evaluates** any job offer across 10 dimensions → score 0.0–5.0 (like a grade A–F)
- **Generates** a tailored ATS-optimized CV PDF per offer — keywords injected, bullets reordered, archetype shifted
- **Scans** Greenhouse, Lever, and Ashby for new openings at 45+ pre-configured companies
- **Batch processes** a list of URLs in parallel — evaluate 10+ offers while you sleep
- **Tracks** everything in `data/applications.md` (markdown, git-friendly)
- **Builds** interview prep kits with STAR story mapping and predicted questions
- **Writes** salary negotiation scripts word-for-word
- **Researches** companies before you apply or interview

Everything runs locally. The model that evaluates your CV never sees the internet.

---

## Philosophy (same as the original)

> AI evaluates and recommends. You decide and act. The system never submits an application — you always have the final call.

This is not a spray-and-pray bot. Career-ops is a **filter** — it helps you find the few offers worth your time out of hundreds. Strongly recommends against applying to anything scoring below 3.0/5. Your time is valuable, and so is the recruiter's.

---

## Requirements

- **Python 3.10+**
- **Ollama** — https://ollama.ai (runs local LLMs)
- A pulled model: `ollama pull llama3.2` (or `mistral`, `qwen2.5`, `phi4`, etc.)

Optional for PDF generation:
- `pip install weasyprint` — renders HTML→PDF locally
- Without it, career-ops saves `.html` files you can print to PDF from any browser

---

## Installation

```bash
# 1. Clone
git clone https://github.com/yourname/career-ops-local.git
cd career-ops-local

# 2. Install Python deps
pip install -r requirements.txt

# 3. Start Ollama (if not already running)
ollama serve &
ollama pull llama3.2        # fast and capable
# or: ollama pull qwen2.5   # excellent at structured output
# or: ollama pull phi4      # small but smart

# 4. First-time setup
python ops.py setup
```

Setup will:
- Prompt you to paste your CV in markdown format
- Ask for your name, target roles, salary range, preferred model
- Create `config/profile.yml`, `portals.yml`, `data/applications.md`, `data/pipeline.md`

---

## Usage

### Interactive mode (recommended to start)

```bash
python ops.py
```

You'll get a prompt. Paste any job URL and it runs the full pipeline:
fetch → evaluate → report → PDF → tracker.

### Paste a URL directly

```bash
python ops.py https://boards.greenhouse.io/stripe/jobs/123456
python ops.py https://jobs.lever.co/vercel/abc-def
```

### Scan for new openings

```bash
python ops.py scan                    # scan all companies in portals.yml
python ops.py scan Stripe             # scan a specific company
```

New openings matching your title filters appear in a table.
You choose which ones to add to your pipeline.

### Process all pending URLs

```bash
python ops.py pipeline
```

Evaluates everything in `data/pipeline.md` → Pending, in parallel (3 workers by default).
Prints a ranked table when done.

### Batch evaluate from a file

```bash
cat > urls.txt << EOF
https://boards.greenhouse.io/anthropic/jobs/123
https://jobs.lever.co/cursor/456
https://jobs.ashbyhq.com/linear/789
EOF

python ops.py batch urls.txt
```

### View your pipeline

```bash
python ops.py tracker
python ops.py tracker --status Applied
python ops.py tracker --status Interview
python ops.py tracker --grade A
python ops.py tracker --stats
```

### Deep single evaluation

```bash
python ops.py evaluate https://jobs.lever.co/vercel/abc
```

More detailed than auto-pipeline — 6 evaluation blocks + personalization + interview angle.

### Interview prep

```bash
python ops.py interview 3    # builds prep kit for report #003
```

Pulls STAR stories from `interview-prep/story-bank.md`, maps them to predicted questions,
drafts new stories for any gaps.

### Salary negotiation script

```bash
python ops.py negotiate 3    # generates negotiation playbook for report #003
```

Word-for-word scripts for phone, email, and async negotiation. 3 objection responses.
Non-salary levers when base is fixed.

### Company research

```bash
python ops.py deep "Anthropic"
python ops.py deep "Linear"
```

Saves to `data/research/{slug}.md`. Use before applying or before an interview.

### Re-generate a CV PDF

```bash
python ops.py pdf 3    # re-generates CV for report #003
```

### Health check

```bash
python ops.py status
python verify-pipeline.py    # detailed integrity check
```

---

## File structure

```
career-ops/
├── ops.py                      # Main CLI — the only file you need to run
├── merge-tracker.py            # Merge TSV tracker additions into applications.md
├── verify-pipeline.py          # Pipeline integrity check
├── cv.md                       # YOUR CV — source of truth (you create this)
├── portals.yml                 # Companies to scan + title filters
├── requirements.txt
│
├── config/
│   ├── profile.yml             # Your name, targets, salary, model preference
│   └── profile.example.yml     # Template
│
├── modes/                      # Skill files — scoped prompts per operation
│   ├── _shared.md              # Scoring dimensions + archetypes (loaded by all modes)
│   ├── auto-pipeline.md        # Full pipeline when URL/JD pasted
│   ├── oferta.md               # Single offer deep evaluation
│   ├── pdf.md                  # CV tailoring + PDF generation
│   ├── scan.md                 # Portal scanner
│   ├── batch.md                # Parallel batch processing
│   ├── interview.md            # Interview prep kit
│   ├── negotiate.md            # Negotiation script
│   ├── tracker.md              # Pipeline view + stats
│   └── deep.md                 # Company research
│
├── data/
│   ├── applications.md         # Master tracker — never edit to ADD rows
│   ├── pipeline.md             # Inbox of pending URLs
│   ├── scan-history.tsv        # Dedup log for scanner
│   └── research/               # Company research briefs
│
├── templates/
│   ├── cv-template.html        # HTML→PDF template (customize fonts/colors here)
│   ├── portals.example.yml     # Portals config template
│   └── states.yml              # Canonical status definitions
│
├── reports/                    # One markdown report per offer
│   └── 001-stripe-2026-04-06.md
│
├── output/                     # Generated CV PDFs (gitignored)
│   └── 001-stripe-cv.pdf
│
├── batch/
│   └── tracker-additions/      # TSV staging area before merge (auto-cleared)
│
├── jds/                        # Local JD text files (reference as local:jds/file.md)
│
├── interview-prep/
│   └── story-bank.md           # Your STAR story bank
│
└── examples/
    ├── cv-example.md           # Example CV format
    └── sample-report.md        # Example evaluation report output
```

---

## Customization

**career-ops is designed to be made yours.** Edit any file.

### Change target archetypes

Edit `modes/_shared.md` → Archetypes section.
Replace the 6 default archetypes with ones that match your career.

```yaml
# Example: data engineering archetypes
- Analytics Engineer — dbt, Snowflake, data modeling
- Data Engineer — pipelines, Spark, Airflow
- ML Engineer — training infra, feature stores, serving
```

### Add companies to scan

Edit `portals.yml`:

```yaml
companies:
  - name: Your Target Company
    greenhouse_slug: their-greenhouse-slug   # from their Greenhouse URL
    tier: 1
```

Find the slug from the company's job board URL:
- Greenhouse: `boards.greenhouse.io/{slug}/jobs`
- Lever: `jobs.lever.co/{slug}/`
- Ashby: `jobs.ashbyhq.com/{slug}/`

### Change the scoring weights

Edit the 10 dimensions in `modes/_shared.md`.
Each dimension is 0.0–0.5. Change the descriptions to weight what matters to you.

### Change the CV template design

Edit `templates/cv-template.html`. It's plain HTML/CSS — no framework.
The only required placeholder is `{{CONTENT}}` where the CV body goes.

### Switch Ollama model

Edit `config/profile.yml`:
```yaml
ollama_model: "qwen2.5"   # or phi4, mistral, llama3.1:70b, etc.
```

Larger models give better evaluation quality but take longer.
`llama3.2` is a good default. `qwen2.5:14b` is noticeably better for structured tasks.

---

## Tracker rules (important)

- **NEVER edit `applications.md` to ADD new rows** — the system does this via TSV merge
- **YES, edit `applications.md` to UPDATE status** of existing rows (change `Evaluated` → `Applied`, etc.)
- All statuses must be canonical — see `templates/states.yml`
- Run `python merge-tracker.py` after any batch to sync tracker
- Run `python verify-pipeline.py` to find broken links or dupes

---

## Performance

| Model | Avg evaluation time | Quality |
|-------|--------------------|---------| 
| llama3.2 (3B) | ~20–40s | Good |
| mistral (7B) | ~30–60s | Good |
| qwen2.5 (7B) | ~30–60s | Very good |
| qwen2.5:14b | ~60–120s | Excellent |
| llama3.1:70b | ~3–5min | Best (if you have the VRAM) |

Batch mode runs 3 workers in parallel — 10 offers ≈ 5–15 minutes depending on model.

---

## Differences from santifer/career-ops

| Feature | career-ops (original) | career-ops-local |
|---------|----------------------|------------------|
| AI engine | Claude Code (Anthropic) | Local Ollama models |
| PDF generation | Puppeteer (Node.js) | WeasyPrint (Python) |
| Runtime | Node.js + mjs | Python only |
| Data privacy | Sent to Anthropic API | Fully local |
| Cost | Anthropic API credits | Free (after hardware) |
| Setup | `npm install` + `claude` | `pip install` + `ollama pull` |
| Skill files | `.md` files read by Claude Code | `.md` files loaded as system prompts |

The architecture philosophy is identical: scoped skill files, markdown as data layer, YAML config, HITL design.

---

## Tips

- Your `cv.md` is the canonical source of truth. Keep it updated. The system reads it fresh at every evaluation — no caching.
- Add proof points (metrics, outcomes, specifics) to your CV — vague bullets get vague tailoring.
- Run `ops deep <company>` before applying to any role you're excited about. The research brief feeds directly into your interview prep.
- The story bank (`interview-prep/story-bank.md`) compounds over time — each interview prep session adds new stories.
- Score < 3.0 means skip. Really. Every application to a poor-fit role is noise in the market and noise in your head.
