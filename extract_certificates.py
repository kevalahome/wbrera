#!/usr/bin/env python3
"""
RERA Certificate Extractor
Reads all PDF certificates from /certificates folder,
extracts structured data, and outputs certificates.json

Run: python extract_certificates.py
"""

import pdfplumber
import json
import re
from pathlib import Path

# ─── CONFIGURATION ───────────────────────────────────────────────
CERTIFICATES_DIR = "certificates"
OUTPUT_FILE = "certificates.json"

# ─── EXTRACTION FUNCTIONS ────────────────────────────────────────

def extract_text_from_pdf(pdf_path):
    """Extract all text from a PDF file."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            full_text = ""
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    full_text += text + "\n"
            return full_text
    except Exception as e:
        print(f"  Error reading {pdf_path}: {e}")
        return ""

def extract_tables_from_pdf(pdf_path):
    """Extract tables from PDF."""
    tables_data = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    tables_data.append(table)
    except Exception:
        pass
    return tables_data

def normalize_rera_no(rera_no):
    """Normalize RERA number for matching (remove separators)."""
    if not rera_no:
        return ""
    return re.sub(r'[/\-_\.]', '', rera_no).upper()

def parse_certificate(text, tables, filename):
    """Parse certificate text and tables into structured data."""
    data = {
        "filename": filename,
        "rera_no": "",
        "project_name": "",
        "project_address": "",
        "developer_name": "",
        "valid_from": "",
        "valid_until": "",
        "project_type": "",
        "land_area_sqm": "",
        "builtup_area_sqm": "",
        "carpet_area_sqm": "",
        "total_units": "",
        "open_parking": "",
        "covered_parking": "",
        "mechanical_parking": "",
        "basement_parking": "",
        "project_status": "",
        "registration_date": ""
    }
    
    # Normalize special Unicode characters
    text = text.replace('\u2018', "'").replace('\u2019', "'")
    text = text.replace('\u201c', '"').replace('\u201d', '"')
    text = text.replace('\u2013', '-').replace('\u2014', '--')
    text = text.replace('\u00a0', ' ')
    
    # ── Extract RERA Registration Number ──
    # Pattern: WBRERA/P/NOR/2024/002162 (with slashes and hyphens)
    rera_patterns = [
        r'Project Registration No\.:\s*(WBRERA\/[A-Z]+\/\d+\/\d+)',
        r'project registration number\s*:\s*(WBRERA\/[A-Z]+\/\d+\/\d+)',
        r'registration number\s*:\s*(WBRERA\/[A-Z]+\/\d+\/\d+)',
        r'(WBRERA\/[A-Z]+\/\d+\/\d+)',
    ]
    for pattern in rera_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            data["rera_no"] = match.group(1).strip()
            break
    
    # If still empty, try from filename
    if not data["rera_no"]:
        fn = filename.upper().replace('.PDF', '')
        # Try: WBRERAPNOR2024002162 -> WBRERA/P/NOR/2024/002162
        m = re.match(r'(WBRERA)([A-Z])([A-Z]+)(\d{4})(\d+)', fn)
        if m:
            data["rera_no"] = f"{m.group(1)}/{m.group(2)}/{m.group(3)}/{m.group(4)}/{m.group(5)}"
    
    # ── Extract Project Name ──
    match = re.search(r'Project Name\s*:\s*(.+?)(?:\n|\r|$)', text, re.IGNORECASE)
    if match:
        name = match.group(1).strip()
        # Clean up common artifacts
        name = re.sub(r'\s*\*\*\s*$', '', name)
        data["project_name"] = name
    
    # ── Extract Project Address ──
    # Text between "Project Address :" and "Project Details" or conditions
    match = re.search(r'Project Address\s*:\s*(.+?)(?:Project Details|2\.\s*\()', text, re.IGNORECASE | re.DOTALL)
    if match:
        addr = re.sub(r'\s+', ' ', match.group(1).strip())
        data["project_address"] = addr[:300]
    
    # ── Extract Developer Name ──
    # Look for "Company/LLP firm/society..." followed by name before "having its registered office"
    dev_match = re.search(
        r'(?:Company\s*\/\s*LLP\s*firm\s*\/\s*society[^\n]*)\s*\n\s*(.+?)(?:\s+(?:LLP|Limited|Ltd|Private|Pvt)[^\n]*)?\s*\n.*?registered office',
        text, re.IGNORECASE | re.DOTALL
    )
    if dev_match:
        dev_name = re.sub(r'\s+', ' ', dev_match.group(1).strip())
        data["developer_name"] = dev_name[:200]
    
    # ── Extract Dates ──
    date_match = re.search(
        r'commencing from\s*(\d{1,2}/\d{1,2}/\d{4})\s*and ending with\s*(\d{1,2}/\d{1,2}/\d{4})',
        text
    )
    if date_match:
        data["valid_from"] = date_match.group(1)
        data["valid_until"] = date_match.group(2)
    
    reg_date_match = re.search(r'(?:Dated|Date)\s*:\s*(\d{1,2}/\d{1,2}/\d{4})', text)
    if reg_date_match:
        data["registration_date"] = reg_date_match.group(1)
    
    # ── Parse Tables for Structured Data ──
    for table in tables:
        if not table or len(table) < 2:
            continue
        
        # Convert table to a flat text for easier parsing
        table_text = ""
        for row in table:
            if row:
                row_text = " | ".join([str(cell).strip() if cell else "" for cell in row])
                table_text += row_text + "\n"
        
        # Project Type
        type_match = re.search(r'(Residential|Commercial|Mixed\s*Use)', table_text, re.IGNORECASE)
        if type_match and not data["project_type"]:
            data["project_type"] = type_match.group(1).strip()
        
        # Area row: "Area of Land Developed ... Total Builtup Area ... Total Carpet Area ... Flats/Units"
        # Look for numbers in the table
        area_match = re.search(
            r'Area.*?(\d[\d,]*)\s+(\d[\d,]*)\s+(\d[\d,]*)\s+(\d[\d,]*)',
            table_text
        )
        if area_match:
            data["land_area_sqm"] = area_match.group(1).replace(',', '')
            data["builtup_area_sqm"] = area_match.group(2).replace(',', '')
            data["carpet_area_sqm"] = area_match.group(3).replace(',', '')
            data["total_units"] = area_match.group(4).replace(',', '')
        
        # Parking rows
        for row in table:
            if not row:
                continue
            row_str = " ".join([str(c).lower() if c else "" for c in row])
            
            if 'open parking' in row_str:
                nums = re.findall(r'(\d+)', row_str)
                if nums:
                    data["open_parking"] = nums[-1]
            
            if 'covered parking' in row_str:
                nums = re.findall(r'(\d+)', row_str)
                if nums:
                    data["covered_parking"] = nums[-1]
            
            if 'mechanical parking' in row_str:
                nums = re.findall(r'(\d+)', row_str)
                if nums:
                    data["mechanical_parking"] = nums[-1]
            
            if 'basement parking' in row_str:
                nums = re.findall(r'(\d+)', row_str)
                if nums:
                    data["basement_parking"] = nums[-1]
    
    # ── Project Status ──
    status_match = re.search(r'Project Status\s*:\s*(.+)', text, re.IGNORECASE)
    if status_match:
        data["project_status"] = status_match.group(1).strip()
    
    return data


# ─── MAIN EXTRACTION ────────────────────────────────────────────

def main():
    cert_dir = Path(CERTIFICATES_DIR)
    if not cert_dir.exists():
        print(f"\nERROR: Certificates folder not found: {CERTIFICATES_DIR}")
        print(f"Create the folder and add PDF files to it.")
        return
    
    pdf_files = list(cert_dir.glob("*.pdf"))
    
    if not pdf_files:
        print(f"\nERROR: No PDF files found in {CERTIFICATES_DIR}/")
        print(f"Add RERA certificate PDFs to this folder and run again.")
        return
    
    print(f"\nProcessing {len(pdf_files)} certificate(s)...\n")
    
    certificates = []
    success_count = 0
    error_count = 0
    
    for pdf_file in sorted(pdf_files):
        print(f"  {pdf_file.name}")
        
        text = extract_text_from_pdf(pdf_file)
        tables = extract_tables_from_pdf(pdf_file)
        
        if not text.strip():
            print(f"    WARNING: No text extracted - may be scanned image (OCR needed)")
            error_count += 1
            continue
        
        data = parse_certificate(text, tables, pdf_file.name)
        
        if data["rera_no"] or data["project_name"]:
            certificates.append(data)
            success_count += 1
            print(f"    Project: {data['project_name'][:60]}")
            print(f"    RERA:   {data['rera_no']}")
            if data.get("total_units"):
                print(f"    Units:  {data['total_units']}, Type: {data.get('project_type', 'N/A')}")
            if data.get("registration_date"):
                print(f"    Date:   {data['registration_date']}")
            print()
        else:
            print(f"    WARNING: Could not extract key fields\n")
            error_count += 1
    
    # Save to JSON
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(certificates, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*60}")
    print(f"Extraction complete!")
    print(f"   Total PDFs processed: {len(pdf_files)}")
    print(f"   Successful:           {success_count}")
    print(f"   Failed:               {error_count}")
    print(f"   Output file:          {OUTPUT_FILE}")
    print(f"   Certificates saved:   {len(certificates)}")
    
    if success_count > 0:
        print(f"\nNext step: Run 'python rebuild.py' to update the app with certificate data.")
    
    if error_count > 0:
        print(f"\nNOTE: {error_count} file(s) had issues. Scanned PDFs need OCR software.")


if __name__ == "__main__":
    main()