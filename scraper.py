"""
scraper.py — 3-tier job description fetcher and portal scanner.

Tier 1: ATS public APIs       (Greenhouse, Lever, Ashby, Workable, Wellfound)
Tier 2: requests + BS4        (static HTML, fast, no browser)
Tier 3: Playwright Chromium   (JS-rendered pages, Workday, custom career sites)

Also handles:
- Active listing verification  (is the job still open?)
- Custom career page scanning  (companies not on a standard ATS)
- Wellfound / AngelList jobs
"""

import re
import time
import logging
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

log = logging.getLogger("career-ops")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}

# Selectors tried in order when extracting JD text from HTML
JD_SELECTORS = [
    # ATS-specific
    "[data-automation='job-description']",      # Workday
    ".job-description__body",                    # Workday alt
    "#job-description",
    ".job-description",
    "[class*='JobDescription']",
    "[class*='job-description']",
    "[class*='jobDescription']",
    # Generic
    "article[class*='job']",
    "section[class*='job']",
    "div[class*='posting']",
    "div[class*='content']",
    "article",
    "main",
]

# Signs that a job is CLOSED (checked in page text/title)
CLOSED_SIGNALS = [
    "this job is no longer available",
    "this position has been filled",
    "job posting has expired",
    "no longer accepting applications",
    "position is closed",
    "this role is no longer",
    "job has been removed",
    "404",
]


# ── Tier 1: ATS APIs ─────────────────────────────────────────────────────────

def _api_greenhouse(url: str) -> Optional[tuple[str, str, str]]:
    """Returns (jd_text, company, title) or None."""
    try:
        parts = url.rstrip("/").split("/")
        job_id = parts[-1].split("?")[0]
        board = url.split("greenhouse.io/")[-1].split("/")[0]
        api = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}"
        r = requests.get(api, headers=HEADERS, timeout=10)
        if not r.ok:
            return None
        d = r.json()
        content = BeautifulSoup(d.get("content", ""), "html.parser").get_text("\n", strip=True)
        company = d.get("company", {}).get("name", "") or board.title()
        title = d.get("title", "")
        return f"{title}\n\n{content}", company, title
    except Exception:
        return None


def _api_lever(url: str) -> Optional[tuple[str, str, str]]:
    try:
        parts = url.rstrip("/").split("/")
        company = parts[-2] if len(parts) >= 2 else ""
        job_id = parts[-1].split("?")[0]
        api = f"https://api.lever.co/v0/postings/{company}/{job_id}"
        r = requests.get(api, headers=HEADERS, timeout=10)
        if not r.ok:
            return None
        d = r.json()
        desc = d.get("descriptionPlain", "")
        lists_text = ""
        for lst in d.get("lists", []):
            lists_text += f"\n{lst.get('text', '')}:\n"
            items = re.findall(r"<li>(.*?)</li>", lst.get("content", ""), re.DOTALL)
            for item in items:
                clean = BeautifulSoup(item, "html.parser").get_text(strip=True)
                lists_text += f"• {clean}\n"
        title = d.get("text", "")
        return f"{title}\n\n{desc}\n{lists_text}", company.replace("-", " ").title(), title
    except Exception:
        return None


def _api_ashby(url: str) -> Optional[tuple[str, str, str]]:
    try:
        slug = url.split("ashbyhq.com/")[-1].split("/")[0]
        job_id = url.rstrip("/").split("/")[-1].split("?")[0]
        api = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
        r = requests.get(api, headers=HEADERS, timeout=10)
        if not r.ok:
            return None
        for j in r.json().get("jobs", []):
            if j.get("id", "") in url or j.get("jobUrl", "") == url:
                desc = BeautifulSoup(j.get("descriptionHtml", ""), "html.parser").get_text("\n", strip=True)
                title = j.get("title", "")
                company = slug.replace("-", " ").title()
                return f"{title}\n\n{desc}", company, title
        return None
    except Exception:
        return None


def _api_workable(url: str) -> Optional[tuple[str, str, str]]:
    """Workable has a JSON view at the same URL with ?format=json or via API."""
    try:
        # Workable public API: apply.workable.com/company/j/SHORTCODE/
        m = re.search(r"apply\.workable\.com/([^/]+)/j/([^/]+)", url)
        if m:
            company_slug, job_code = m.group(1), m.group(2)
            api = f"https://apply.workable.com/api/v3/accounts/{company_slug}/jobs/{job_code}"
            r = requests.get(api, headers=HEADERS, timeout=10)
            if r.ok:
                d = r.json()
                desc = BeautifulSoup(d.get("description", ""), "html.parser").get_text("\n", strip=True)
                reqs = BeautifulSoup(d.get("requirements", ""), "html.parser").get_text("\n", strip=True)
                title = d.get("title", "")
                company = d.get("account", {}).get("name", company_slug.title())
                return f"{title}\n\n{desc}\n\nRequirements:\n{reqs}", company, title
        return None
    except Exception:
        return None


# ── Tier 2: requests + BS4 ───────────────────────────────────────────────────

def _scrape_static(url: str) -> Optional[tuple[str, str]]:
    """
    Returns (page_text, page_title) or None.
    Lightweight — no browser, no JS execution.
    """
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()

        # Skip binary content
        ct = r.headers.get("content-type", "")
        if "text" not in ct and "html" not in ct:
            return None

        soup = BeautifulSoup(r.text, "html.parser")
        page_title = soup.title.string.strip() if soup.title else ""

        # Check for closed signals early
        body_text = soup.get_text(" ", strip=True).lower()
        for signal in CLOSED_SIGNALS:
            if signal in body_text:
                return f"[CLOSED] {signal}", page_title

        # Strip chrome
        for tag in soup(["nav", "footer", "script", "style", "header", "aside", "noscript"]):
            tag.decompose()

        # Try targeted selectors
        for sel in JD_SELECTORS:
            el = soup.select_one(sel)
            if el:
                text = el.get_text("\n", strip=True)
                if len(text) > 400:
                    return text, page_title

        # Full body fallback
        text = soup.get_text("\n", strip=True)
        if len(text) > 400:
            return text[:8000], page_title

        return None
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            return "[CLOSED] 404 — page not found", ""
        return None
    except Exception:
        return None


# ── Tier 3: Playwright ───────────────────────────────────────────────────────

def _scrape_playwright(url: str, timeout_ms: int = 20000) -> Optional[tuple[str, str, bool]]:
    """
    Returns (jd_text, page_title, is_active) or None.
    Uses headless Chromium to handle JS-rendered pages.
    Handles: Workday, Rippling, custom career SPAs, any JS-heavy page.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        log.warning("Playwright not installed — skipping browser fallback")
        log.warning("Install with: pip install playwright && playwright install chromium")
        return None

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ]
            )
            ctx = browser.new_context(
                user_agent=UA,
                viewport={"width": 1280, "height": 900},
                locale="en-US",
            )
            page = ctx.new_page()

            # Block images/fonts/media to speed up loading
            page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,mp4,webm}", lambda r: r.abort())

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            except PWTimeout:
                log.debug(f"Playwright timeout on initial load: {url}")
                browser.close()
                return None

            # Wait for content to settle
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except PWTimeout:
                pass  # Proceed with what we have

            # Workday: click through modal if present
            try:
                page.click("[data-automation='close-button']", timeout=2000)
            except Exception:
                pass

            title = page.title()
            content = page.content()
            browser.close()

        soup = BeautifulSoup(content, "html.parser")

        # Active check
        visible_text = soup.get_text(" ", strip=True).lower()
        is_active = True
        for signal in CLOSED_SIGNALS:
            if signal in visible_text:
                is_active = False
                break

        # Strip chrome
        for tag in soup(["nav", "footer", "script", "style", "header", "aside", "noscript"]):
            tag.decompose()

        # Workday-specific extraction
        if "myworkdayjobs.com" in url or "wd" in url:
            for sel in [
                "[data-automation='job-posting-details']",
                "[data-automation='jobPostingDescription']",
                ".css-1g0fqss",  # common Workday class
                "[class*='jobPosting']",
            ]:
                el = soup.select_one(sel)
                if el and len(el.get_text(strip=True)) > 300:
                    return el.get_text("\n", strip=True), title, is_active

        # Rippling-specific
        if "rippling.com" in url:
            for sel in ["[class*='JobDescription']", "[class*='job-content']"]:
                el = soup.select_one(sel)
                if el and len(el.get_text(strip=True)) > 300:
                    return el.get_text("\n", strip=True), title, is_active

        # Generic selectors
        for sel in JD_SELECTORS:
            el = soup.select_one(sel)
            if el:
                text = el.get_text("\n", strip=True)
                if len(text) > 400:
                    return text, title, is_active

        # Full body
        text = soup.get_text("\n", strip=True)
        if len(text) > 400:
            return text[:8000], title, is_active

        return None

    except Exception as e:
        log.debug(f"Playwright error on {url}: {e}")
        return None


# ── Active listing verification ───────────────────────────────────────────────

def verify_active(url: str, use_playwright: bool = True) -> tuple[bool, str]:
    """
    Verify whether a job posting is still active.
    Returns (is_active, method_used).
    
    Always uses Playwright per career-ops original philosophy:
    "NEVER trust WebSearch/WebFetch to verify if an offer is still active."
    """
    if not url.startswith("http"):
        return True, "local"

    # Try Playwright first (most reliable)
    if use_playwright:
        result = _scrape_playwright(url, timeout_ms=15000)
        if result:
            _, _, is_active = result
            return is_active, "playwright"

    # Fallback: static check
    result = _scrape_static(url)
    if result:
        text, _ = result
        if text.startswith("[CLOSED]"):
            return False, "static"
        return True, "static"

    # Can't determine — assume active
    return True, "unknown"


# ── Main fetch_jd function ────────────────────────────────────────────────────

def fetch_jd(url_or_text: str) -> tuple[str, str, str, str]:
    """
    Main entry point. Returns (jd_text, company, title, url).

    Strategy:
      1. Local file / raw text — return immediately
      2. ATS API (Greenhouse, Lever, Ashby, Workable) — fast JSON
      3. requests + BeautifulSoup — static HTML
      4. Playwright Chromium — JS-rendered fallback
    """
    text = url_or_text.strip()

    # ── Local file
    if text.startswith("local:"):
        path = Path(__file__).parent / text[6:]
        if path.exists():
            jd = path.read_text()
            meta = _quick_meta(jd)
            return jd, meta["company"], meta["title"], str(path)
        return f"[File not found: {path}]", "", "", ""

    # ── Raw JD text (pasted, not a URL)
    if not text.startswith("http"):
        meta = _quick_meta(text)
        return text, meta["company"], meta["title"], ""

    url = text
    log.debug(f"Fetching: {url}")

    # ── Tier 1: ATS APIs
    result = None

    if "greenhouse.io" in url:
        result = _api_greenhouse(url)
        if result:
            log.debug("Fetched via Greenhouse API")
            jd, company, title = result
            return jd, company, title, url

    if "lever.co" in url:
        result = _api_lever(url)
        if result:
            log.debug("Fetched via Lever API")
            jd, company, title = result
            return jd, company, title, url

    if "ashbyhq.com" in url:
        result = _api_ashby(url)
        if result:
            log.debug("Fetched via Ashby API")
            jd, company, title = result
            return jd, company, title, url

    if "workable.com" in url:
        result = _api_workable(url)
        if result:
            log.debug("Fetched via Workable API")
            jd, company, title = result
            return jd, company, title, url

    # ── Tier 2: Static scrape
    static_result = _scrape_static(url)
    if static_result:
        page_text, page_title = static_result

        if page_text.startswith("[CLOSED]"):
            return f"[Job posting appears closed: {page_text}]", "", "", url

        # Check if we got a real JD (heuristic: mentions of requirements/responsibilities)
        text_lower = page_text.lower()
        jd_signals = ["responsibilities", "requirements", "qualifications",
                      "experience", "you will", "we are looking", "about the role"]
        signal_count = sum(1 for s in jd_signals if s in text_lower)

        if signal_count >= 2:
            meta = _quick_meta(page_text)
            # Prefer page title for company/title if meta extraction fails
            if meta["company"] == "Unknown" and page_title:
                parsed = _parse_page_title(page_title)
                meta.update(parsed)
            log.debug(f"Fetched via static scrape (signals: {signal_count})")
            return page_text, meta["company"], meta["title"], url

    # ── Tier 3: Playwright
    log.debug(f"Falling back to Playwright for: {url}")
    pw_result = _scrape_playwright(url)

    if pw_result:
        page_text, page_title, is_active = pw_result

        if not is_active:
            return f"[Job posting is closed — page indicates this role is no longer available]", "", "", url

        if len(page_text) > 300:
            meta = _quick_meta(page_text)
            if meta["company"] == "Unknown" and page_title:
                parsed = _parse_page_title(page_title)
                meta.update(parsed)
            log.debug("Fetched via Playwright")
            return page_text, meta["company"], meta["title"], url

    return "[Could not extract job description. Try pasting the JD text directly.]", "", "", url


# ── Portal scanner ────────────────────────────────────────────────────────────

def scan_portal(portal: str, slug: str, company_name: str,
                career_url: str = None) -> list[dict]:
    """
    Scan a single company/portal combination.
    Supports: greenhouse, lever, ashby, workable, wellfound, custom.
    """
    jobs = []

    try:
        if portal == "greenhouse":
            url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.ok:
                for j in r.json().get("jobs", []):
                    jobs.append({
                        "company": company_name,
                        "title":   j.get("title", ""),
                        "url":     j.get("absolute_url", ""),
                        "location": ", ".join(o.get("name", "") for o in j.get("offices", [])),
                        "portal":  "Greenhouse",
                    })

        elif portal == "lever":
            url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.ok:
                data = r.json()
                if isinstance(data, list):
                    for j in data:
                        jobs.append({
                            "company": company_name,
                            "title":   j.get("text", ""),
                            "url":     j.get("hostedUrl", ""),
                            "location": j.get("categories", {}).get("location", ""),
                            "portal":  "Lever",
                        })

        elif portal == "ashby":
            url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.ok:
                for j in r.json().get("jobs", []):
                    jobs.append({
                        "company": company_name,
                        "title":   j.get("title", ""),
                        "url":     j.get("jobUrl", ""),
                        "location": j.get("location", ""),
                        "portal":  "Ashby",
                    })

        elif portal == "workable":
            url = f"https://apply.workable.com/api/v3/accounts/{slug}/jobs"
            r = requests.post(url, json={"query": "", "location": [],
                                          "department": [], "worktype": []},
                              headers=HEADERS, timeout=10)
            if r.ok:
                for j in r.json().get("results", []):
                    jobs.append({
                        "company": company_name,
                        "title":   j.get("title", ""),
                        "url":     f"https://apply.workable.com/{slug}/j/{j.get('shortcode', '')}",
                        "location": j.get("location", {}).get("city", ""),
                        "portal":  "Workable",
                    })

        elif portal == "wellfound":
            # Wellfound (AngelList Talent) public search
            url = f"https://api.wellfound.com/graphql"
            query = {
                "query": """query JobListings($companySlug: String!) {
                    startup(slug: $companySlug) {
                        name
                        jobListings { title slug locationNames remote }
                    }
                }""",
                "variables": {"companySlug": slug}
            }
            r = requests.post(url, json=query, headers={**HEADERS,
                "Content-Type": "application/json"}, timeout=10)
            if r.ok:
                startup = r.json().get("data", {}).get("startup", {})
                cname = startup.get("name", company_name)
                for j in startup.get("jobListings", []):
                    jobs.append({
                        "company": cname,
                        "title":   j.get("title", ""),
                        "url":     f"https://wellfound.com/jobs/{j.get('slug', '')}",
                        "location": "Remote" if j.get("remote") else ", ".join(j.get("locationNames", [])),
                        "portal":  "Wellfound",
                    })

        elif portal == "custom" and career_url:
            # Playwright scan of a custom career page
            jobs = _scan_custom_careers_page(company_name, career_url)

    except Exception as e:
        log.debug(f"scan_portal error ({portal}/{slug}): {e}")

    return jobs


def _scan_custom_careers_page(company_name: str, career_url: str) -> list[dict]:
    """
    Use Playwright to scrape a custom careers page (not on a standard ATS).
    Finds all job links on the page.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        return []

    jobs = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(user_agent=UA)
            page.route("**/*.{png,jpg,gif,svg,woff,woff2,ttf,mp4}", lambda r: r.abort())

            try:
                page.goto(career_url, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_load_state("networkidle", timeout=8000)
            except PWTimeout:
                browser.close()
                return []

            content = page.content()
            browser.close()

        soup = BeautifulSoup(content, "html.parser")
        base = urlparse(career_url)
        base_url = f"{base.scheme}://{base.netloc}"

        # Find all links that look like job postings
        job_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            link_text = a.get_text(strip=True)

            # Skip nav/footer links
            if len(link_text) < 4 or len(link_text) > 120:
                continue

            # Normalize URL
            if href.startswith("/"):
                href = base_url + href
            elif not href.startswith("http"):
                continue

            # Job URL heuristics
            job_url_signals = ["job", "career", "position", "opening", "role", "posting"]
            href_lower = href.lower()
            if any(s in href_lower for s in job_url_signals):
                job_links.append((link_text, href))

        # Deduplicate
        seen = set()
        for title, url in job_links:
            if url not in seen:
                seen.add(url)
                jobs.append({
                    "company":  company_name,
                    "title":    title,
                    "url":      url,
                    "location": "",
                    "portal":   "Custom",
                })

        log.debug(f"Custom page scan ({company_name}): {len(jobs)} jobs found")

    except Exception as e:
        log.debug(f"Custom careers page error ({company_name}): {e}")

    return jobs


# ── Helpers ───────────────────────────────────────────────────────────────────

def _quick_meta(text: str) -> dict:
    """
    Fast heuristic extraction of company/title from JD text.
    No LLM call — used as a fallback when LLM is slow or not needed.
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    title = "Unknown"
    company = "Unknown"

    # Title: first substantial line that looks like a job title
    title_words = ["engineer", "developer", "manager", "director", "lead", "architect",
                   "analyst", "designer", "scientist", "product", "head of", "vp ", "staff"]
    for line in lines[:10]:
        if any(w in line.lower() for w in title_words) and len(line) < 100:
            title = line
            break

    # Company: look for "at Company" or "Company is hiring" patterns
    for line in lines[:15]:
        m = re.search(r"(?:at|@|join)\s+([A-Z][A-Za-z0-9\s&,.]+?)(?:\s*[-–|]|\s+is|\s+are|\.|$)", line)
        if m:
            candidate = m.group(1).strip().rstrip(".,")
            if 2 < len(candidate) < 50:
                company = candidate
                break

    return {"company": company, "title": title}


def _parse_page_title(page_title: str) -> dict:
    """
    Extract job title and company from HTML <title> tag.
    Common formats: "Title | Company", "Title at Company", "Company - Title"
    """
    result = {"company": "Unknown", "title": "Unknown"}
    if not page_title:
        return result

    page_title = re.sub(r"\s*(jobs?|careers?|openings?)\s*", " ", page_title, flags=re.IGNORECASE).strip()

    for sep in [" | ", " at ", " - ", " — ", " – ", " · "]:
        if sep in page_title:
            parts = [p.strip() for p in page_title.split(sep, 1)]
            if len(parts) == 2:
                left, right = parts[0], parts[1]
                # Heuristic: company names are usually shorter and contain
                # fewer job-title words. "Title | Company" is most common.
                job_words = ["engineer", "developer", "manager", "director",
                             "lead", "architect", "analyst", "designer",
                             "scientist", "product", "head", "staff", "senior",
                             "principal", "vp", "associate", "intern", "junior"]
                left_is_title = any(w in left.lower() for w in job_words)
                right_is_title = any(w in right.lower() for w in job_words)
                if left_is_title and not right_is_title:
                    result["title"] = left
                    result["company"] = right
                elif right_is_title and not left_is_title:
                    result["title"] = right
                    result["company"] = left
                else:
                    # Default: first part is title (most common page title format)
                    result["title"] = left
                    result["company"] = right
                return result

    result["title"] = page_title[:80]
    return result
