#!/usr/bin/env python3
"""
career-ops daemon — runs on schedule via launchd.

Designed to run silently in the background while you sleep.
Handles: Ollama wakeup, scan, pipeline evaluation, notifications, logging.

Usage (called by launchd, not manually):
  python3 daemon.py [--scan-only] [--pipeline-only] [--force]

Logs: ~/.career-ops/logs/daemon.log  (rotated daily, kept 7 days)
"""

import os
import sys
import json
import time
import signal
import logging
import argparse
import subprocess
import traceback
from pathlib import Path
from datetime import datetime, date

import requests
import yaml

# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT        = Path(__file__).parent
LOG_DIR     = Path.home() / ".career-ops" / "logs"
STATE_FILE  = Path.home() / ".career-ops" / "daemon-state.json"
LOCK_FILE   = Path.home() / ".career-ops" / "daemon.lock"
PIPELINE    = ROOT / "data" / "pipeline.md"
HISTORY     = ROOT / "data" / "scan-history.tsv"
APPS        = ROOT / "data" / "applications.md"
PROFILE     = ROOT / "config" / "profile.yml"
PORTALS     = ROOT / "portals.yml"

LOG_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

OLLAMA_URL  = "http://localhost:11434"
MAX_RUNTIME = 45 * 60  # 45 min hard cap per run

# ── Logging ───────────────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    log_file = LOG_DIR / f"daemon-{date.today().isoformat()}.log"

    # Rotate: remove logs older than 7 days
    for old in LOG_DIR.glob("daemon-*.log"):
        try:
            log_date = datetime.strptime(old.stem.replace("daemon-", ""), "%Y-%m-%d").date()
            if (date.today() - log_date).days > 7:
                old.unlink()
        except Exception:
            pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ]
    )
    return logging.getLogger("career-ops-daemon")


log = setup_logging()

# ── State ─────────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


# ── Lock ──────────────────────────────────────────────────────────────────────

def acquire_lock() -> bool:
    """Prevent two daemon instances running at once."""
    if LOCK_FILE.exists():
        try:
            pid = int(LOCK_FILE.read_text().strip())
            # Check if that PID is still alive
            os.kill(pid, 0)
            log.warning(f"Daemon already running (PID {pid}). Exiting.")
            return False
        except (ProcessLookupError, ValueError):
            # Stale lock
            LOCK_FILE.unlink()
    LOCK_FILE.write_text(str(os.getpid()))
    return True


def release_lock():
    if LOCK_FILE.exists():
        LOCK_FILE.unlink()


# ── Ollama ────────────────────────────────────────────────────────────────────

def ensure_ollama(timeout: int = 30) -> bool:
    """Start Ollama if not running. Returns True when ready."""
    # Already running?
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        if r.ok:
            models = r.json().get("models", [])
            if models:
                log.info(f"Ollama running — model: {models[0]['name']}")
                return True
            log.warning("Ollama running but no models pulled.")
            return False
    except Exception:
        pass

    # Try to start it
    log.info("Ollama not running — attempting to start...")
    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
    except FileNotFoundError:
        log.error("ollama not found in PATH. Is Ollama installed?")
        notify("career-ops: Ollama not found",
               "Install Ollama from ollama.ai to enable background evaluations.")
        return False

    # Wait for Ollama to be ready
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(2)
        try:
            r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
            if r.ok:
                models = r.json().get("models", [])
                if models:
                    log.info(f"Ollama started — model: {models[0]['name']}")
                    return True
        except Exception:
            pass

    log.error("Ollama did not start within timeout.")
    return False


# ── Notifications ─────────────────────────────────────────────────────────────

def notify(title: str, body: str):
    """Send a macOS notification."""
    try:
        script = f'display notification "{body}" with title "{title}" sound name "Ping"'
        subprocess.run(
            ["osascript", "-e", script],
            check=False, capture_output=True, timeout=5
        )
        log.info(f"Notification sent: {title}")
    except Exception as e:
        log.debug(f"Notification failed (non-critical): {e}")


# ── Schedule check ────────────────────────────────────────────────────────────

def should_scan(state: dict, config: dict) -> bool:
    """Return True if it's time to scan based on schedule config."""
    interval_hours = config.get("scan_interval_hours", 12)
    last_scan = state.get("last_scan_at")
    if not last_scan:
        return True
    try:
        last = datetime.fromisoformat(last_scan)
        elapsed_hours = (datetime.now() - last).total_seconds() / 3600
        return elapsed_hours >= interval_hours
    except Exception:
        return True


def should_run_pipeline(state: dict, config: dict) -> bool:
    """Return True if there are pending URLs to evaluate."""
    if not PIPELINE.exists():
        return False
    text = PIPELINE.read_text()
    import re
    pending_m = re.search(r"## Pending\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    if not pending_m:
        return False
    urls = [l.strip() for l in pending_m.group(1).strip().splitlines()
            if l.strip() and not l.strip().startswith("#")]
    return len(urls) > 0


# ── Scan ──────────────────────────────────────────────────────────────────────

def run_scan(config: dict) -> dict:
    """Run portal scan. Returns {new_jobs: int, companies_scanned: int}."""
    sys.path.insert(0, str(ROOT))
    from scraper import scan_portal
    from ops import _load_portals
    import re

    portals_cfg = _load_portals()
    if not portals_cfg:
        log.warning("portals.yml not found — skipping scan")
        return {"new_jobs": 0, "companies_scanned": 0}

    companies = portals_cfg.get("companies", [])
    title_pos = portals_cfg.get("title_filter", {}).get("positive", [])
    title_neg = portals_cfg.get("title_filter", {}).get("negative", [])
    max_per_run = config.get("max_new_jobs_per_scan", 20)

    # Load seen URLs
    seen_urls = set()
    if HISTORY.exists():
        for line in HISTORY.read_text().splitlines():
            parts = line.split("\t")
            if parts:
                seen_urls.add(parts[0].strip())

    all_new = []
    scanned = 0

    for company in companies:
        name = company.get("name", "")

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
            try:
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
                    all_new.append(j)
                    seen_urls.add(url)
            except Exception as e:
                log.debug(f"Scan error {name}/{portal}: {e}")
            time.sleep(0.4)

        # Custom career page — Playwright powered
        career_url = company.get("career_url")
        if career_url:
            try:
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
                    all_new.append(j)
                    seen_urls.add(url)
            except Exception as e:
                log.debug(f"Custom scan error {name}: {e}")

        scanned += 1

    if not all_new:
        log.info(f"Scan complete — {scanned} companies, 0 new jobs")
        return {"new_jobs": 0, "companies_scanned": scanned}

    # Append new URLs to pipeline.md
    if not PIPELINE.exists():
        PIPELINE.write_text("# Pipeline — Pending Evaluation\n\n## Pending\n\n## Processed\n")

    pipeline_text = PIPELINE.read_text()
    urls_block = "\n".join(f"- {j['url']}" for j in all_new[:max_per_run])
    pipeline_text = pipeline_text.replace("## Pending\n", f"## Pending\n{urls_block}\n")
    PIPELINE.write_text(pipeline_text)

    # Update history
    with open(HISTORY, "a") as f:
        for j in all_new:
            f.write(f"{j['url']}\t{date.today().isoformat()}\t{j['company']}\t{j['title']}\n")

    # Log summary
    companies_found = {}
    for j in all_new:
        companies_found.setdefault(j["company"], []).append(j["title"])
    for company, titles in companies_found.items():
        log.info(f"  {company}: {len(titles)} new — {', '.join(titles[:3])}")

    log.info(f"Scan complete — {scanned} companies, {len(all_new)} new jobs added to pipeline")
    return {"new_jobs": len(all_new), "companies_scanned": scanned, "found": companies_found}


# ── Pipeline ──────────────────────────────────────────────────────────────────

def run_pipeline(config: dict) -> dict:
    """Evaluate all pending URLs. Returns summary dict."""
    import re
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    sys.path.insert(0, str(ROOT))
    from scraper import fetch_jd
    from ops import evaluate_and_report, merge_tracker

    if not PIPELINE.exists():
        return {"evaluated": 0}

    text = PIPELINE.read_text()
    pending_m = re.search(r"## Pending\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    if not pending_m:
        return {"evaluated": 0}

    urls = [l.lstrip("- ").strip() for l in pending_m.group(1).strip().splitlines()
            if l.strip() and not l.strip().startswith("#")]

    if not urls:
        return {"evaluated": 0}

    max_batch = config.get("max_evaluations_per_run", 8)
    urls = urls[:max_batch]
    workers = config.get("parallel_workers", 2)

    log.info(f"Pipeline: evaluating {len(urls)} URLs ({workers} parallel workers)")

    results = []
    lock = threading.Lock()
    start_time = time.time()

    def process(url):
        # Hard time cap per URL
        try:
            jd, company, title, clean_url = fetch_jd(url)
            if jd.startswith("[CLOSED]") or "no longer available" in jd.lower():
                log.info(f"Skipping closed listing: {url}")
                return None
            if jd.startswith("["):
                log.warning(f"Could not fetch JD: {url}")
                return None
            result = evaluate_and_report(jd, company, title, clean_url or url)
            with lock:
                log.info(f"  Evaluated: {company} — {title} → {result.get('score', 0):.1f}/5 ({result.get('grade', '?')})")
            return result
        except Exception as e:
            log.error(f"Evaluation error for {url}: {e}")
            return None

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process, url): url for url in urls}
        for future in as_completed(futures, timeout=MAX_RUNTIME - 60):
            r = future.result()
            if r:
                results.append(r)
            # Check overall time cap
            if time.time() - start_time > MAX_RUNTIME - 120:
                log.warning("Approaching time cap — stopping pipeline early")
                executor.shutdown(wait=False, cancel_futures=True)
                break

    # Merge tracker
    merge_tracker()
    log.info(f"Tracker merged — {len(results)} new entries")

    # Move processed URLs
    processed_block = "\n".join(f"- {u}" for u in urls[:len(results) + 1])
    new_text = text.replace(
        pending_m.group(1),
        "\n"
    ).replace("## Processed\n", f"## Processed\n{processed_block}\n")
    PIPELINE.write_text(new_text)

    grades = [r.get("grade", "?") for r in results]
    a_b = [r for r in results if r.get("grade") in ("A", "B")]

    return {
        "evaluated": len(results),
        "grades": grades,
        "top_picks": [f"{r['company']} — {r['title']} ({r['score']:.1f}/5)" for r in a_b],
    }


# ── Main run ──────────────────────────────────────────────────────────────────

def run(args):
    start = time.time()
    log.info("=" * 60)
    log.info(f"career-ops daemon starting  (PID {os.getpid()})")
    log.info("=" * 60)

    # Load config
    config = {}
    if PROFILE.exists():
        with open(PROFILE) as f:
            profile = yaml.safe_load(f) or {}
        config = profile.get("daemon", {})

    state = load_state()

    # Ensure Ollama is up
    if not ensure_ollama(timeout=30):
        log.error("Ollama unavailable — aborting run")
        save_state({**state, "last_error": "ollama_unavailable", "last_attempt": datetime.now().isoformat()})
        return

    scan_results     = {}
    pipeline_results = {}
    run_scan_flag     = (not args.pipeline_only) and (args.force or should_scan(state, config))
    run_pipeline_flag = (not args.scan_only) and should_run_pipeline(state, config)

    # ── Scan
    if run_scan_flag:
        log.info("── Phase 1: Scan ──────────────────────────────────────")
        try:
            scan_results = run_scan(config)
            state["last_scan_at"] = datetime.now().isoformat()
            state["last_scan_found"] = scan_results.get("new_jobs", 0)
            save_state(state)

            if scan_results.get("new_jobs", 0) > 0:
                found = scan_results.get("found", {})
                summary_lines = [f"{c}: {len(t)} jobs" for c, t in list(found.items())[:4]]
                notify(
                    f"career-ops: {scan_results['new_jobs']} new openings found",
                    ", ".join(summary_lines) + (" + more" if len(found) > 4 else "")
                )
        except Exception as e:
            log.error(f"Scan phase failed: {e}\n{traceback.format_exc()}")
    else:
        reason = "pipeline-only mode" if args.pipeline_only else "not due yet"
        log.info(f"Scan skipped ({reason})")

    # ── Pipeline
    if run_pipeline_flag or (scan_results.get("new_jobs", 0) > 0 and not args.scan_only):
        log.info("── Phase 2: Pipeline ──────────────────────────────────")
        try:
            pipeline_results = run_pipeline(config)
            state["last_pipeline_at"] = datetime.now().isoformat()
            state["last_evaluated"] = pipeline_results.get("evaluated", 0)
            save_state(state)

            ev = pipeline_results.get("evaluated", 0)
            top = pipeline_results.get("top_picks", [])
            if ev > 0:
                if top:
                    notify(
                        f"career-ops: {ev} offers evaluated",
                        f"Top picks: {' | '.join(top[:2])}"
                    )
                else:
                    notify(
                        f"career-ops: {ev} offers evaluated",
                        f"Grades: {', '.join(pipeline_results.get('grades', []))}"
                    )
        except Exception as e:
            log.error(f"Pipeline phase failed: {e}\n{traceback.format_exc()}")
    else:
        log.info("Pipeline skipped (no pending URLs)")

    elapsed = time.time() - start
    log.info(f"Run complete in {elapsed:.0f}s")
    log.info(f"  Scanned: {scan_results.get('companies_scanned', 0)} companies, "
             f"{scan_results.get('new_jobs', 0)} new jobs")
    log.info(f"  Evaluated: {pipeline_results.get('evaluated', 0)} offers")

    state["last_run_at"]      = datetime.now().isoformat()
    state["last_run_elapsed"] = f"{elapsed:.0f}s"
    save_state(state)

    log.info("=" * 60)


# ── Entry ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="career-ops background daemon")
    parser.add_argument("--scan-only",     action="store_true", help="Only scan, don't evaluate")
    parser.add_argument("--pipeline-only", action="store_true", help="Only evaluate pipeline, don't scan")
    parser.add_argument("--force",         action="store_true", help="Ignore schedule, run now")
    args = parser.parse_args()

    if not acquire_lock():
        sys.exit(0)

    def handle_signal(sig, frame):
        log.warning(f"Received signal {sig} — shutting down cleanly")
        release_lock()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT,  handle_signal)

    try:
        run(args)
    finally:
        release_lock()


if __name__ == "__main__":
    main()
