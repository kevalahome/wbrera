# WBRERA Certificate Bulk Downloader

Downloads all ~4,200 RERA registration certificate PDFs from rera.wb.gov.in,
plus structured JSON metadata for every project.

---

## Setup (5 minutes)

### 1. Install Python 3.10+
https://www.python.org/downloads/

### 2. Install dependencies
```bash
pip install playwright requests tqdm urllib3
playwright install chromium
```

### 3. Run the scraper
```bash
python scraper.py
```

### 4. If some projects failed (network blip, server timeout), retry them:
```bash
python retry_failed.py
```

---

## What it does

| Stage | What happens |
|-------|-------------|
| **Stage 1** | Opens Chrome (headless), loads the full project listing, clicks through every pagination page, collects all `procode` values. Saved to `data/procodes.json`. |
| **Stage 2** | For each procode, loads `project_details.php?procode=...`, extracts RERA reg number, project name, completion date, district, and the certificate PDF URL. |
| **Stage 3** | Downloads the PDF using `requests` (handles the legacy SSL cert that browsers warn about). Saves to `certificates/` named by RERA reg number. |

---

## Output

```
certificates/
  WBRERA_P_KOL_2023_000276 — devlok.pdf
  WBRERA_P_HWR_2022_000041 — sunrise heights.pdf
  ...

data/
  procodes.json      — list of all project IDs (Stage 1 cache)
  projects.json      — full metadata for every project
  failed.json        — procodes that need retry
  progress.json      — checkpoint (re-running skips already-done projects)
  scraper.log        — full log with timestamps
```

---

## Estimated time

- Stage 1 (collecting procodes): ~10–20 minutes depending on pagination
- Stage 2+3 (scraping + downloading, ~4,200 projects): **4–8 hours**
  - The `DELAY_MIN/DELAY_MAX` in `scraper.py` defaults to 1.5–3.5 seconds per project
  - This is intentional — the WB govt server is shared infrastructure
  - You can reduce to 0.8–1.5 if you're comfortable with faster requests

**You can stop and restart at any time.** `progress.json` is a checkpoint
file — rerunning skips all projects already marked done.

---

## Using the data in your app

`data/projects.json` contains one object per project:

```json
{
  "procode": "11790000000000",
  "rera_reg_no": "WBRERA/P/KOL/2023/000276",
  "project_name": "devlok",
  "completion_date": "31-12-2024",
  "project_type": "Residential",
  "district": "Kolkata",
  "promoter": "...",
  "certificate_url": "https://rera.wb.gov.in/...",
  "source_url": "https://rera.wb.gov.in/project_details.php?procode=11790000000000",
  "scraped_at": "2026-05-05T10:23:11"
}
```

You can load this JSON directly into your Google Sheet using the Apps Script
`importJSON` pattern, or serve it from GitHub as a static data file for the
RERA app.

---

## Troubleshooting

**"SSL certificate verify failed"** — handled automatically (`verify=False` in requests,
`--ignore-certificate-errors` in Playwright). The WB RERA server uses legacy
TLS renegotiation that modern clients flag; this is expected.

**"robots.txt disallowed"** — Playwright bypasses robots.txt as it runs a
real browser. The `requests` download also doesn't check robots.txt.
The scraper uses respectful delays (1.5–3.5s) to avoid overloading the server.

**Server goes down mid-run** — just re-run `scraper.py`. It picks up from
the checkpoint in `data/progress.json`.

**Certificate URL is None for some projects** — Some projects on the portal
don't yet have a certificate issued (registration pending or very recent).
Their metadata is still saved in `projects.json`.
