#!/usr/bin/env python3
"""
Kevala Home - Rebuild Script (API-less Dynamic Loading)
Reads Approved.csv, Rejected.csv, and certificates.json,
outputs JSON data files to /data/ folder and updates stats in index.html.
"""

import csv
import json
import re
import os
from datetime import datetime, timezone

def parse_approved(filepath):
    """Parse Approved.csv and return list of dicts."""
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
    """Parse Rejected.csv and return list of dicts."""
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

def save_json(data, filepath):
    """Save data as JSON file."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)

def update_index_html(index_path, approved_count, rejected_count, cert_count):
    """Update stats in index.html."""
    with open(index_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ts_comment = f"/* Last data update: {now} | Approved: {approved_count:,} | Rejected: {rejected_count:,} | Certs: {cert_count:,} */"
    
    content = re.sub(r'/\* Last data update:.*?\*/', ts_comment, content, flags=re.DOTALL)
    
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

if __name__ == "__main__":
    try:
        approved = parse_approved("Approved.csv")
        rejected = parse_rejected("Rejected.csv")
        certs = load_certificates()
        
        print(f"Parsing CSV files...")
        print(f"   Approved rows: {len(approved):,}")
        print(f"   Rejected rows: {len(rejected):,}")
        print(f"   Certificates:  {len(certs):,}")
        
        if len(approved) == 0:
            print("WARNING: No approved projects parsed.")
        if len(rejected) == 0:
            print("WARNING: No rejected projects parsed.")
        
        # Save data files to /data/ folder
        save_json(approved, "data/approved.json")
        save_json(rejected, "data/rejected.json")
        save_json(certs, "data/certificates.json")
        
        # Update stats in index.html
        update_index_html("index.html", len(approved), len(rejected), len(certs))
        
        print(f"\nRebuild complete!")
        print(f"   Approved projects: {len(approved):,}")
        print(f"   Rejected projects: {len(rejected):,}")
        print(f"   Certificates:      {len(certs):,}")
        print(f"   Total projects:    {len(approved) + len(rejected):,}")
        print(f"   Timestamp:         {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        print(f"   Output:            data/approved.json")
        print(f"   Output:            data/rejected.json")
        print(f"   Output:            data/certificates.json")
        
    except FileNotFoundError as e:
        print(f"Error: File not found - {e}")
        exit(1)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)