"""
WBRERA Project Metadata Scraper
================================
Scrapes complete project details from WB RERA portal for all 4,251 projects.

Usage:
    pip install playwright requests tqdm
    playwright install chromium
    python scraper.py

Output:
    ./data/projects.json     — all scraped project metadata
    ./data/procodes.json     — list of all project IDs (Stage 1 cache)
    ./data/progress.json     — checkpoint so reruns skip done IDs
    ./data/failed.json       — IDs that need retry
"""

import asyncio
import json
import os
import re
import time
import random
import logging
from pathlib import Path
from datetime import datetime

from tqdm import tqdm
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

# ── Config ──────────────────────────────────────────────────────────────────
BASE_URL       = "https://rera.wb.gov.in"
LIST_URL       = f"{BASE_URL}/district_project.php?dcode=0"
DETAIL_URL     = f"{BASE_URL}/project_details.php?procode={{procode}}"
DATA_DIR       = Path("data")
PROGRESS_FILE  = DATA_DIR / "progress.json"
PROJECTS_FILE  = DATA_DIR / "projects.json"
FAILED_FILE    = DATA_DIR / "failed.json"

DELAY_MIN      = 0.8   # seconds between requests
DELAY_MAX      = 2.0
MAX_RETRIES    = 3
HEADLESS       = True

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────────
def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default

def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def sleep():
    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))


# ── Stage 1: Collect all procodes ───────────────────────────────────────────
async def collect_procodes(page) -> list[str]:
    """Navigates the listing page and scrapes every procode from 'View Details' links."""
    procodes = []
    log.info("Stage 1: Collecting procodes from listing pages...")

    await page.goto(LIST_URL, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(2000)

    page_num = 1
    while True:
        links = await page.query_selector_all("a[href*='procode=']")
        new_codes = []
        for link in links:
            href = await link.get_attribute("href")
            m = re.search(r"procode=(\d+)", href or "")
            if m:
                code = m.group(1)
                if code not in procodes:
                    new_codes.append(code)

        procodes.extend(new_codes)
        log.info(f"  Page {page_num}: {len(new_codes)} projects (total: {len(procodes)})")

        next_btn = await page.query_selector("a.paginate_button.next:not(.disabled)")
        if not next_btn:
            next_btn = await page.query_selector("a:has-text('Next'):not(.disabled)")
        if not next_btn:
            log.info("No more pages — collection complete.")
            break

        await next_btn.click()
        await page.wait_for_timeout(1500)
        page_num += 1

    log.info(f"Total procodes: {len(procodes)}")
    return list(set(procodes))


# ── Stage 2: Scrape project detail page ─────────────────────────────────────
async def scrape_project(page, procode: str) -> dict | None:
    """Visits project detail page and extracts all available metadata."""
    url = DETAIL_URL.format(procode=procode)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(1500)

            data = {"procode": procode, "source_url": url, "scraped_at": datetime.utcnow().isoformat()}
            body_text = await page.inner_text("body")

            # Registration number
            reg_match = re.search(r"REGISTRATION\s*NO\.?\s*:?\s*(WBRERA/\S+)", body_text, re.IGNORECASE)
            if not reg_match:
                reg_match = re.search(r"(WBRERA/[A-Z]/[A-Z]+/\d{4}/\d+)", body_text)
            data["rera_reg_no"] = reg_match.group(1).strip() if reg_match else ""

            # Project name
            name_el = await page.query_selector("h2, h3, .proj_name, font b")
            data["project_name"] = (await name_el.inner_text()).strip() if name_el else ""

            # Project ID
            pid_match = re.search(r"PROJECT\s*ID\s*:?\s*(\S+)", body_text, re.IGNORECASE)
            data["project_id"] = pid_match.group(1).strip() if pid_match else ""

            # Status
            status_match = re.search(r"PROJECT\s*STATUS\s*[-:]\s*([^\n]+)", body_text, re.IGNORECASE)
            data["project_status"] = status_match.group(1).strip() if status_match else ""

            # Completion date
            comp_match = re.search(r"(?:COMPLETION\s*DATE|PROJECT\s*COMPLETION\s*DATE)\s*:?\s*([\d.]+)", body_text, re.IGNORECASE)
            data["completion_date"] = comp_match.group(1).strip() if comp_match else ""

            # Extension date
            ext_match = re.search(r"EXTENSION\s*COMPLETION\s*DATE\s*:?\s*([^\n]+)", body_text, re.IGNORECASE)
            data["extension_date"] = ext_match.group(1).strip() if ext_match else ""

            # Project type
            type_match = re.search(r"Project\s*Type\s*:?\s*([^\n]+)", body_text, re.IGNORECASE)
            data["project_type"] = type_match.group(1).strip() if type_match else ""

            # Land area
            land_match = re.search(r"Land\s*Area\s*:?\s*([\d,.]+)\s*sq", body_text, re.IGNORECASE)
            data["land_area_sqm"] = land_match.group(1).replace(",", "").strip() if land_match else ""

            # Built-up area
            built_match = re.search(r"(?:Total\s*)?Built\s*[Uu]p\s*Area\s*:?\s*([\d,.]+)\s*sq", body_text, re.IGNORECASE)
            data["builtup_area_sqm"] = built_match.group(1).replace(",", "").strip() if built_match else ""

            # Carpet area
            carpet_match = re.search(r"Carpet\s*Area\s*:?\s*([\d,.]+)\s*sq", body_text, re.IGNORECASE)
            data["carpet_area_sqm"] = carpet_match.group(1).replace(",", "").strip() if carpet_match else ""

            # Number of units
            units_match = re.search(r"(?:No\.?\s*of\s*Apartments|Total\s*Units)\s*:?\s*(\d+)", body_text, re.IGNORECASE)
            data["total_units"] = units_match.group(1).strip() if units_match else ""

            # Parking
            for pt in ["Covered Car Parking", "Mechanical Parking", "Open Parking", "Basement Parking"]:
                key = pt.lower().replace(" ", "_")
                m = re.search(rf"{pt}\s*:?\s*([\d,]+)", body_text, re.IGNORECASE)
                data[key] = m.group(1).replace(",", "").strip() if m else ""

            # Promoter
            promoter_match = re.search(r"Promoter\s*Name\s*:?\s*([^\n]+)", body_text, re.IGNORECASE)
            data["promoter_name"] = promoter_match.group(1).strip() if promoter_match else ""

            # Firm name
            firm_match = re.search(r"Firm\s*Name\s*:?\s*([^\n]+)", body_text, re.IGNORECASE)
            data["firm_name"] = firm_match.group(1).strip() if firm_match else ""

            # Establishment year
            est_match = re.search(r"Establishment\s*Year\s*:?\s*(\d{4})", body_text, re.IGNORECASE)
            data["establishment_year"] = est_match.group(1).strip() if est_match else ""

            # Contact
            contact_match = re.search(r"Contact\s*:?\s*([^\n]+)", body_text, re.IGNORECASE)
            data["contact"] = contact_match.group(1).strip() if contact_match else ""

            # Email
            email_match = re.search(r"Email\s*ID\s*:?\s*([^\s\n@]+@[^\s\n]+)", body_text, re.IGNORECASE)
            data["email"] = email_match.group(1).strip() if email_match else ""

            # Address
            addr_match = re.search(r"Address\s*:?\s*([^\n]+)", body_text, re.IGNORECASE)
            data["address"] = addr_match.group(1).strip() if addr_match else ""

            # Pin code
            pin_match = re.search(r"Pin\s*(\d{6})", body_text)
            data["pin_code"] = pin_match.group(1).strip() if pin_match else ""

            # Consultant
            cons_match = re.search(r"Consultant\s*Name\s*:?\s*([^\n]+)", body_text, re.IGNORECASE)
            data["consultant_name"] = cons_match.group(1).strip() if cons_match else ""

            return data

        except PWTimeout:
            log.warning(f"  Timeout on {procode} (attempt {attempt}/{MAX_RETRIES})")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(8)
        except Exception as e:
            log.warning(f"  Error on {procode} attempt {attempt}: {e}")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(4)

    return None


# ── Main ─────────────────────────────────────────────────────────────────────
async def main():
    DATA_DIR.mkdir(exist_ok=True)

    progress  = load_json(PROGRESS_FILE, {"done": [], "failed": []})
    projects  = load_json(PROJECTS_FILE, [])
    done_set  = set(progress["done"])
    failed    = progress["failed"]

    log.info("=" * 60)
    log.info("WBRERA Project Metadata Scraper")
    log.info("=" * 60)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=HEADLESS,
            args=["--ignore-certificate-errors"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        # ── Stage 1: Collect procodes ────────────────────────────────────
        procodes_file = DATA_DIR / "procodes.json"
        if procodes_file.exists():
            all_procodes = load_json(procodes_file, [])
            log.info(f"Loaded {len(all_procodes)} procodes from cache.")
        else:
            all_procodes = await collect_procodes(page)
            save_json(procodes_file, all_procodes)
            log.info(f"Saved {len(all_procodes)} procodes.")

        # ── Stage 2: Scrape metadata ─────────────────────────────────────
        todo = [p for p in all_procodes if p not in done_set]
        log.info(f"{len(todo)} projects to process ({len(done_set)} already done).")

        for procode in tqdm(todo, desc="Scraping", unit="proj"):
            sleep()

            project = await scrape_project(page, procode)

            if project is None:
                failed.append(procode)
                log.warning(f"FAILED: {procode}")
            else:
                projects.append(project)
                done_set.add(procode)
                name = project.get('project_name', '')[:50]
                rera = project.get('rera_reg_no', '')
                log.info(f"✓ {rera} — {name}")

            # Save checkpoint every 100 projects
            if len(projects) % 100 == 0:
                save_json(PROGRESS_FILE, {"done": list(done_set), "failed": failed})
                save_json(PROJECTS_FILE, projects)
                save_json(FAILED_FILE, failed)

        await browser.close()

    # Final save
    save_json(PROGRESS_FILE, {"done": list(done_set), "failed": failed})
    save_json(PROJECTS_FILE, projects)
    save_json(FAILED_FILE, failed)

    log.info("=" * 60)
    log.info(f"Done. {len(done_set)} succeeded, {len(failed)} failed.")
    log.info(f"Metadata saved to: {PROJECTS_FILE.resolve()}")
    if failed:
        log.info(f"Re-run to retry {len(failed)} failed projects.")
    log.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())