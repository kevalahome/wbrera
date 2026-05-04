#!/usr/bin/env python3
"""
Kevala Home - Rebuild Script
Reads Approved.csv, Rejected.csv, and certificates.json,
converts to JavaScript arrays, and replaces embedded data blocks in index.html.
"""

import csv
import json
import re
from datetime import datetime, timezone

def parse_approved(filepath):
    """Parse Approved.csv and return list of dicts. Tries multiple encodings."""
    projects = []
    for encoding in ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']:
        try:
            with open(filepath, 'r', encoding=encoding) as f:
                reader = csv.reader(f)
                rows = list(reader)
                
                start = 0
                for i, row in enumerate(rows):
                    if row and row[0].strip() == 'Sl No.':
                        start = i
                        break
                
                for row in rows[start+1:]:
                    if len(row) < 3:
                        continue
                    project = {
                        "id": row[1].strip() if len(row) > 1 else "",
                        "name": row[2].strip() if len(row) > 2 else "",
                        "rera": row[4].strip() if len(row) > 4 else "",
                        "comp": row[3].strip() if len(row) > 3 else "",
                        "reg": row[5].strip() if len(row) > 5 else "",
                        "s": "A"
                    }
                    if project["id"] and project["name"]:
                        projects.append(project)
                break
        except (UnicodeDecodeError, Exception):
            continue
    return projects

def parse_rejected(filepath):
    """Parse Rejected.csv and return list of dicts. Tries multiple encodings."""
    projects = []
    for encoding in ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']:
        try:
            with open(filepath, 'r', encoding=encoding) as f:
                reader = csv.reader(f)
                rows = list(reader)
                
                start = 0
                for i, row in enumerate(rows):
                    if row and row[0].strip() == 'Sl No.':
                        start = i
                        break
                
                for row in rows[start+1:]:
                    if len(row) < 3:
                        continue
                    project = {
                        "id": row[1].strip() if len(row) > 1 else "",
                        "name": row[2].strip() if len(row) > 2 else "",
                        "rera": row[1].strip() if len(row) > 1 else "",
                        "comp": row[3].strip() if len(row) > 3 else "",
                        "rev": row[4].strip() if len(row) > 4 else "",
                        "s": "R"
                    }
                    if project["id"] and project["name"]:
                        projects.append(project)
                break
        except (UnicodeDecodeError, Exception):
            continue
    return projects

def load_certificates(filepath="certificates.json"):
    """Load extracted certificate data."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            certs = json.load(f)
            if isinstance(certs, list):
                return certs
            return []
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def generate_js_array(projects, variable_name):
    """Generate JavaScript array declaration with proper formatting."""
    lines = []
    lines.append(f"const {variable_name} = [")
    
    for i, proj in enumerate(projects):
        js_obj = json.dumps(proj, ensure_ascii=False)
        comma = "," if i < len(projects) - 1 else ""
        lines.append(f"  {js_obj}{comma}")
    
    lines.append("];")
    return "\n".join(lines)

def update_index_html(index_path, approved_js, rejected_js, combined_js, certs_js, approved_count, rejected_count, cert_count):
    """Replace embedded data blocks in index.html."""
    with open(index_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Replace data blocks
    content = re.sub(r'const EMBEDDED_APPROVED\s*=\s*\[.*?\];', approved_js, content, flags=re.DOTALL)
    content = re.sub(r'const EMBEDDED_REJECTED\s*=\s*\[.*?\];', rejected_js, content, flags=re.DOTALL)
    content = re.sub(r'const FALLBACK_DATA\s*=\s*\[.*?\];', combined_js, content, flags=re.DOTALL)
    content = re.sub(r'const EMBEDDED_CERTIFICATES\s*=\s*\[.*?\];', certs_js, content, flags=re.DOTALL)
    
    # Update timestamp
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ts_comment = f"/* Last data update: {now} | Approved: {approved_count:,} | Rejected: {rejected_count:,} | Certs: {cert_count:,} | Total: {approved_count + rejected_count:,} */"
    
    content = re.sub(r'/\* Last data update:.*?\*/', ts_comment, content, flags=re.DOTALL)
    
    # Update stats
    content = re.sub(
        r'<div class="stat-num" id="statTotal">.*?</div>',
        f'<div class="stat-num" id="statTotal">{approved_count + rejected_count:,}</div>',
        content
    )
    content = re.sub(
        r'<div class="stat-num" id="statActive">.*?</div>',
        f'<div class="stat-num" id="statActive">{approved_count:,}</div>',
        content
    )
    content = re.sub(
        r'<div class="stat-num" id="statRevoked">.*?</div>',
        f'<div class="stat-num" id="statRevoked">{rejected_count:,}</div>',
        content
    )
    
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"\n✅ Rebuild complete!")
    print(f"   Approved projects: {approved_count:,}")
    print(f"   Rejected projects: {rejected_count:,}")
    print(f"   Certificates:      {cert_count:,}")
    print(f"   Total projects:    {approved_count + rejected_count:,}")
    print(f"   Timestamp:         {now}")
    print(f"   Output:            {index_path}")

if __name__ == "__main__":
    try:
        approved = parse_approved("Approved.csv")
        rejected = parse_rejected("Rejected.csv")
        certs = load_certificates()
        
        print(f"📊 Parsing CSV files...")
        print(f"   Approved rows: {len(approved):,}")
        print(f"   Rejected rows: {len(rejected):,}")
        print(f"   Certificates:  {len(certs):,}")
        
        if len(approved) == 0:
            print("⚠️  WARNING: No approved projects parsed. Check Approved.csv encoding.")
        if len(rejected) == 0:
            print("⚠️  WARNING: No rejected projects parsed. Check Rejected.csv encoding.")
        
        approved_js = generate_js_array(approved, "EMBEDDED_APPROVED")
        rejected_js = generate_js_array(rejected, "EMBEDDED_REJECTED")
        combined_js = generate_js_array(approved + rejected, "FALLBACK_DATA")
        certs_js = generate_js_array(certs, "EMBEDDED_CERTIFICATES") if certs else "const EMBEDDED_CERTIFICATES = [];"
        
        update_index_html("index.html", approved_js, rejected_js, combined_js, certs_js, len(approved), len(rejected), len(certs))
        
    except FileNotFoundError as e:
        print(f"❌ Error: File not found - {e}")
        exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)