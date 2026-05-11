#!/usr/bin/env python3
"""
OnlineJobs.ph - Collect ALL IDs using Playwright
Step 1: Get all 601K profile IDs
"""

import asyncio
import json
import re
from pathlib import Path
from playwright.async_api import async_playwright

OUTPUT = Path("/Users/aiserver/OPENCLAW BOT/ojp_progress/all_ids.json")
BASE = "https://www.onlinejobs.ph/employers/skillsearch/all/a181a603769c1f98ad927e7367c7aa5112147425"


async def get_page_ids(page, offset):
    """Get IDs from a single page"""
    await page.goto(f"{BASE}/{offset}", timeout=15000)
    await asyncio.sleep(0.5)  # Let JS load
    
    html = await page.content()
    ids = re.findall(r'/jobseekers/info/(\d+)', html)
    return ids


async def main():
    print("=== Collecting ALL profile IDs ===")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        all_ids = set()
        
        # Get 50 pages first to test
        for page_num in range(50):
            offset = page_num * 30
            
            try:
                page = await browser.new_page()
                ids = await get_page_ids(page, offset)
                await page.close()
                
                all_ids.update(ids)
                
                if (page_num + 1) % 10 == 0:
                    print(f"Page {page_num+1}: {len(all_ids)} unique IDs")
                    
            except Exception as e:
                print(f"Error at {offset}: {e}")
        
        await browser.close()
    
    # Save
    ids_list = list(all_ids)
    OUTPUT.write_text(json.dumps(ids_list))
    print(f"\n✓ Saved {len(ids_list)} IDs to {OUTPUT}")
    
    return ids_list


if __name__ == "__main__":
    asyncio.run(main())