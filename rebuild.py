#!/usr/bin/env python3
"""
Kevala Home - Rebuild Script
Reads Approved.csv and Rejected.csv, converts to JavaScript arrays,
and replaces the embedded data blocks in index.html.
"""

import csv
import json
import re
from datetime import datetime, timezone

def parse_approved(filepath):
    """Parse Approved.csv and return list of dicts."""
    projects = []
    # Try multiple encodings
    for encoding in ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252', 'iso-8859-1']:
        try:
            with open(filepath, 'r', encoding=encoding) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    project = {
                        "id": row.get("Project ID", "").strip(),
                        "name": row.get("Project Name", "").strip(),
                        "rera": row.get("Registration No", "").strip(),
                        "comp": row.get("Completion Date", "").strip(),
                        "reg": row.get("Registration Date", "").strip(),
                        "s": "A"
                    }
                    if project["id"] and project["name"]:
                        projects.append(project)
                break
        except (UnicodeDecodeError, Exception):
            continue
    return projects

def parse_rejected(filepath):
    """Parse Rejected.csv and return list of dicts."""
    projects = []
    for encoding in ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252', 'iso-8859-1']:
        try:
            with open(filepath, 'r', encoding=encoding) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("Sl No.", "").strip() == "Project List":
                        continue
                    project = {
                        "id": row.get("Project ID", "").strip(),
                        "name": row.get("Project Name", "").strip(),
                        "rera": row.get("Project ID", "").strip(),
                        "comp": row.get("Completion Date", "").strip(),
                        "rev": row.get("Reject/Revoke Date", "").strip(),
                        "s": "R"
                    }
                    if project["id"] and project["name"]:
                        projects.append(project)
                break
        except (UnicodeDecodeError, Exception):
            continue
    return projects

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

def update_index_html(index_path, approved_js, rejected_js, combined_js, approved_count, rejected_count):
    """Replace embedded data blocks in index.html."""
    with open(index_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Replace data blocks
    content = re.sub(r'const EMBEDDED_APPROVED\s*=\s*\[.*?\];', approved_js, content, flags=re.DOTALL)
    content = re.sub(r'const EMBEDDED_REJECTED\s*=\s*\[.*?\];', rejected_js, content, flags=re.DOTALL)
    content = re.sub(r'const FALLBACK_DATA\s*=\s*\[.*?\];', combined_js, content, flags=re.DOTALL)
    
    # Update timestamp
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ts_comment = f"/* Last data update: {now} | Approved: {approved_count:,} | Rejected: {rejected_count:,} | Total: {approved_count + rejected_count:,} */"
    
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
    print(f"   Total projects:    {approved_count + rejected_count:,}")
    print(f"   Timestamp:         {now}")
    print(f"   Output:            {index_path}")

if __name__ == "__main__":
    try:
        approved = parse_approved("Approved.csv")
        rejected = parse_rejected("Rejected.csv")
        
        print(f"Parsing CSV files...")
        print(f"   Approved rows: {len(approved):,}")
        print(f"   Rejected rows: {len(rejected):,}")
        
        if len(approved) == 0:
            print("WARNING: No approved projects parsed. Check Approved.csv encoding.")
        if len(rejected) == 0:
            print("WARNING: No rejected projects parsed. Check Rejected.csv encoding.")
        
        approved_js = generate_js_array(approved, "EMBEDDED_APPROVED")
        rejected_js = generate_js_array(rejected, "EMBEDDED_REJECTED")
        combined_js = generate_js_array(approved + rejected, "FALLBACK_DATA")
        
        update_index_html("index.html", approved_js, rejected_js, combined_js, len(approved), len(rejected))
        
    except FileNotFoundError as e:
        print(f"Error: CSV file not found - {e}")
        exit(1)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)