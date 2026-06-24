"""
WBRERA Project Metadata Scraper v2
====================================
Scrapes all project details from WB RERA portal.

Improvements over v1:
- Targets specific HTML elements instead of raw body_text regex
- Correctly extracts project_name from <h2> in .overview section
- Correctly extracts promoter from the promoter table
- Extracts project_address, google_maps_url, certificate_url
- Skips projects where project_name already exists (incremental mode)
- Saves output to projects_cleaned.json (not projects.json)

Usage:
    pip install playwright tqdm
    playwright install chromium
    python scraper.py

Output:
    data/projects_cleaned.json  — clean scraped project metadata
    data/procodes.json          — cached list of all project procodes
    data/progress_v2.json       — checkpoint (reruns skip completed projects)
    data/failed_v2.json         — procodes that failed after all retries
"""

import asyncio
import json
import re
import time
import random
import logging
from pathlib import Path
from datetime import datetime

from tqdm import tqdm
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL        = "https://rera.wb.gov.in"
LIST_URL        = f"{BASE_URL}/district_project.php?dcode=0"
DETAIL_URL      = f"{BASE_URL}/project_details.php?procode={{procode}}"
DATA_DIR        = Path("data")
PROGRESS_FILE   = DATA_DIR / "progress_v2.json"
OUTPUT_FILE     = DATA_DIR / "projects_cleaned.json"
FAILED_FILE     = DATA_DIR / "failed_v2.json"
PROCODES_FILE   = DATA_DIR / "procodes.json"

DELAY_MIN       = 1.5   # be respectful to the govt server
DELAY_MAX       = 3.5
MAX_RETRIES     = 3
HEADLESS        = True

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────
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

def clean(text: str) -> str:
    """Strip whitespace and trailing junk from scraped text."""
    return re.sub(r'\s+', ' ', (text or "")).strip()


# ── Stage 1: Collect all procodes ─────────────────────────────────────────────
async def collect_procodes(page) -> list:
    """Navigates all listing pages and collects every procode."""
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

        # Try standard DataTables next button first, then text fallback
        next_btn = await page.query_selector("a.paginate_button.next:not(.disabled)")
        if not next_btn:
            next_btn = await page.query_selector("a:has-text('Next'):not(.disabled)")
        if not next_btn:
            log.info("No more pages — collection complete.")
            break

        await next_btn.click()
        await page.wait_for_timeout(1500)
        page_num += 1

    log.info(f"Total procodes collected: {len(procodes)}")
    return list(set(procodes))


# ── Stage 2: Scrape a single project detail page ──────────────────────────────
async def scrape_project(page, procode: str) -> dict | None:
    """
    Visits the project detail page and extracts fields using
    targeted CSS selectors rather than raw body_text regex.
    """
    url = DETAIL_URL.format(procode=procode)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(1500)

            data = {
                "procode":          procode,
                "source_url":       url,
                "scraped_at":       datetime.utcnow().isoformat(),
                # Fields to be populated below
                "project_name":     "",
                "rera_reg_no":      "",
                "project_id":       "",
                "project_status":   "",
                "completion_date":  "",
                "extension_date":   "",
                "project_type":     "",
                "district":         "",
                "project_address":  "",
                "pin_code":         "",
                "google_maps_url":  "",
                "certificate_url":  "",
                "land_area_sqm":    "",
                "builtup_area_sqm": "",
                "carpet_area_sqm":  "",
                "total_units":      "",
                "promoter_name":    "",
                "firm_name":        "",
                "promoter_address": "",
                "amenities":        [],
                "facilities":       [],
            }

            # ── Project name ─────────────────────────────────────────────────
            # Located in <h2> inside the .overview section
            name_el = await page.query_selector("section.overview h2")
            if name_el:
                data["project_name"] = clean(await name_el.inner_text())

            # ── Status block (the <ul class="outerrera"> list) ───────────────
            # Contains: PROJECT STATUS, PROJECT ID, COMPLETION DATE,
            #           EXTENSION DATE, RERA REG NO, and certificate link
            status_items = await page.query_selector_all("ul.outerrera li")
            for item in status_items:
                text = clean(await item.inner_text())

                if text.upper().startswith("PROJECT STATUS"):
                    # "PROJECT STATUS - Not Started"
                    m = re.search(r"PROJECT STATUS\s*[-–:]\s*(.+)", text, re.IGNORECASE)
                    data["project_status"] = clean(m.group(1)) if m else ""

                elif text.upper().startswith("PROJECT ID"):
                    m = re.search(r"PROJECT ID[:\s]*(.+)", text, re.IGNORECASE)
                    data["project_id"] = clean(m.group(1)) if m else ""

                elif "COMPLETION DATE" in text.upper() and "EXTENSION" not in text.upper():
                    m = re.search(r"PROJECT COMPLETION DATE[:\s]*(.+)", text, re.IGNORECASE)
                    data["completion_date"] = clean(m.group(1)) if m else ""

                elif "EXTENSION COMPLETION DATE" in text.upper():
                    m = re.search(r"EXTENSION COMPLETION DATE[:\s]*(.+)", text, re.IGNORECASE)
                    val = clean(m.group(1)) if m else ""
                    data["extension_date"] = None if val.upper() == "NA" else val

                elif "RERA REGISTRATION NO" in text.upper():
                    m = re.search(r"RERA REGISTRATION NO\.?[:\s]*(.+)", text, re.IGNORECASE)
                    data["rera_reg_no"] = clean(m.group(1)) if m else ""

                # Certificate PDF URL — from the VIEW CERTIFICATE anchor
                cert_link = await item.query_selector("a[href*='.pdf'], a[href*='/PDF/']")
                if cert_link:
                    href = await cert_link.get_attribute("href")
                    if href:
                        data["certificate_url"] = href.strip()

            # ── Project info (district, address, pincode) ────────────────────
            # projectDataTable is commented out on most pages, so we always
            # parse the locationmap h5 block which looks like:
            # "Street Address\nArea\nPS. Rajarhat\nDist. North 24-Parganas\nPin 700135"
            loc_el = await page.query_selector("section.locationmap h5")
            if loc_el:
                loc_text = clean(await loc_el.inner_text())
                # Pin code
                pin_m = re.search(r"Pin\s+(\d{6})", loc_text, re.IGNORECASE)
                if pin_m:
                    data["pin_code"] = pin_m.group(1)
                # District — text after "Dist." up to end of that segment
                dist_m = re.search(r"Dist\.?\s+([^,\n\r]+)", loc_text, re.IGNORECASE)
                if dist_m:
                    # Strip any trailing pin that bled in e.g. "Kolkata Pin 700084"
                    dist_raw = re.sub(r'\s*Pin\s*\d{6}', '', dist_m.group(1), flags=re.IGNORECASE)
                    data["district"] = clean(dist_raw)
                # Project address — everything before the "PS." / "Dist." line
                # Split on newlines and take lines before police station / district
                lines = [l.strip() for l in re.split(r'[\n\r]+', loc_text) if l.strip()]
                addr_lines = []
                for line in lines:
                    if re.match(r'(PS\.?|P\.S\.?|Dist\.?|Pin\s)', line, re.IGNORECASE):
                        break
                    addr_lines.append(line)
                if addr_lines:
                    data["project_address"] = ", ".join(addr_lines)

            # ── Google Maps URL ───────────────────────────────────────────────
            maps_link = await page.query_selector(
                "section.locationmap a[href*='google.com/maps']"
            )
            if maps_link:
                data["google_maps_url"] = await maps_link.get_attribute("href") or ""

            # ── Specification section: areas and unit count ───────────────────
            # <span style="font-size:16px;font-weight:900;">Land Area:</span>
            # <span>16501 sq.mtr.</span>
            spec_section = await page.query_selector("section.specification")
            if spec_section:
                spec_text = clean(await spec_section.inner_text())

                land_m    = re.search(r"Land Area[:\s]*([\d,]+)\s*sq", spec_text, re.IGNORECASE)
                built_m   = re.search(r"Total Built Up Area[:\s]*([\d,]+)\s*sq", spec_text, re.IGNORECASE)
                carpet_m  = re.search(r"Carpet Area[:\s]*([\d,]+)\s*sq", spec_text, re.IGNORECASE)
                units_m   = re.search(r"No\.\s*of Apartments[:\s]*([\d,]+)", spec_text, re.IGNORECASE)
                type_m    = re.search(r"(Residential|Commercial|Mixed)", spec_text, re.IGNORECASE)

                data["land_area_sqm"]    = land_m.group(1).replace(",", "")   if land_m   else ""
                data["builtup_area_sqm"] = built_m.group(1).replace(",", "")  if built_m  else ""
                data["carpet_area_sqm"]  = carpet_m.group(1).replace(",", "") if carpet_m else ""
                data["total_units"]      = units_m.group(1).replace(",", "")  if units_m  else ""
                data["project_type"]     = type_m.group(1).capitalize()       if type_m   else ""

            # ── Promoter table ────────────────────────────────────────────────
            # Heading: "Promoter and other officials handling the project"
            # Table columns: Sl No | Promoter Name | Firm Name |
            #                Establishment Year | Contact | Email | Address
            # We take the first row (primary promoter)
            promoter_rows = await page.query_selector_all(
                "section.amenities table tbody tr"
            )
            # There are multiple tables (promoters, agents, documents).
            # The promoter table comes first. Walk sections to find the right one.
            promo_section = None
            amenity_sections = await page.query_selector_all("section.amenities")
            for sec in amenity_sections:
                heading_el = await sec.query_selector("h5")
                if heading_el:
                    heading = clean(await heading_el.inner_text()).upper()
                    if "PROMOTER" in heading:
                        promo_section = sec
                        break

            if promo_section:
                promo_rows = await promo_section.query_selector_all("tbody tr")
                if promo_rows:
                    first_row = promo_rows[0]
                    cells = await first_row.query_selector_all("td")
                    if len(cells) >= 2:
                        data["promoter_name"] = clean(await cells[1].inner_text())
                    if len(cells) >= 3:
                        data["firm_name"] = clean(await cells[2].inner_text())
                    if len(cells) >= 7:
                        data["promoter_address"] = clean(await cells[6].inner_text())

            # ── Fallback: "Promoter Details" personal information section ────
            # Present when the promoter table is empty ("Information not available yet")
            # Structure: <h3><span class="text-primary">COMPANY NAME</span></h3>
            #            <div class="lead">Address : ...</div>
            if not data["promoter_name"]:
                promo_detail = await page.query_selector(
                    "h3 span.text-primary"
                )
                if promo_detail:
                    data["promoter_name"] = clean(await promo_detail.inner_text())
                    data["firm_name"]     = data["promoter_name"]
                # Extract address from lead divs in that same section
                lead_divs = await page.query_selector_all(".lead")
                addr_parts = []
                for div in lead_divs:
                    txt = clean(await div.inner_text())
                    if txt.lower().startswith("address"):
                        val = re.sub(r'^address\s*:\s*', '', txt, flags=re.IGNORECASE)
                        addr_parts.append(val)
                    elif txt.lower().startswith("tehsil") or txt.lower().startswith("district"):
                        val = re.sub(r'^(tehsil|district)\s*:\s*', '', txt, flags=re.IGNORECASE)
                        addr_parts.append(val)
                if addr_parts and not data["promoter_address"]:
                    data["promoter_address"] = ", ".join(addr_parts)

            # ── Facilities ────────────────────────────────────────────────────
            facilities = []
            for sec in amenity_sections:
                heading_el = await sec.query_selector("h5")
                if heading_el:
                    heading = clean(await heading_el.inner_text()).upper()
                    if "FACILIT" in heading:
                        items = await sec.query_selector_all("span")
                        for item in items:
                            txt = clean(await item.inner_text())
                            if txt:
                                facilities.append(txt)
            data["facilities"] = facilities

            # ── Amenities ─────────────────────────────────────────────────────
            amenities = []
            for sec in amenity_sections:
                heading_el = await sec.query_selector("h5")
                if heading_el:
                    heading = clean(await heading_el.inner_text()).upper()
                    if "AMENITIES" in heading:
                        items = await sec.query_selector_all("span")
                        for item in items:
                            txt = clean(await item.inner_text())
                            if txt:
                                amenities.append(txt)
            data["amenities"] = amenities

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


# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    DATA_DIR.mkdir(exist_ok=True)

    # Load existing output — keyed by procode for fast lookup
    existing_list  = load_json(OUTPUT_FILE, [])
    existing_map   = {p["procode"]: p for p in existing_list if "procode" in p}

    progress = load_json(PROGRESS_FILE, {"done": [], "failed": []})
    done_set = set(progress["done"])
    failed   = progress.get("failed", [])

    log.info("=" * 60)
    log.info("WBRERA Scraper v2")
    log.info("=" * 60)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=HEADLESS,
            args=["--ignore-certificate-errors"]
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        # ── Stage 1: Get procodes ─────────────────────────────────────────────
        if PROCODES_FILE.exists():
            all_procodes = load_json(PROCODES_FILE, [])
            log.info(f"Loaded {len(all_procodes)} procodes from cache.")
        else:
            all_procodes = await collect_procodes(page)
            save_json(PROCODES_FILE, all_procodes)

        # ── Stage 2: Scrape only projects not yet done ────────────────────────
        # Skip if already has a non-empty, valid project_name in existing data
        def needs_scrape(procode):
            existing = existing_map.get(procode, {})
            # Re-scrape if project_name is missing or was incorrectly set
            # (old scraper set it to "WEST BENGAL REAL ESTATE..." page title)
            name = existing.get("project_name", "")
            if name and "WEST BENGAL" not in name.upper() and len(name) > 2:
                return False  # already clean, skip
            return True

        todo = [p for p in all_procodes if needs_scrape(p)]
        log.info(f"{len(todo)} projects to scrape ({len(all_procodes) - len(todo)} already clean).")

        results = {k: v for k, v in existing_map.items()}  # start with existing data

        for procode in tqdm(todo, desc="Scraping", unit="proj"):
            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

            project = await scrape_project(page, procode)

            if project is None:
                if procode not in failed:
                    failed.append(procode)
                log.warning(f"FAILED: {procode}")
            else:
                results[procode] = project
                done_set.add(procode)
                log.info(
                    f"✓ {project.get('rera_reg_no','?')} — "
                    f"{project.get('project_name','?')[:50]} — "
                    f"{project.get('promoter_name','?')[:30]}"
                )

            # Checkpoint every 50 projects
            if len(results) % 50 == 0:
                save_json(OUTPUT_FILE, list(results.values()))
                save_json(PROGRESS_FILE, {"done": list(done_set), "failed": failed})
                save_json(FAILED_FILE, failed)

        await browser.close()

    # Final save
    save_json(OUTPUT_FILE, list(results.values()))
    save_json(PROGRESS_FILE, {"done": list(done_set), "failed": failed})
    save_json(FAILED_FILE, failed)

    log.info("=" * 60)
    log.info(f"Done. {len(done_set)} succeeded, {len(failed)} failed.")
    log.info(f"Output: {OUTPUT_FILE.resolve()}")
    if failed:
        log.info(f"Re-run to retry {len(failed)} failed projects.")
    log.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
