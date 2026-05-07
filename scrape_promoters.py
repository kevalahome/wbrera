"""
WB RERA Promoter Name Scraper
==============================
Fetches the promoter/developer/builder name for every project from the
official WB RERA portal using the procode already stored in approved.json.

Usage (Windows Command Prompt, inside your repo folder):
    pip install requests beautifulsoup4
    python scrape_promoters.py

Output:
    data/approved.json   — updated in-place with promoter_name field
    promoter_cache.json  — progress cache (safe to re-run if interrupted)

Features:
  - Resumes from where it left off if interrupted
  - Polite rate limiting (1.5 sec between requests)
  - Retries on network errors
  - Progress bar printed to console
  - Never overwrites data already fetched
"""

import json
import time
import re
import os
import sys
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Installing required packages...")
    os.system(f"{sys.executable} -m pip install requests beautifulsoup4")
    import requests
    from bs4 import BeautifulSoup

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL      = "https://rera.wb.gov.in/project_details.php?procode={}"
DELAY_SEC     = 1.5      # seconds between requests — be polite to the server
RETRY_LIMIT   = 3        # retries per failed request
RETRY_WAIT    = 5        # seconds to wait before retry
CACHE_FILE    = "promoter_cache.json"
APPROVED_FILE = "data/approved.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ── Scraping logic ────────────────────────────────────────────────────────────
def extract_promoter(html: str) -> str | None:
    """
    Parse the WB RERA project detail page and extract promoter name.
    The page has a table with label/value pairs — we look for the
    'Name of Promoter' or 'Promoter Name' row.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Strategy 1: look for table rows with promoter label
    PROMOTER_LABELS = [
        "name of promoter", "promoter name", "name of the promoter",
        "promoter / developer", "developer name", "name of developer",
        "firm name", "name of firm", "applicant name"
    ]
    for row in soup.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) >= 2:
            label = cells[0].get_text(strip=True).lower()
            if any(kw in label for kw in PROMOTER_LABELS):
                val = cells[1].get_text(strip=True)
                val = re.sub(r'\s+', ' ', val).strip()
                if val and len(val) > 2 and val.upper() not in ("NA", "N/A", "NIL", "-"):
                    return val

    # Strategy 2: look for definition lists or labeled divs
    for el in soup.find_all(["dt", "label", "strong", "b"]):
        text = el.get_text(strip=True).lower()
        if any(kw in text for kw in PROMOTER_LABELS):
            nxt = el.find_next_sibling()
            if nxt:
                val = nxt.get_text(strip=True)
                val = re.sub(r'\s+', ' ', val).strip()
                if val and len(val) > 2:
                    return val

    # Strategy 3: scan all text for a line after "Promoter" keyword
    text_blocks = soup.get_text(separator="\n").split("\n")
    for i, line in enumerate(text_blocks):
        if any(kw in line.lower() for kw in ["promoter name", "name of promoter"]):
            for j in range(i + 1, min(i + 4, len(text_blocks))):
                candidate = text_blocks[j].strip()
                candidate = re.sub(r'\s+', ' ', candidate)
                if candidate and len(candidate) > 3 and not candidate.lower().startswith("name"):
                    return candidate

    return None


def fetch_promoter(session: requests.Session, procode: str) -> str | None:
    url = BASE_URL.format(procode)
    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            resp = session.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            return extract_promoter(resp.text)
        except requests.exceptions.Timeout:
            print(f"    Timeout (attempt {attempt}/{RETRY_LIMIT})")
        except requests.exceptions.HTTPError as e:
            print(f"    HTTP {e.response.status_code} (attempt {attempt}/{RETRY_LIMIT})")
        except requests.exceptions.ConnectionError:
            print(f"    Connection error (attempt {attempt}/{RETRY_LIMIT})")
        if attempt < RETRY_LIMIT:
            time.sleep(RETRY_WAIT)
    return None


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    # Load approved projects
    if not Path(APPROVED_FILE).exists():
        print(f"ERROR: {APPROVED_FILE} not found.")
        print("Make sure you're running this script from inside your repo folder.")
        sys.exit(1)

    with open(APPROVED_FILE, encoding="utf-8") as f:
        projects = json.load(f)

    # Load or create cache
    cache = {}
    if Path(CACHE_FILE).exists():
        with open(CACHE_FILE, encoding="utf-8") as f:
            cache = json.load(f)
        print(f"Resuming — {len(cache)} entries already cached.\n")

    # Build work list: projects with a procode that aren't cached yet
    todo = [
        p for p in projects
        if p.get("procode") and p["procode"] not in cache
    ]

    total    = len(projects)
    cached   = len(cache)
    to_scrape = len(todo)
    eta_min  = round(to_scrape * DELAY_SEC / 60, 1)

    print(f"Total projects  : {total}")
    print(f"Already cached  : {cached}")
    print(f"To scrape now   : {to_scrape}")
    print(f"Estimated time  : ~{eta_min} minutes at {DELAY_SEC}s/request")
    print(f"{'─' * 55}")

    if to_scrape == 0:
        print("Nothing left to scrape — applying cache to approved.json now.")
    else:
        session = requests.Session()
        for i, p in enumerate(todo, 1):
            procode = p["procode"]
            name    = p["name"]
            pct     = round((cached + i) * 100 / total)

            promoter = fetch_promoter(session, procode)
            cache[procode] = promoter or ""   # empty string = confirmed scraped, no data

            # Progress line
            status = f"✓ {promoter}" if promoter else "— not found"
            print(f"[{pct:3}%] {i}/{to_scrape}  {name[:35]:<35}  {status}")

            # Save cache every 25 records
            if i % 25 == 0 or i == to_scrape:
                with open(CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(cache, f, ensure_ascii=False, indent=2)

            time.sleep(DELAY_SEC)

        # Final cache save
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)

    # ── Apply cache to approved.json ──────────────────────────────────────────
    print(f"\n{'─' * 55}")
    print("Applying promoter names to approved.json...")

    filled = 0
    for p in projects:
        procode = p.get("procode", "")
        if procode and procode in cache and cache[procode]:
            p["promoter"] = cache[procode]
            filled += 1
        elif "promoter" not in p:
            p["promoter"] = None

    with open(APPROVED_FILE, "w", encoding="utf-8") as f:
        json.dump(projects, f, ensure_ascii=False, separators=(",", ":"))

    print(f"Done! Promoter name filled for {filled}/{total} projects.")
    print(f"      No name found for {total - filled} projects.")
    print(f"\nNext step: git add data/approved.json && git commit -m 'Add promoter names' && git push")


if __name__ == "__main__":
    main()
