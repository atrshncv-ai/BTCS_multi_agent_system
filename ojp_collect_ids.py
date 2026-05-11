#!/usr/bin/env python3
"""
Incremental ID collector - restartable
"""
import asyncio, re, json
from pathlib import Path
from playwright.async_api import async_playwright
import sys

BASE = 'https://www.onlinejobs.ph/employers/skillsearch/all/a181a603769c1f98ad927e7367c7aa5112147425'
OUTPUT = Path('/Users/aiserver/OPENCLAW BOT/ojp_progress/all_ids.json')
START_PAGE = int(sys.argv[1]) if len(sys.argv) > 1 else 0
PAGES = int(sys.argv[2]) if len(sys.argv) > 2 else 50

async def collect():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        page = await b.new_page()
        
        all_ids = set()
        
        for i in range(PAGES):
            offset = (START_PAGE + i) * 30
            try:
                await page.goto(f'{BASE}/{offset}', timeout=45000)
                await asyncio.sleep(0.4)
                
                html = await page.content()
                ids = re.findall(r'/jobseekers/info/(\d+)', html)
                if not ids:
                    print(f'End at page {START_PAGE + i}')
                    break
                    
                all_ids.update(ids)
                print(f'Page {START_PAGE + i + 1}: +{len(ids)}, total {len(all_ids)}')
                
            except Exception as e:
                print(f'Error at page {i}: {e}')
                break
        
        await b.close()
        
        if all_ids:
            # Load existing and merge
            existing = []
            if OUTPUT.exists():
                existing = json.loads(OUTPUT.read_text())
            
            existing = list(set(existing) | all_ids)
            OUTPUT.write_text(json.dumps(existing))
            print(f'Saved: total {len(existing)} IDs')

asyncio.run(collect())