#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════╗
║              career-ops — local LLM job search                ║
║   Paste a URL. Get a score, a report, and a tailored PDF.     ║
╚═══════════════════════════════════════════════════════════════╝

  ops                      interactive mode (paste URL to start)
  ops scan                 scan portals for new openings
  ops pipeline             process all URLs in data/pipeline.md
  ops batch <file>         evaluate a list of URLs in parallel
  ops evaluate <url>       deep single-offer evaluation
  ops pdf <id>             generate tailored CV PDF for report #{id}
  ops tracker [--status X] view application pipeline
  ops interview <id>       build interview prep for report #{id}
  ops negotiate <id>       build negotiation script for report #{id}
  ops deep <company>       research a company
  ops status               pipeline health check
  ops setup                first-time onboarding
"""

import os
import sys
import json
import re
import time
import glob
import shutil
import threading
import yaml
import requests
from pathlib import Path
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.text import Text
from rich.markdown import Markdown
from rich import print as rprint

# Scraper module — 3-tier fetch with Playwright fallback
from scraper import fetch_jd, scan_portal, verify_active

# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT        = Path(__file__).parent
CV          = ROOT / "cv.md"
PROFILE     = ROOT / "config" / "profile.yml"
PORTALS     = ROOT / "portals.yml"
APPS        = ROOT / "data" / "applications.md"
PIPELINE    = ROOT / "data" / "pipeline.md"
HISTORY     = ROOT / "data" / "scan-history.tsv"
STORY_BANK  = ROOT / "interview-prep" / "story-bank.md"
CV_TMPL     = ROOT / "templates" / "cv-template.html"
MODES_DIR   = ROOT / "modes"
REPORTS_DIR = ROOT / "reports"
OUTPUT_DIR  = ROOT / "output"
BATCH_DIR   = ROOT / "batch" / "tracker-additions"
RESEARCH_DIR= ROOT / "data" / "research"

for d in [REPORTS_DIR, OUTPUT_DIR, BATCH_DIR, RESEARCH_DIR,
          ROOT / "data", ROOT / "jds", ROOT / "interview-prep"]:
    d.mkdir(parents=True, exist_ok=True)

console = Console()

GRADE_COLOR = {"A": "bright_green", "B": "green", "C": "yellow", "D": "orange1", "F": "red"}
STATUS_COLOR = {
    "Evaluated": "dim", "Applied": "cyan", "Responded": "blue",
    "Interview": "yellow", "Offer": "bright_green",
    "Rejected": "red", "Discarded": "dim", "SKIP": "dim"
}

# ── Ollama LLM ────────────────────────────────────────────────────────────────

OLLAMA_URL = "http://localhost:11434"


def _get_model() -> str:
    cfg = _load_profile()
    if cfg and cfg.get("ollama_model"):
        return cfg["ollama_model"]
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        if r.ok:
            models = r.json().get("models", [])
            if models:
                return models[0]["name"]
    except Exception:
        pass
    return "llama3.2"


def llm(system: str, user: str, temperature: float = 0.2, json_mode: bool = False) -> str:
    """Call local Ollama. Returns response text."""
    model = _get_model()
    if json_mode:
        system += "\n\nRespond ONLY with valid JSON. No markdown fences, no explanation."

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user}
        ],
        "stream": False,
        "options": {"temperature": temperature, "num_predict": 4096}
    }
    try:
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=180)
        r.raise_for_status()
        return r.json()["message"]["content"].strip()
    except requests.exceptions.ConnectionError:
        return "[OFFLINE] Ollama not running. Start with: ollama serve"
    except Exception as e:
        return f"[LLM ERROR] {e}"


# ── Config loaders ────────────────────────────────────────────────────────────

def _load_profile() -> dict:
    if not PROFILE.exists():
        return {}
    with open(PROFILE) as f:
        return yaml.safe_load(f) or {}


def _load_cv() -> str:
    if not CV.exists():
        return ""
    return CV.read_text()


def _load_mode(name: str) -> str:
    path = MODES_DIR / f"{name}.md"
    shared = MODES_DIR / "_shared.md"
    shared_text = shared.read_text() if shared.exists() else ""
    mode_text = path.read_text() if path.exists() else ""
    return shared_text + "\n\n" + mode_text


def _load_portals() -> dict:
    if not PORTALS.exists():
        return {}
    with open(PORTALS) as f:
        return yaml.safe_load(f) or {}


# ── Report helpers ────────────────────────────────────────────────────────────

def _next_report_num() -> int:
    existing = list(REPORTS_DIR.glob("*.md"))
    if not existing:
        return 1
    nums = []
    for f in existing:
        m = re.match(r"^(\d+)-", f.name)
        if m:
            nums.append(int(m.group(1)))
    return (max(nums) + 1) if nums else 1


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:30]


def _parse_score_from_report(report_text: str) -> tuple[float, str]:
    """Extract score and grade from a report."""
    m = re.search(r"\*\*Score:\*\*\s*([\d.]+)/5\s*\(([A-F])\)", report_text)
    if m:
        return float(m.group(1)), m.group(2)
    return 0.0, "?"


def _load_report(report_id: int) -> Optional[tuple[str, Path]]:
    matches = list(REPORTS_DIR.glob(f"{report_id:03d}-*.md"))
    if not matches:
        matches = list(REPORTS_DIR.glob(f"{report_id}-*.md"))
    if not matches:
        return None
    p = matches[0]
    return p.read_text(), p


# ── JD Fetcher ────────────────────────────────────────────────────────────────

def fetch_jd_with_status(url_or_text: str) -> tuple[str, str, str, str]:
    """
    Wrapper around scraper.fetch_jd that prints tier info to the console.
    Returns (jd_text, company, title, url).
    """
    text = url_or_text.strip()

    # Show what tier we'll need
    if text.startswith("http"):
        known_api = any(x in text for x in ["greenhouse.io", "lever.co", "ashbyhq.com", "workable.com"])
        if known_api:
            console.print("  [dim]→ Tier 1: ATS API[/]", end=" ")
        else:
            console.print("  [dim]→ Tier 2/3: scraping (may use browser for JS pages)[/]", end=" ")

    jd, company, title, url = fetch_jd(text)

    if jd.startswith("[CLOSED]") or "no longer available" in jd.lower():
        console.print(f"[yellow]⚠ Job posting appears closed[/]")
    elif jd.startswith("[Could not"):
        console.print(f"[red]✗[/]")
    else:
        console.print(f"[green]✓[/] {len(jd)} chars")

    # Refine company/title with LLM if heuristic got "Unknown"
    if (company == "Unknown" or title == "Unknown") and _load_cv() and not jd.startswith("["):
        refined = _llm_extract_meta(jd)
        if company == "Unknown":
            company = refined.get("company", company)
        if title == "Unknown":
            title = refined.get("title", title)

    return jd, company, title, url


def _llm_extract_meta(jd_text: str) -> dict:
    """Extract company and title from raw JD text via LLM."""
    raw = llm(
        "Extract job metadata. Return only valid JSON.",
        f"JD text:\n{jd_text[:1500]}\n\nReturn: {{\"company\": \"...\", \"title\": \"...\"}}",
        json_mode=True
    )
    try:
        raw = re.sub(r"```(?:json)?", "", raw).strip().strip("`")
        return json.loads(raw)
    except Exception:
        return {"company": "Unknown", "title": "Unknown"}


# ── Core: Evaluate + Report ───────────────────────────────────────────────────

def evaluate_and_report(jd_text: str, company: str, title: str, url: str = "") -> dict:
    """
    Run full evaluation. Returns dict with report_num, score, grade, report_path, pdf_path.
    """
    cv = _load_cv()
    profile = _load_profile()
    mode_ctx = _load_mode("auto-pipeline")

    if not cv:
        console.print("[red]✗ cv.md not found. Run: ops setup[/]")
        return {}

    profile_summary = yaml.dump(profile) if profile else "(no profile configured)"

    # ── Evaluation prompt ─────────────────────────────────────────────────────
    eval_prompt = f"""You are an expert technical recruiter and career coach.

CANDIDATE PROFILE:
{profile_summary}

CANDIDATE CV:
{cv[:4000]}

JOB DESCRIPTION:
{jd_text[:3000]}

Score this opportunity across all 10 dimensions (0.0–0.5 each, total 0.0–5.0).
Write a complete evaluation report following the exact format in the system context.
Be specific, honest, and critical. Reference actual lines from the CV and JD.
If score < 3.0, explicitly recommend SKIP.

Company: {company}
Role: {title}
URL: {url or "not provided"}
Today: {date.today().isoformat()}
Report Number: {_next_report_num():03d}"""

    console.print(f"  [dim]Evaluating with {_get_model()}...[/]")
    report_text = llm(mode_ctx, eval_prompt, temperature=0.2)

    # Parse score and grade
    score, grade = _parse_score_from_report(report_text)

    # If parsing failed, try to extract from LLM output
    if score == 0.0:
        m = re.search(r"(\d\.\d)/5", report_text)
        if m:
            score = float(m.group(1))
        grade_m = re.search(r"\b([ABCDF])\b.*(?:grade|Grade)", report_text[:200])
        if grade_m:
            grade = grade_m.group(1)
        # Map score to grade
        if grade == "?":
            if score >= 4.5: grade = "A"
            elif score >= 3.5: grade = "B"
            elif score >= 2.5: grade = "C"
            elif score >= 1.5: grade = "D"
            else: grade = "F"

    # Write report
    num = _next_report_num()
    slug = _slugify(company)
    today = date.today().isoformat()
    report_name = f"{num:03d}-{slug}-{today}.md"
    report_path = REPORTS_DIR / report_name
    report_path.write_text(report_text)

    # Write TSV tracker entry
    note_m = re.search(r"## TL;DR\n(.+)", report_text)
    note = note_m.group(1).strip()[:80] if note_m else f"Score {score}/5"
    tsv_line = f"{num}\t{today}\t{company}\t{title}\tEvaluated\t{score}/5\t❌\t[{num}](reports/{report_name})\t{note}"
    tsv_path = BATCH_DIR / f"{num:03d}-{slug}.tsv"
    tsv_path.write_text(tsv_line + "\n")

    # Generate PDF
    pdf_path = _generate_pdf_from_jd(num, slug, jd_text, company, title, report_text)
    if pdf_path:
        # Update TSV with PDF check
        tsv_path.write_text(tsv_line.replace("❌", "✅") + "\n")

    return {
        "num": num,
        "score": score,
        "grade": grade,
        "company": company,
        "title": title,
        "report_path": report_path,
        "pdf_path": pdf_path,
        "report_text": report_text,
    }


# ── PDF Generation ────────────────────────────────────────────────────────────

def _generate_pdf_from_jd(num: int, slug: str, jd_text: str, company: str, title: str, report_text: str) -> Optional[Path]:
    """Tailor CV and generate PDF."""
    cv = _load_cv()
    mode_ctx = _load_mode("pdf")

    tailor_prompt = f"""Tailor this CV for the following job. Apply all rules from your system context.

TARGET: {title} at {company}
JOB DESCRIPTION:
{jd_text[:2000]}

EVALUATION NOTES (from report):
{_extract_tailoring_notes(report_text)}

CANDIDATE CV (source of truth — do not invent experience):
{cv}

Return a complete tailored CV in clean markdown. Same structure as input.
Inject keywords naturally. Reorder bullets by relevance. Quantify everything."""

    tailored_md = llm(mode_ctx, tailor_prompt, temperature=0.15)

    # Render to HTML then PDF
    return _md_to_pdf(tailored_md, num, slug, company, title)


def _extract_tailoring_notes(report_text: str) -> str:
    m = re.search(r"## Tailored CV Notes\n(.*?)(?=\n## |\Z)", report_text, re.DOTALL)
    return m.group(1).strip() if m else ""


def _md_to_pdf(cv_md: str, num: int, slug: str, company: str, title: str) -> Optional[Path]:
    """Convert markdown CV to PDF using WeasyPrint."""
    try:
        import weasyprint
        import markdown as md_lib

        html_body = md_lib.markdown(cv_md, extensions=["tables", "extra"])

        # Load template
        if CV_TMPL.exists():
            template = CV_TMPL.read_text()
            html = template.replace("{{CONTENT}}", html_body).replace("{{TITLE}}", f"{title} — {company}")
        else:
            html = _default_html_template(html_body, title, company)

        pdf_path = OUTPUT_DIR / f"{num:03d}-{slug}-cv.pdf"
        weasyprint.HTML(string=html, base_url=str(ROOT)).write_pdf(str(pdf_path))
        return pdf_path

    except ImportError:
        # Fallback: save as HTML (user can print to PDF)
        html_body_fb = _cv_md_to_basic_html(cv_md)
        html = _default_html_template(html_body_fb, title, company)
        html_path = OUTPUT_DIR / f"{num:03d}-{slug}-cv.html"
        html_path.write_text(html)
        console.print(f"  [yellow]WeasyPrint not installed. Saved as HTML:[/] {html_path}")
        console.print(f"  [dim]Install: pip install weasyprint  OR  open HTML → Print → Save as PDF[/]")
        return html_path
    except Exception as e:
        console.print(f"  [yellow]PDF generation failed: {e}[/]")
        return None


def _cv_md_to_basic_html(md_text: str) -> str:
    try:
        import markdown as md_lib
        return md_lib.markdown(md_text, extensions=["tables", "extra"])
    except ImportError:
        return f"<pre>{md_text}</pre>"


def _default_html_template(body: str, title: str, company: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title} — {company}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, 'Helvetica Neue', Arial, sans-serif;
    font-size: 10.5pt;
    line-height: 1.45;
    color: #1a1a1a;
    max-width: 780px;
    margin: 0 auto;
    padding: 36px 44px;
  }}
  h1 {{ font-size: 22pt; color: #111; margin-bottom: 2px; letter-spacing: -0.5px; }}
  h2 {{
    font-size: 9pt; text-transform: uppercase; letter-spacing: 1.5px;
    color: #2c4a8a; border-bottom: 1.5px solid #dde3f0;
    padding-bottom: 3px; margin: 18px 0 8px;
  }}
  h3 {{ font-size: 10.5pt; font-weight: 600; color: #111; margin-bottom: 1px; }}
  p {{ margin-bottom: 6px; }}
  ul {{ padding-left: 16px; margin-bottom: 8px; }}
  li {{ margin-bottom: 3px; }}
  .contact {{ color: #555; font-size: 9.5pt; margin-bottom: 14px; }}
  a {{ color: #2c4a8a; text-decoration: none; }}
  @media print {{
    body {{ padding: 20px 28px; }}
    @page {{ margin: 0.5in; }}
  }}
</style>
</head>
<body>
{body}
</body>
</html>"""


# ── Tracker merge ─────────────────────────────────────────────────────────────

def merge_tracker():
    """Merge all TSV files in batch/tracker-additions/ into data/applications.md."""
    tsv_files = sorted(BATCH_DIR.glob("*.tsv"))
    if not tsv_files:
        return

    # Load existing apps to check for dupes
    existing = set()
    if APPS.exists():
        for line in APPS.read_text().splitlines():
            cols = [c.strip() for c in line.split("|")]
            if len(cols) >= 5:
                company_col = cols[3] if len(cols) > 3 else ""
                role_col = cols[4] if len(cols) > 4 else ""
                key = f"{company_col.lower()}|{role_col.lower()}"
                existing.add(key)

    new_rows = []
    processed = []
    for tsv in tsv_files:
        line = tsv.read_text().strip()
        if not line:
            continue
        cols = line.split("\t")
        if len(cols) < 9:
            continue
        # TSV order: num, date, company, role, status, score, pdf, report, notes
        # Table order: #, date, company, role, score, status, pdf, report, notes
        num, d, company, role, status, score, pdf_e, report, notes = cols[:9]
        key = f"{company.lower()}|{role.lower()}"
        if key not in existing:
            # Swap score/status for table format
            new_rows.append(f"| {num} | {d} | {company} | {role} | {score} | {status} | {pdf_e} | {report} | {notes} |")
            existing.add(key)
            processed.append(tsv)

    if new_rows:
        if not APPS.exists():
            APPS.write_text(
                "# Applications Tracker\n\n"
                "| # | Date | Company | Role | Score | Status | PDF | Report | Notes |\n"
                "|---|------|---------|------|-------|--------|-----|--------|-------|\n"
            )
        with open(APPS, "a") as f:
            for row in new_rows:
                f.write(row + "\n")

    # Archive processed TSVs
    for tsv in processed:
        tsv.unlink()


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_setup():
    """First-time onboarding."""
    console.print(Panel.fit(
        "[bold cyan]career-ops — local LLM job search[/]\n"
        "All AI runs locally via Ollama. Nothing leaves your machine.",
        border_style="cyan"
    ))

    # Check Ollama
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        models = r.json().get("models", []) if r.ok else []
        if models:
            model_names = [m["name"] for m in models]
            console.print(f"[green]✓ Ollama running[/] — models: {', '.join(model_names[:3])}")
        else:
            console.print("[yellow]⚠ Ollama running but no models pulled.[/]")
            console.print("  Run: [cyan]ollama pull llama3.2[/]")
    except Exception:
        console.print("[red]✗ Ollama not running.[/] Start it: [cyan]ollama serve &[/]")
        console.print("  Then pull a model: [cyan]ollama pull llama3.2[/]")

    # Step 1: CV
    if not CV.exists():
        console.print("\n[bold]Step 1: Your CV[/]")
        console.print("Paste your CV below in markdown format.")
        console.print("Sections: Summary, Experience, Projects, Education, Skills")
        console.print("Type [bold red]END[/] on its own line when done:\n")
        lines = []
        while True:
            try:
                line = input()
            except EOFError:
                break
            if line.strip().upper() == "END":
                break
            lines.append(line)
        cv_text = "\n".join(lines).strip()
        if cv_text:
            CV.write_text(cv_text)
            console.print(f"[green]✓ cv.md saved ({len(cv_text)} chars)[/]")
        else:
            console.print("[yellow]Skipped — create cv.md manually before evaluating offers.[/]")
    else:
        console.print(f"[green]✓ cv.md exists[/] ({CV.stat().st_size} bytes)")

    # Step 2: Profile
    if not PROFILE.exists():
        console.print("\n[bold]Step 2: Profile[/]")
        name     = Prompt.ask("Your full name")
        email    = Prompt.ask("Email")
        location = Prompt.ask("Location (e.g. San Francisco, CA or Remote)")
        roles    = Prompt.ask("Target roles (comma-separated, e.g. Staff Engineer, Tech Lead)")
        salary   = Prompt.ask("Salary target (e.g. $180k-$220k)")
        model    = Prompt.ask("Ollama model to use", default="llama3.2")

        profile_content = f"""name: "{name}"
email: "{email}"
location: "{location}"
target_roles:
{chr(10).join(f'  - "{r.strip()}"' for r in roles.split(","))}
salary_target: "{salary}"
ollama_model: "{model}"
preferred_stage: "growth"  # seed / growth / public
remote_preference: "remote-first"  # remote-first / hybrid / on-site
"""
        PROFILE.parent.mkdir(exist_ok=True)
        PROFILE.write_text(profile_content)
        console.print(f"[green]✓ config/profile.yml saved[/]")
    else:
        console.print(f"[green]✓ config/profile.yml exists[/]")

    # Step 3: Portals
    if not PORTALS.exists():
        _write_default_portals()
        console.print(f"[green]✓ portals.yml created[/] (45+ companies pre-configured)")
    else:
        console.print(f"[green]✓ portals.yml exists[/]")

    # Step 4: Tracker
    if not APPS.exists():
        APPS.write_text(
            "# Applications Tracker\n\n"
            "| # | Date | Company | Role | Score | Status | PDF | Report | Notes |\n"
            "|---|------|---------|------|-------|--------|-----|--------|-------|\n"
        )
        console.print(f"[green]✓ data/applications.md created[/]")

    # Step 5: Pipeline
    if not PIPELINE.exists():
        PIPELINE.write_text("# Pipeline — Pending Evaluation\n\n## Pending\n\n## Processed\n")
        console.print(f"[green]✓ data/pipeline.md created[/]")

    console.print(Panel.fit(
        "✓ Setup complete!\n\n"
        "Next:\n"
        "  • [cyan]python ops.py[/]              — interactive mode (paste a URL)\n"
        "  • [cyan]python ops.py scan[/]          — scan portals for new openings\n"
        "  • [cyan]python ops.py tracker[/]       — view your pipeline\n"
        "  • Edit [bold]portals.yml[/] to customize your target companies\n"
        "  • Edit [bold]config/profile.yml[/] to tune your preferences",
        title="[bold green]Ready[/]", border_style="green"
    ))


def cmd_evaluate(url_or_text: str):
    """Single offer evaluation."""
    console.print(f"\n[bold cyan]⚙ Fetching job description...[/]")
    jd, company, title, url = fetch_jd_with_status(url_or_text)

    if jd.startswith("["):
        console.print(f"[red]{jd}[/]")
        if "closed" in jd.lower():
            console.print("[dim]Tip: The role may have been filled. Check the URL directly.[/]")
        else:
            console.print("[dim]Tip: Paste the JD text directly if the URL is behind a login.[/]")
        return

    if not company or company == "Unknown":
        company = Prompt.ask("[bold]Company name[/]")
    if not title or title == "Unknown":
        title = Prompt.ask("[bold]Role title[/]")

    console.print(f"\n[bold]📋 {title}[/] at [bold cyan]{company}[/]")
    console.print(f"[bold cyan]🤖 Running evaluation...[/]")

    result = evaluate_and_report(jd, company, title, url)
    if not result:
        return

    _print_result(result)

    # Merge tracker
    merge_tracker()
    console.print(f"\n[green]✓ Tracker updated[/]")


def _print_result(result: dict):
    score = result["score"]
    grade = result["grade"]
    color = GRADE_COLOR.get(grade, "white")

    # Extract key sections from report
    report = result.get("report_text", "")
    strengths = re.findall(r"## Strengths\n(.*?)(?=\n## |\Z)", report, re.DOTALL)
    gaps      = re.findall(r"## Gaps\n(.*?)(?=\n## |\Z)", report, re.DOTALL)
    rec       = re.findall(r"## Recommendation\n(.*?)(?=\n## |\Z)", report, re.DOTALL)
    tldr      = re.findall(r"## TL;DR\n(.*?)(?=\n## |\Z)", report, re.DOTALL)

    body = f"[bold {color}]Score: {score}/5  Grade: {grade}[/]\n\n"
    if tldr:
        body += f"[bold]Summary:[/] {tldr[0].strip()}\n\n"
    if strengths:
        body += f"[bold green]Strengths:[/]\n{strengths[0].strip()}\n\n"
    if gaps:
        body += f"[bold red]Gaps:[/]\n{gaps[0].strip()}\n\n"
    if rec:
        body += f"[bold]→ {rec[0].strip()}[/]"

    body += f"\n\n[dim]Report:[/] {result['report_path']}"
    if result.get("pdf_path"):
        body += f"\n[dim]PDF:   [/] {result['pdf_path']}"

    console.print(Panel(
        body,
        title=f"[bold]{result['title']} @ {result['company']} — #{result['num']:03d}[/]",
        border_style=color
    ))

    if score < 3.0:
        console.print(
            Panel("[bold red]⚠ Score below 3.0 — system recommends skipping this one.[/]\n"
                  "Your time is valuable. Apply only where there's a genuine match.",
                  border_style="red")
        )


def cmd_tracker(status_filter: str = None, grade_filter: str = None, stats: bool = False):
    """View application pipeline."""
    if not APPS.exists():
        console.print("[yellow]No tracker yet. Run: python ops.py setup[/]")
        return

    lines = APPS.read_text().splitlines()
    rows = []
    for line in lines:
        if not line.startswith("|") or line.startswith("| #") or line.startswith("|--"):
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) >= 6:
            rows.append(cols)

    # Filter
    if status_filter:
        rows = [r for r in rows if r[5].lower() == status_filter.lower()]
    if grade_filter:
        rows = [r for r in rows if grade_filter.upper() in r[4]]

    if stats:
        _print_tracker_stats(rows)
        return

    table = Table(show_header=True, header_style="bold cyan", expand=True,
                  box=None, show_edge=False, pad_edge=False)
    table.add_column("#", width=4)
    table.add_column("Date", width=11)
    table.add_column("Company", width=18)
    table.add_column("Role", width=28)
    table.add_column("Score", width=7, justify="center")
    table.add_column("Status", width=12)
    table.add_column("PDF", width=4, justify="center")

    for r in rows[-40:]:
        num, d, company, role = r[0], r[1], r[2], r[3]
        score_s, status = r[4], r[5]
        pdf_e = r[6] if len(r) > 6 else ""
        s_color = STATUS_COLOR.get(status, "white")
        # Grade from score
        try:
            score_v = float(score_s.replace("/5", ""))
            if score_v >= 4.5: g = "A"
            elif score_v >= 3.5: g = "B"
            elif score_v >= 2.5: g = "C"
            elif score_v >= 1.5: g = "D"
            else: g = "F"
            g_color = GRADE_COLOR.get(g, "white")
            score_display = f"[{g_color}]{score_s}[/]"
        except Exception:
            score_display = score_s

        table.add_row(num, d, company[:17], role[:27], score_display,
                      f"[{s_color}]{status}[/]", pdf_e)

    total = len(rows)
    console.print(Panel(table, title=f"[bold]Pipeline — {total} applications[/]", border_style="cyan"))
    console.print("[dim]Filters: --status Applied | --grade A | --stats[/]")


def _print_tracker_stats(rows: list):
    from collections import Counter
    statuses = Counter(r[5] for r in rows if len(r) > 5)
    scores = []
    for r in rows:
        try:
            scores.append(float(r[4].replace("/5", "")))
        except Exception:
            pass

    table = Table(show_header=False, box=None, show_edge=False)
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_row("Total evaluated", str(len(rows)))
    table.add_row("Avg score", f"{sum(scores)/len(scores):.2f}/5" if scores else "N/A")
    for status, count in sorted(statuses.items(), key=lambda x: -x[1]):
        color = STATUS_COLOR.get(status, "white")
        table.add_row(status, f"[{color}]{count}[/]")

    applied = statuses.get("Applied", 0) + statuses.get("Responded", 0) + statuses.get("Interview", 0)
    interviewed = statuses.get("Interview", 0)
    if applied:
        table.add_row("Interview rate", f"{interviewed/applied*100:.0f}%")

    console.print(Panel(table, title="[bold]Pipeline Stats[/]", border_style="cyan"))


def cmd_scan(company_filter: str = None):
    """Scan portals for new openings."""
    portals_cfg = _load_portals()
    if not portals_cfg:
        console.print("[yellow]portals.yml not found. Run: python ops.py setup[/]")
        return

    companies = portals_cfg.get("companies", [])
    if company_filter:
        companies = [c for c in companies if company_filter.lower() in c.get("name", "").lower()]

    title_pos = portals_cfg.get("title_filter", {}).get("positive", [])
    title_neg = portals_cfg.get("title_filter", {}).get("negative", [])

    # Load dedup history
    seen_urls = set()
    if HISTORY.exists():
        for line in HISTORY.read_text().splitlines():
            parts = line.split("\t")
            if parts:
                seen_urls.add(parts[0])

    all_jobs = []
    console.print(f"\n[bold cyan]🔭 Scanning {len(companies)} companies...[/]\n")

    for company in companies:
        name = company.get("name", "")
        new_for_company = []
        portals_tried = []

        for portal, slug_key in [
            ("greenhouse", "greenhouse_slug"),
            ("lever",      "lever_slug"),
            ("ashby",      "ashby_slug"),
            ("workable",   "workable_slug"),
            ("wellfound",  "wellfound_slug"),
        ]:
            slug = company.get(slug_key)
            if not slug:
                continue
            portals_tried.append(portal)
            jobs = scan_portal(portal, slug, name)
            for j in jobs:
                url = j.get("url", "")
                if not url or url in seen_urls:
                    continue
                title_lower = j.get("title", "").lower()
                if title_pos and not any(p.lower() in title_lower for p in title_pos):
                    continue
                if any(n.lower() in title_lower for n in title_neg):
                    continue
                new_for_company.append(j)
                seen_urls.add(url)
            time.sleep(0.4)

        # Custom career page — Playwright-powered
        career_url = company.get("career_url")
        if career_url:
            portals_tried.append("custom")
            jobs = scan_portal("custom", "", name, career_url=career_url)
            for j in jobs:
                url = j.get("url", "")
                if not url or url in seen_urls:
                    continue
                title_lower = j.get("title", "").lower()
                if title_pos and not any(p.lower() in title_lower for p in title_pos):
                    continue
                if any(n.lower() in title_lower for n in title_neg):
                    continue
                new_for_company.append(j)
                seen_urls.add(url)

        status = f"[green]{len(new_for_company)} new[/]" if new_for_company else "[dim]0 new[/]"
        portal_str = f"[dim]({', '.join(portals_tried)})[/]" if portals_tried else ""
        console.print(f"  {name:25} {status} {portal_str}")
        all_jobs.extend(new_for_company)

    if not all_jobs:
        console.print("\n[yellow]No new openings found matching your filters.[/]")
        return

    # Update history
    with open(HISTORY, "a") as f:
        for j in all_jobs:
            f.write(f"{j['url']}\t{date.today().isoformat()}\t{j['company']}\t{j['title']}\n")

    # Display results
    console.print(f"\n[bold green]✓ {len(all_jobs)} new openings found[/]\n")
    table = Table(show_header=True, header_style="bold cyan", expand=True, box=None, show_edge=False)
    table.add_column("#", width=4)
    table.add_column("Company", width=20)
    table.add_column("Role", width=35)
    table.add_column("Location", width=18)
    table.add_column("Portal", width=12)

    for i, j in enumerate(all_jobs, 1):
        table.add_row(str(i), j["company"][:19], j["title"][:34],
                      (j.get("location") or "")[:17], j.get("portal", ""))
    console.print(table)

    # Offer to add to pipeline — with guardrails on large counts
    console.print()
    total = len(all_jobs)

    if total > 50:
        console.print(Panel(
            f"[yellow]{total} new openings found.[/] Adding all at once would take hours to evaluate.\n\n"
            "Recommended: pick the most relevant companies/roles, or add in batches.\n"
            "[dim]Tip: enter numbers like [cyan]1,5,12,23[/] to cherry-pick, "
            "or [cyan]all[/] if you want the full list added for overnight processing.[/]",
            title="[bold yellow]Large result set[/]", border_style="yellow"
        ))

    add = Prompt.ask(
        f"Add to pipeline? ([cyan]all[/] / numbers like [cyan]1,3,5[/] / [cyan]n[/])",
        default="n"
    )

    if add.strip().lower() != "n":
        selected = []
        if add.strip().lower() == "all":
            selected = all_jobs
        else:
            try:
                idxs = [int(x.strip()) - 1 for x in add.split(",")]
                selected = [all_jobs[i] for i in idxs if 0 <= i < len(all_jobs)]
            except Exception:
                pass

        if selected:
            pipeline_text = PIPELINE.read_text() if PIPELINE.exists() else "# Pipeline\n\n## Pending\n\n## Processed\n"
            urls_block = "\n".join(f"- {j['url']}" for j in selected)
            pipeline_text = pipeline_text.replace("## Pending\n", f"## Pending\n{urls_block}\n")
            PIPELINE.write_text(pipeline_text)
            console.print(
                f"[green]✓ Added {len(selected)} URLs to pipeline.[/]\n"
                f"  Run: [cyan]python ops.py pipeline --limit 10[/] to evaluate the first 10\n"
                f"  Or:  [cyan]python ops.py pipeline --limit 5[/]  for a quick first pass"
            )


def cmd_verify(url: str):
    """Check whether a job posting is still active using Playwright."""
    console.print(f"\n[bold cyan]🔍 Verifying listing status...[/]")
    console.print(f"  [dim]{url}[/]\n")

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  transient=True, console=console) as p:
        p.add_task("Loading page with browser...")
        is_active, method = verify_active(url)

    if is_active:
        console.print(f"[bold green]✓ Job is ACTIVE[/] [dim](verified via {method})[/]")
    else:
        console.print(f"[bold red]✗ Job appears CLOSED[/] [dim](verified via {method})[/]")
        console.print("[dim]The posting may have been filled or taken down.[/]")


# scan_portal imported from scraper.py


def cmd_pipeline(limit: int = 20, workers: int = 2):
    """Process pending URLs in data/pipeline.md — capped batch, smart defaults."""
    if not PIPELINE.exists():
        console.print("[yellow]pipeline.md not found. Run: python ops.py setup[/]")
        return

    content = PIPELINE.read_text()
    pending_m = re.search(r"## Pending\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
    if not pending_m:
        console.print("[yellow]No pending section in pipeline.md[/]")
        return

    all_urls = [line.lstrip("- ").strip() for line in pending_m.group(1).strip().splitlines()
                if line.strip() and not line.strip().startswith("#")]

    if not all_urls:
        console.print("[yellow]No pending URLs in pipeline.md[/]")
        return

    total_pending = len(all_urls)
    urls = all_urls[:limit]

    if total_pending > limit:
        console.print(Panel(
            f"[yellow]{total_pending} URLs pending.[/] Processing first [bold]{limit}[/] this run.\n"
            f"Run again to process the next batch. Use [cyan]--limit N[/] to change batch size.\n\n"
            f"[dim]Tip: --limit 5 is safe for a first run to verify quality.[/]",
            title="[bold]Batch capped[/]", border_style="yellow"
        ))
    else:
        console.print(f"\n[bold cyan]⚙ Processing {len(urls)} URLs[/] ({workers} workers)\n")

    results = []

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  BarColumn(), TaskProgressColumn(), console=console) as progress:
        task = progress.add_task("Evaluating...", total=len(urls))
        lock = threading.Lock()

        def process(url):
            jd, company, title, clean_url = fetch_jd(url)
            if jd.startswith("[CLOSED]") or "no longer available" in jd.lower():
                with lock:
                    progress.advance(task)
                return {"skipped": "closed", "url": url}
            if jd.startswith("["):
                with lock:
                    progress.advance(task)
                return {"error": jd, "url": url}
            result = evaluate_and_report(jd, company, title, clean_url or url)
            with lock:
                progress.advance(task)
            return result

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(process, url): url for url in urls}
            for future in as_completed(futures):
                r = future.result()
                if r:
                    results.append(r)

    merge_tracker()

    # Move processed URLs
    processed_section = "\n".join(f"- {u}" for u in urls)
    new_content = content.replace(
        pending_m.group(1),
        "\n"
    ).replace("## Processed\n", f"## Processed\n{processed_section}\n")
    PIPELINE.write_text(new_content)

    # Summary table
    results = [r for r in results if r and "error" not in r]
    results.sort(key=lambda x: x.get("score", 0), reverse=True)

    table = Table(show_header=True, header_style="bold cyan", expand=True, box=None, show_edge=False)
    table.add_column("Rank", width=5)
    table.add_column("Score", width=8, justify="center")
    table.add_column("Grade", width=6, justify="center")
    table.add_column("Company", width=20)
    table.add_column("Role", width=30)
    table.add_column("Rec", width=8)

    for i, r in enumerate(results, 1):
        g = r.get("grade", "?")
        g_color = GRADE_COLOR.get(g, "white")
        rec = "APPLY" if r.get("score", 0) >= 3.5 else ("HOLD" if r.get("score", 0) >= 2.5 else "SKIP")
        rec_color = "green" if rec == "APPLY" else ("yellow" if rec == "HOLD" else "red")
        table.add_row(
            str(i), f"{r.get('score', 0):.1f}/5",
            f"[{g_color}]{g}[/]",
            r.get("company", "")[:19], r.get("title", "")[:29],
            f"[{rec_color}]{rec}[/]"
        )

    console.print(Panel(table, title=f"[bold]Batch Results — {len(results)} evaluated[/]", border_style="cyan"))


def cmd_interview(report_id: int):
    """Build interview prep for a report."""
    loaded = _load_report(report_id)
    if not loaded:
        console.print(f"[red]Report #{report_id} not found.[/]")
        return

    report_text, report_path = loaded
    cv = _load_cv()
    mode_ctx = _load_mode("interview")
    story_bank = STORY_BANK.read_text() if STORY_BANK.exists() else "(empty)"

    m_company = re.search(r"# \d+ — (.+?) —", report_text)
    m_role    = re.search(r"# \d+ — .+? — (.+)", report_text)
    company = m_company.group(1) if m_company else "the company"
    role    = m_role.group(1).strip() if m_role else "this role"

    prompt = f"""Build a complete interview prep kit for this role.

REPORT:
{report_text[:3000]}

CV:
{cv[:2500]}

EXISTING STAR STORY BANK:
{story_bank[:2000]}

Include: predicted questions, STAR story mapping, questions to ask them, opening pitch.
For any competency with no existing story, draft a new STAR story from the CV and add it."""

    console.print(f"\n[bold cyan]🎤 Building interview prep for #{report_id:03d}...[/]")
    result = llm(mode_ctx, prompt, temperature=0.25)

    console.print(Panel(Markdown(result),
                        title=f"[bold]Interview Prep — {role} @ {company}[/]",
                        border_style="yellow"))

    # Update story bank with any new stories
    new_stories = re.findall(r"### New STAR Story(.*?)(?=###|\Z)", result, re.DOTALL)
    if new_stories:
        with open(STORY_BANK, "a") as f:
            f.write(f"\n\n---\n<!-- Added during #{report_id:03d} interview prep -->\n")
            for s in new_stories:
                f.write(s.strip() + "\n")
        console.print(f"[green]✓ Added {len(new_stories)} new stories to story-bank.md[/]")


def cmd_negotiate(report_id: int, offer_details: str = None):
    """Build negotiation script for an offer."""
    loaded = _load_report(report_id)
    if not loaded:
        console.print(f"[red]Report #{report_id} not found.[/]")
        return

    report_text, _ = loaded
    profile = _load_profile()
    mode_ctx = _load_mode("negotiate")

    if not offer_details:
        offer_details = Prompt.ask("[bold]Paste offer details[/] (salary, equity, bonus, start date, etc.)")

    prompt = f"""Build a complete salary negotiation playbook.

PROFILE: {yaml.dump(profile)}
REPORT CONTEXT:
{report_text[:2000]}
OFFER RECEIVED: {offer_details}

Include: opening response script, counter-offer script (phone + email versions),
3 objection responses, non-salary levers, walk-away line."""

    console.print(f"\n[bold cyan]🤝 Building negotiation script...[/]")
    result = llm(mode_ctx, prompt, temperature=0.3)

    m_company = re.search(r"# \d+ — (.+?) —", report_text)
    company = m_company.group(1) if m_company else "the company"

    console.print(Panel(Markdown(result),
                        title=f"[bold]Negotiation Playbook — {company}[/]",
                        border_style="green"))


def cmd_deep(company: str):
    """Company research."""
    mode_ctx = _load_mode("deep")
    prompt = f"""Research this company thoroughly for a job application context.
Company: {company}
Build a complete company brief with all sections from your system context.
Use your knowledge. Be honest about red flags if any exist."""

    console.print(f"\n[bold cyan]🔬 Researching {company}...[/]")
    result = llm(mode_ctx, prompt, temperature=0.3)

    slug = _slugify(company)
    out_path = RESEARCH_DIR / f"{slug}.md"
    out_path.write_text(f"# Research: {company}\n\n{result}")

    console.print(Panel(Markdown(result), title=f"[bold]{company} — Company Brief[/]", border_style="blue"))
    console.print(f"[dim]Saved: {out_path}[/]")


def cmd_status():
    """Pipeline health check + daemon status."""
    issues = []
    checks = []

    checks.append(("cv.md", CV.exists()))
    checks.append(("config/profile.yml", PROFILE.exists()))
    checks.append(("portals.yml", PORTALS.exists()))
    checks.append(("data/applications.md", APPS.exists()))

    reports = list(REPORTS_DIR.glob("*.md"))
    checks.append((f"reports/ ({len(reports)} files)", len(reports) >= 0))

    pdfs = list(OUTPUT_DIR.glob("*.pdf")) + list(OUTPUT_DIR.glob("*.html"))
    checks.append((f"output/ ({len(pdfs)} CVs)", len(pdfs) >= 0))

    table = Table(show_header=False, box=None, show_edge=False)
    table.add_column("Check", width=30)
    table.add_column("Status", width=10)
    for name, ok in checks:
        status = "[green]✓[/]" if ok else "[red]✗[/]"
        table.add_row(name, status)
        if not ok:
            issues.append(name)

    console.print(Panel(table, title="[bold]Pipeline Health[/]", border_style="cyan"))
    if issues:
        console.print(f"[red]Issues found: {', '.join(issues)}[/]")
        console.print("[dim]Run: python ops.py setup[/]")
    else:
        console.print("[green]✓ Pipeline healthy[/]")

    # Daemon state
    state_file = Path.home() / ".career-ops" / "daemon-state.json"
    if state_file.exists():
        import json as _json
        state = _json.loads(state_file.read_text())
        dt = Table(show_header=False, box=None, show_edge=False)
        dt.add_column("Key", width=24, style="dim")
        dt.add_column("Value")
        dt.add_row("Last run",          state.get("last_run_at", "never")[:19])
        dt.add_row("Last scan",         state.get("last_scan_at", "never")[:19])
        dt.add_row("New jobs found",    str(state.get("last_scan_found", 0)))
        dt.add_row("Offers evaluated",  str(state.get("last_evaluated", 0)))
        dt.add_row("Runtime",           state.get("last_run_elapsed", "—"))
        if state.get("last_error"):
            dt.add_row("[red]Last error[/]", f"[red]{state['last_error']}[/]")
        console.print(Panel(dt, title="[bold]Daemon Status[/]", border_style="dim"))
    else:
        console.print(Panel(
            "[dim]Daemon not yet run.[/]\n"
            "Install automation: [cyan]python install.py[/]\n"
            "Run now:            [cyan]python daemon.py --force[/]",
            title="[bold]Daemon[/]", border_style="dim"
        ))


def cmd_interactive():
    """Interactive mode — paste a URL or JD to start."""
    console.print(Panel.fit(
        "[bold cyan]career-ops[/] — local LLM job search\n\n"
        "Paste a job URL or JD text to evaluate it.\n"
        "Type [bold]help[/] for all commands. [bold]q[/] to quit.",
        border_style="cyan"
    ))

    # Onboarding check
    missing = []
    if not CV.exists():       missing.append("cv.md")
    if not PROFILE.exists():  missing.append("config/profile.yml")
    if missing:
        console.print(f"\n[yellow]⚠ Setup incomplete. Missing: {', '.join(missing)}[/]")
        console.print("[dim]Run: python ops.py setup[/]\n")

    while True:
        try:
            inp = Prompt.ask("\n[bold cyan]career-ops[/]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye.[/]")
            break

        if not inp:
            continue
        if inp.lower() in ("q", "quit", "exit"):
            break
        if inp.lower() == "help":
            console.print(Markdown(__doc__))
            continue
        if inp.lower() == "tracker":
            cmd_tracker()
        elif inp.lower().startswith("tracker "):
            parts = inp.split()
            status = None
            for i, p in enumerate(parts):
                if p == "--status" and i + 1 < len(parts):
                    status = parts[i + 1]
            cmd_tracker(status_filter=status)
        elif inp.lower() == "scan":
            cmd_scan()
        elif inp.lower().startswith("pipeline"):
            parts = inp.split()
            limit = 20
            for i, p in enumerate(parts):
                if p == "--limit" and i + 1 < len(parts):
                    try: limit = int(parts[i + 1])
                    except ValueError: pass
            cmd_pipeline(limit=limit)
        elif inp.lower() == "status":
            cmd_status()
        elif inp.lower().startswith("interview "):
            try:
                cmd_interview(int(inp.split()[1]))
            except (IndexError, ValueError):
                console.print("[red]Usage: interview <report-id>[/]")
        elif inp.lower().startswith("negotiate "):
            try:
                cmd_negotiate(int(inp.split()[1]))
            except (IndexError, ValueError):
                console.print("[red]Usage: negotiate <report-id>[/]")
        elif inp.lower().startswith("verify "):
            cmd_verify(inp[7:].strip())
        elif inp.lower().startswith("deep "):
            cmd_deep(inp[5:].strip())
        elif inp.lower().startswith("pdf "):
            try:
                rid = int(inp.split()[1])
                loaded = _load_report(rid)
                if loaded:
                    report_text, _ = loaded
                    jd_m = re.search(r"\*\*URL:\*\*\s*(.+)", report_text)
                    url = jd_m.group(1).strip() if jd_m else ""
                    jd, company, title, _ = fetch_jd(url) if url.startswith("http") else ("", "Company", "Role", "")
                    slug = _slugify(company)
                    _generate_pdf_from_jd(rid, slug, jd, company, title, report_text)
                else:
                    console.print(f"[red]Report #{rid} not found.[/]")
            except (IndexError, ValueError):
                console.print("[red]Usage: pdf <report-id>[/]")
        elif inp.startswith("http") or inp.startswith("local:") or len(inp) > 200:
            # URL or pasted JD text
            cmd_evaluate(inp)
        else:
            console.print(f"[yellow]Unknown command: {inp}[/] — type [bold]help[/]")


# ── Portals default config ────────────────────────────────────────────────────

def _write_default_portals():
    PORTALS.write_text("""# Job Portal Configuration
# Edit this file to customize your target companies and role filters.

title_filter:
  positive:
    - engineer
    - developer
    - architect
    - platform
    - infrastructure
    - backend
    - fullstack
    - staff
    - principal
    - senior
  negative:
    - intern
    - junior
    - "entry level"
    - manager    # remove this line if targeting EM roles
    - recruiter

companies:
  # AI / Developer Tools
  - name: Anthropic
    greenhouse_slug: anthropic
    tier: 1
  - name: OpenAI
    greenhouse_slug: openai
    tier: 1
  - name: Mistral AI
    lever_slug: mistral
    tier: 1
  - name: Cohere
    greenhouse_slug: cohere
    tier: 1
  - name: Together AI
    ashby_slug: together-ai
    tier: 1
  - name: Replicate
    lever_slug: replicate
    tier: 2
  - name: Hugging Face
    lever_slug: hugging-face
    tier: 1
  - name: Groq
    ashby_slug: groq
    tier: 1

  # Developer Infrastructure
  - name: Vercel
    lever_slug: vercel
    tier: 1
  - name: Railway
    ashby_slug: railway
    tier: 2
  - name: Render
    lever_slug: render
    tier: 2
  - name: Fly.io
    lever_slug: fly-io
    tier: 2
  - name: Cloudflare
    greenhouse_slug: cloudflare
    tier: 1
  - name: Fastly
    greenhouse_slug: fastly
    tier: 2
  - name: PlanetScale
    lever_slug: planetscale
    tier: 2

  # Product / SaaS
  - name: Linear
    ashby_slug: linear
    tier: 1
  - name: Notion
    greenhouse_slug: notion
    tier: 1
  - name: Loom
    greenhouse_slug: loom
    tier: 2
  - name: Retool
    greenhouse_slug: retool
    tier: 1
  - name: Airtable
    greenhouse_slug: airtable
    tier: 2
  - name: Figma
    greenhouse_slug: figma
    tier: 1

  # Fintech
  - name: Stripe
    greenhouse_slug: stripe
    tier: 1
  - name: Plaid
    greenhouse_slug: plaid
    tier: 1
  - name: Brex
    greenhouse_slug: brex
    tier: 2
  - name: Mercury
    greenhouse_slug: mercury
    tier: 2

  # Growth-stage / custom career pages
  - name: ElevenLabs
    ashby_slug: elevenlabs
    tier: 1
  - name: Cursor
    ashby_slug: anysphere
    tier: 1
  - name: n8n
    ashby_slug: n8n
    tier: 2
  - name: Descript
    lever_slug: descript
    tier: 2

  # Examples using Workable, Wellfound, or custom career pages:
  # - name: Acme Corp
  #   workable_slug: acme-corp        # from apply.workable.com/acme-corp
  #   tier: 2
  # - name: YC Startup
  #   wellfound_slug: yc-startup      # from wellfound.com/company/yc-startup
  #   tier: 2
  # - name: Custom Company
  #   career_url: https://company.com/careers   # Playwright scrapes this page
  #   tier: 2
""")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if not args:
        cmd_interactive()
    elif args[0] == "setup":
        cmd_setup()
    elif args[0] == "scan":
        company = args[1] if len(args) > 1 else None
        cmd_scan(company)
    elif args[0] == "pipeline":
        limit = 20
        workers = 2
        for i, a in enumerate(args):
            if a == "--limit" and i + 1 < len(args):
                try: limit = int(args[i + 1])
                except ValueError: pass
            if a == "--workers" and i + 1 < len(args):
                try: workers = int(args[i + 1])
                except ValueError: pass
        cmd_pipeline(limit=limit, workers=workers)
    elif args[0] == "evaluate" and len(args) > 1:
        cmd_evaluate(" ".join(args[1:]))
    elif args[0] == "tracker":
        status = None
        grade  = None
        stats  = "--stats" in args
        for i, a in enumerate(args):
            if a == "--status" and i + 1 < len(args):
                status = args[i + 1]
            if a == "--grade" and i + 1 < len(args):
                grade = args[i + 1]
        cmd_tracker(status_filter=status, grade_filter=grade, stats=stats)
    elif args[0] == "interview" and len(args) > 1:
        cmd_interview(int(args[1]))
    elif args[0] == "negotiate" and len(args) > 1:
        cmd_negotiate(int(args[1]))
    elif args[0] == "deep" and len(args) > 1:
        cmd_deep(" ".join(args[1:]))
    elif args[0] == "verify" and len(args) > 1:
        cmd_verify(" ".join(args[1:]))
    elif args[0] == "status":
        cmd_status()
    elif args[0] == "batch" and len(args) > 1:
        # Read URLs from file, run pipeline
        urls = Path(args[1]).read_text().splitlines()
        PIPELINE.parent.mkdir(exist_ok=True)
        pipeline_text = PIPELINE.read_text() if PIPELINE.exists() else "# Pipeline\n\n## Pending\n\n## Processed\n"
        urls_block = "\n".join(f"- {u.strip()}" for u in urls if u.strip())
        pipeline_text = pipeline_text.replace("## Pending\n", f"## Pending\n{urls_block}\n")
        PIPELINE.write_text(pipeline_text)
        cmd_pipeline()
    else:
        # Treat the whole arg as a URL / JD
        cmd_evaluate(" ".join(args))
