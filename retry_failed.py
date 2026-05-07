"""
retry_failed.py — Re-runs only the projects that failed in the main scraper.
Run this after the main scraper completes.

    python retry_failed.py
"""

import json
import asyncio
from pathlib import Path
from scraper import scrape_project, download_pdf, save_json, load_json, sleep, DATA_DIR, CERT_DIR
from playwright.async_api import async_playwright
import logging

log = logging.getLogger(__name__)

async def main():
    failed = load_json(DATA_DIR / "failed.json", [])
    if not failed:
        print("No failed projects to retry.")
        return

    print(f"Retrying {len(failed)} failed projects...")
    still_failed = []
    projects = load_json(DATA_DIR / "projects.json", [])
    done_set = set(load_json(DATA_DIR / "progress.json", {}).get("done", []))

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--ignore-certificate-errors"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
        page = await context.new_page()

        for procode in failed:
            sleep()
            project = await scrape_project(page, procode)
            if project is None:
                still_failed.append(procode)
                continue
            projects.append(project)
            cert_url = project.get("certificate_url")
            if cert_url:
                ok = download_pdf(cert_url, project["rera_reg_no"], project.get("project_name",""))
                if ok:
                    done_set.add(procode)
                    print(f"✓ {project['rera_reg_no']}")
                else:
                    still_failed.append(procode)
            else:
                done_set.add(procode)

        await browser.close()

    save_json(DATA_DIR / "failed.json", still_failed)
    save_json(DATA_DIR / "projects.json", projects)
    save_json(DATA_DIR / "progress.json", {"done": list(done_set), "failed": still_failed})
    print(f"\nRetry complete. {len(done_set)} done, {len(still_failed)} still failing.")

if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings()
    asyncio.run(main())
