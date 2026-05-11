#!/usr/bin/env python3
"""
OnlineJobs.ph Parser - полный парсинг всех карточек соискателей
"""

import asyncio
import aiohttp
import re
import json
import csv
import time
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
from dataclasses import dataclass, asdict
from typing import List, Optional

BASE_URL = "https://www.onlinejobs.ph"
SEARCH_URL = f"{BASE_URL}/employers/skillsearch/all/a181a603769c1f98ad927e7367c7aa5112147425"
OUTPUT_DIR = Path("/Users/aiserver/OPENCLAW BOT/onlinejobs_parser")
OUTPUT_DIR.mkdir(exist_ok=True)


@dataclass
class JobSeeker:
    profile_id: str
    name: str
    title: str
    id_proof_score: str
    employment_type: str
    hours_per_day: str
    hourly_rate: str
    monthly_rate: str
    education: str
    last_active: str
    profile_description: str
    top_skills: str
    profile_url: str


def parse_jobseeker_card(card_html: str, profile_id: str) -> Optional[JobSeeker]:
    soup = BeautifulSoup(card_html, 'html.parser')
    
    try:
        name_elem = soup.find('h3', {'class': lambda x: x and 'Job' in x})
        if not name_elem:
            name_elem = soup.find('h4')
        name = name_elem.get_text(strip=True) if name_elem else ""
        
        title_match = re.search(r'####\s*([^\n]+)', card_html)
        title = title_match.group(1).strip() if title_match else ""
        
        id_proof_match = re.search(r'(\d+)\s+ID PROOF', card_html)
        id_proof_score = id_proof_match.group(1) if id_proof_match else ""
        
        emp_type_match = re.search(r'LOOKING FOR\s*\n\s*([^\n]+)', card_html)
        employment_type = emp_type_match.group(1).strip() if emp_type_match else ""
        
        hours_match = re.search(r'\((\d+)\s+hours?/day\)', card_html)
        hours_per_day = hours_match.group(1) if hours_match else ""
        
        rate_match = re.search(r'at\s+\$?([\d.]+)/hour\s+\(\$?([\d,]+)', card_html)
        hourly_rate = rate_match.group(1) if rate_match else ""
        monthly_rate = rate_match.group(2) if rate_match else ""
        
        edu_match = re.search(r'EDUCATION\s*\n\s*([^\n]+)', card_html)
        education = edu_match.group(1).strip() if edu_match else ""
        
        active_match = re.search(r'LAST ACTIVE\s*\n\s*([^\n]+)', card_html)
        last_active = active_match.group(1).strip() if active_match else ""
        
        desc_match = re.search(r'PROFILE DESCRIPTION\s*\n\s*(.+?)(?=TOP SKILLS|$)', card_html, re.DOTALL)
        profile_description = desc_match.group(1).strip()[:500] if desc_match else ""
        
        skills_match = re.search(r'TOP SKILLS\s*\n\s*(.+?)(?=LOOKING FOR|$)', card_html, re.DOTALL)
        top_skills = skills_match.group(1).strip()[:300] if skills_match else ""
        
        profile_url = f"{BASE_URL}/jobseekers/info/{profile_id}"
        
        if name:
            return JobSeeker(
                profile_id=profile_id,
                name=name,
                title=title,
                id_proof_score=id_proof_score,
                employment_type=employment_type,
                hours_per_day=hours_per_day,
                hourly_rate=hourly_rate,
                monthly_rate=monthly_rate,
                education=education,
                last_active=last_active,
                profile_description=profile_description,
                top_skills=top_skills,
                profile_url=profile_url
            )
    except Exception as e:
        print(f"Error parsing card {profile_id}: {e}")
    
    return None


async def fetch_page(session: aiohttp.ClientSession, offset: int, total: int) -> tuple[List[JobSeeker], int]:
    url = f"{SEARCH_URL}/{offset}/{total}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }
    
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            html = await resp.text()
            
            jobseekers = []
            
            profile_ids = re.findall(r'/jobseekers/info/(\d+)', html)
            profile_ids = list(dict.fromkeys(profile_ids))
            
            for i, profile_id in enumerate(profile_ids):
                pattern = rf'/jobseekers/info/{profile_id}</a>(.*?)(?:</div>|</a>)'
                match = re.search(pattern, html, re.DOTALL)
                if match:
                    card_html = match.group(1)
                    jobseeker = parse_jobseeker_card(card_html, profile_id)
                    if jobseeker:
                        jobseekers.append(jobseeker)
            
            return jobseekers, len(jobseekers)
            
    except Exception as e:
        print(f"Error fetching page {offset}: {e}")
        return [], 0


async def get_total_count(session: aiohttp.ClientSession) -> int:
    url = f"{SEARCH_URL}/0"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    
    async with session.get(url, headers=headers) as resp:
        html = await resp.text()
        match = re.search(r'Found\s+(\d+)\s+jobseekers', html)
        if match:
            return int(match.group(1))
    return 0


def save_to_csv(jobseekers: List[JobSeeker], filename: str):
    filepath = OUTPUT_DIR / filename
    
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'profile_id', 'name', 'title', 'id_proof_score', 'employment_type',
            'hours_per_day', 'hourly_rate', 'monthly_rate', 'education',
            'last_active', 'profile_description', 'top_skills', 'profile_url'
        ])
        writer.writeheader()
        for js in jobseekers:
            writer.writerow(asdict(js))
    
    print(f"💾 Saved {len(jobseekers)} records to {filepath}")
    return filepath


async def main():
    print("📊 OnlineJobs.ph Parser")
    print("=" * 50)
    
    async with aiohttp.ClientSession() as session:
        print("🔍 Getting total count...")
        total = await get_total_count(session)
        print(f"Found {total:,} jobseekers")
        
        if total == 0:
            print("❌ Could not determine total count")
            return
        
        per_page = 30
        total_pages = (total + per_page - 1) // per_page
        print(f"Pages to parse: {total_pages:,}")
        
        all_jobseekers = []
        errors = 0
        start_time = time.time()
        
        for page in range(total_pages):
            offset = page * per_page
            
            if page > 0 and page % 100 == 0:
                elapsed = time.time() - start_time
                rate = page / elapsed if elapsed > 0 else 0
                remaining = (total_pages - page) / rate if rate > 0 else 0
                print(f"[{page:,}/{total_pages:,}] Progress: {page*100/total_pages:.1f}% | Rate: {rate:.1f}p/s | ETA: {remaining/60:.1f}min")
            
            jobseekers, count = await fetch_page(session, offset, total)
            all_jobseekers.extend(jobseekers)
            
            if count == 0:
                errors += 1
                if errors > 10:
                    print(f"❌ Too many errors, stopping at page {page}")
                    break
            else:
                errors = 0
            
            await asyncio.sleep(0.3)
        
        elapsed = time.time() - start_time
        print(f"\n✅ Parsed {len(all_jobseekers):,} jobseekers in {elapsed/60:.1f}min")
        
        if all_jobseekers:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"jobseekers_{len(all_jobseekers)}_{timestamp}.csv"
            save_to_csv(all_jobseekers, filename)


if __name__ == "__main__":
    asyncio.run(main())