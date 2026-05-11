#!/usr/bin/env python3
"""
OnlineJobs.ph Full Parser using Playwright
Scrapes ALL 601K+ profiles using browser automation
"""

import asyncio
import json
import re
import csv
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright

BASE_URL = "https://www.onlinejobs.ph/employers/skillsearch/all/a181a603769c1f98ad927e7367c7aa5112147425"
OUTPUT_DIR = Path("/Users/aiserver/OPENCLAW BOT/ojp_progress")
OUTPUT_DIR.mkdir(exist_ok=True)

CONCURRENCY = 5
BATCH_SIZE = 100


async def collect_all_profile_ids():
    """Use Playwright to scroll through all pages and collect profile IDs"""
    all_ids = set()
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Go to first page
        await page.goto(f"{BASE_URL}/0")
        await page.wait_for_load_state("load")
        
        # Get total count
        total_el = await page.locator("#total_result").text_content()
        total = int(re.sub(r"[^\d]", "", total_el))
        print(f"Total jobseekers: {total:,}")
        
        # Test with limited pages first (full would be ~20K pages)
        max_pages_to_test = 100
        # Test with limited pages first (full would be ~20K pages)
        max_pages_to_test = 100  # Test 100 pages first
        
        # Scroll and collect IDs from each page
        for page_num in range(max_pages_to_test):
            offset = page_num * 30
            
            try:
                await page.goto(f"{BASE_URL}/{offset}", timeout=20000)
                # Wait for page to load
                await asyncio.sleep(1)
                
                # Get all profile IDs from current page
                content = await page.content()
                ids = re.findall(r'/jobseekers/info/(\d+)', content)
                all_ids.update(ids)
                
                if (page_num + 1) % 20 == 0:
                    print(f"Page {page_num+1}: {len(all_ids):,} unique IDs")
                    
            except Exception as e:
                print(f"Error at page {page_num}: {e}")
                continue
        
        await browser.close()
    
    return list(all_ids), total


async def fetch_profile_details(profile_ids: list):
    """Fetch details for each profile"""
    results = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        
        for i, pid in enumerate(profile_ids):
            try:
                page = await context.new_page()
                await page.goto(f"https://www.onlinejobs.ph/jobseekers/info/{pid}", timeout=15000)
                await page.wait_load_state("networkidle", timeout=10000)
                
                html = await page.content()
                
                result = parse_profile(html, pid)
                results.append(result)
                
                await page.close()
                
                if (i + 1) % 50 == 0:
                    print(f"Fetched {i+1}/{len(profile_ids)}")
                    
            except Exception as e:
                print(f"Error fetching {pid}: {e}")
                results.append({"profile_id": pid, "error": str(e)})
            
            await asyncio.sleep(0.2)
        
        await browser.close()
    
    return results


def parse_profile(html: str, profile_id: str) -> dict:
    import html as html_module
    
    result = {
        "profile_id": profile_id,
        "name": "",
        "title": "",
        "url": f"https://www.onlinejobs.ph/jobseekers/info/{profile_id}",
        "id_proof_score": "",
        "education": "",
        "last_active": "",
        "description": "",
        "skills_top": "",
        "hourly_rate": "",
    }
    
    name_m = re.search(r'jobseeker-name[^>]*>([^<]+)<', html)
    if name_m:
        result["name"] = name_m.group(1).strip()
    
    title_m = re.search(r'<h1[^>]*>([^<]+)<', html)
    if title_m:
        result["title"] = title_m.group(1).strip()
    
    idproof = re.search(r'class="badge">(\d+)</span>\s*ID PROOF', html)
    if idproof:
        result["id_proof_score"] = idproof.group(1)
    
    for edu in ['Bachelors degree', 'Associates degree', 'High School', 'College Undergraduate', 'Master']:
        if edu in html:
            result["education"] = edu
            break
    
    active_m = re.search(r'Last Active</strong></p>\s*<p[^>]*>([^<]+)<', html)
    if active_m:
        result["last_active"] = active_m.group(1).strip()
    
    rate_m = re.search(r'>\s*at\s*<strong>\$([\d,.]+)/hour', html)
    if rate_m:
        result["hourly_rate"] = "$" + rate_m.group(1) + "/hour"
    
    return result


async def main():
    print("=== Playwright Full Parser ===")
    
    # Step 1: Collect all profile IDs
    print("\n[1/2] Collecting profile IDs...")
    profile_ids, total = await collect_all_profile_ids()
    print(f"Collected {len(profile_ids):,} unique profile IDs")
    
    # Save IDs
    ids_file = OUTPUT_DIR / "all_profile_ids.json"
    ids_file.write_text(json.dumps(profile_ids))
    print(f"IDs saved to {ids_file}")
    
    # Step 2: Fetch details (this would take too long for 600K)
    # For now, just show how many we found
    print(f"\n[2/2] Would fetch details for {len(profile_ids):,} profiles...")
    print(f"This would take ~{len(profile_ids) * 0.5 / 60:.0f} hours")
    
    return profile_ids


if __name__ == "__main__":
    asyncio.run(main())