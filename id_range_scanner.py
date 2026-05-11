#!/usr/bin/env python3
"""
ID Range Scanner - проверяет ВСЕ ID подряд от 0 до N
Для каждого ID: если страница существует - парсим, нет - прочерк
"""

import asyncio
import aiohttp
import json
import time
import re
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup


def extract_contacts_from_text(text: str) -> dict:
    contacts = {}
    
    # Email
    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w{2,}', text)
    if email_match:
        contacts['email'] = email_match.group(0)
    
    # Phone - various formats
    phone_patterns = [
        r'\+?[\d\s\-\(\)]{10,20}',
        r'\(?:\+?\d{1,3})?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',
    ]
    for pattern in phone_patterns:
        phone_match = re.search(pattern, text)
        if phone_match:
            cleaned = re.sub(r'[^\d\+]', '', phone_match.group(0))
            if len(cleaned) >= 10:
                contacts['phone'] = phone_match.group(0)
                break
    
    # Telegram
    tg_match = re.search(r'telegram[:\s]*@?(\w+)', text, re.IGNORECASE)
    if tg_match:
        contacts['telegram'] = tg_match.group(1)
    
    # WhatsApp
    wa_match = re.search(r'whatsapp[:\s]*[\+\d\s\-]{10,}', text, re.IGNORECASE)
    if wa_match:
        contacts['whatsapp'] = wa_match.group(0).replace('whatsapp', '').strip()
    
    # Facebook
    fb_match = re.search(r'facebook\.com/[\w\.]+|fb\.com/[\w\.]+', text, re.IGNORECASE)
    if fb_match:
        contacts['facebook'] = fb_match.group(0)
    
    # LinkedIn
    li_match = re.search(r'linkedin\.com/in/[\w\-]+', text, re.IGNORECASE)
    if li_match:
        contacts['linkedin'] = li_match.group(0)
    
    # Skype
    skype_match = re.search(r'skype[:\s]*(\w+)', text, re.IGNORECASE)
    if skype_match:
        contacts['skype'] = skype_match.group(1)
    
    # Discord
    discord_match = re.search(r'discord[:\s]*(\w+\.?\w*)', text, re.IGNORECASE)
    if discord_match:
        contacts['discord'] = discord_match.group(1)
    
    return contacts


BASE_URL = "https://www.onlinejobs.ph/jobseekers/info"
OUTPUT_DIR = Path("/Users/aiserver/OPENCLAW BOT/ojp_progress")
OUTPUT_DIR.mkdir(exist_ok=True)

MAX_ID = 1000000  # Тестовый запуск
CONCURRENCY = 20  # Параллельных запросов
BATCH_SAVE = 1000  # Сохранять каждые 1000

headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
}

def parse_profile(html: str, profile_id: str) -> dict:
    result = {
        'profile_id': profile_id,
        'status': 'unknown',
        'profile_url': f'https://www.onlinejobs.ph/jobseekers/info/{profile_id}',
        'name': '',
        'title': '',
        'hourly_rate': '',
        'id_proof_score': '',
        'education': '',
        'last_active': '',
        'description': '',
        'skills_top': '',
        'email': '',
        'website': '',
        'phone': '',
        'telegram': '',
        'whatsapp': '',
        'facebook': '',
        'linkedin': '',
        'skype': '',
        'discord': '',
        'is_active': False,
    }
    
    if not html or len(html) < 100:
        result['status'] = 'not_found'
        result['profile_url'] = f'https://www.onlinejobs.ph/jobseekers/info/{profile_id}'
        return result
    
    # Check for Pro-required content
    if 'Sign Up with Pro Account' in html or 'PIN to View' in html:
        result['status'] = 'locked'
        result['profile_url'] = f'https://www.onlinejobs.ph/jobseekers/info/{profile_id}'
    
    # Check if profile is accessible (has name)
    name_match = re.search(r'jobseeker-name[^>]*>([^<]+)', html)
    if not name_match:
        if result['status'] != 'locked':
            result['status'] = 'empty'
            result['profile_url'] = f'https://www.onlinejobs.ph/jobseekers/info/{profile_id}'
        return result
    
    result['status'] = 'active'
    result['name'] = name_match.group(1).strip()
    result['is_active'] = True
    
    # Title
    title_match = re.search(r'<h1[^>]*>([^<]+)<', html)
    if title_match:
        result['title'] = title_match.group(1).strip()
    
    # Hourly rate
    rate_match = re.search(r'>\s*at\s*<strong>\$([\d,.]+)/hour', html)
    if rate_match:
        result['hourly_rate'] = '$' + rate_match.group(1) + '/hour'
    
    # ID Proof
    id_match = re.search(r'class="badge">(\d+)</span>\s*ID PROOF', html)
    if id_match:
        result['id_proof_score'] = id_match.group(1)
    
    # Education
    for edu in ['Bachelors degree', 'Associates degree', 'High School', 'College Undergraduate', 'Master']:
        if edu in html:
            result['education'] = edu
            break
    
    # Last Active
    active_match = re.search(r'Last Active</strong></p>\s*<p[^>]*>([^<]+)<', html)
    if active_match:
        result['last_active'] = active_match.group(1).strip()
    
    # Description - FULL TEXT (no limit)
    desc_match = re.search(r'>Profile Description</h3>\s*(.*?)(?:<h3|</div>)', html, re.DOTALL)
    if desc_match:
        text = re.sub(r'<[^>]+>', ' ', desc_match.group(1))
        text = re.sub(r'\s+', ' ', text).strip()
        result['description'] = text
        
        # Extract contacts from description
        contacts = extract_contacts_from_text(text)
        if not result['email'] and contacts.get('email'):
            result['email'] = contacts['email']
        if not result['phone'] and contacts.get('phone'):
            result['phone'] = contacts['phone']
        if not result['telegram'] and contacts.get('telegram'):
            result['telegram'] = contacts['telegram']
        if not result['whatsapp'] and contacts.get('whatsapp'):
            result['whatsapp'] = contacts['whatsapp']
        if not result['facebook'] and contacts.get('facebook'):
            result['facebook'] = contacts['facebook']
        if not result['linkedin'] and contacts.get('linkedin'):
            result['linkedin'] = contacts['linkedin']
        if not result['skype'] and contacts.get('skype'):
            result['skype'] = contacts['skype']
        if not result['discord'] and contacts.get('discord'):
            result['discord'] = contacts['discord']
    
    # Skills
    skills_match = re.search(r'>Top Skills</h3>(.*?)(?:<h3|</div>)', html, re.DOTALL)
    if skills_match:
        skills = re.findall(r'>([^<]{2,50})</a>', skills_match.group(1))
        result['skills_top'] = ', '.join(skills[:5])
    
    # Contact fields - usually behind Pro, but check anyway
    # Email (usually masked)
    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', html)
    if email_match:
        result['email'] = email_match.group(1)
    
    # Website/Portfolio
    if 'Website' in html:
        site_match = re.search(r'Website[^<]*href=["\']([^"\']+)["\']', html)
        if site_match:
            result['website'] = site_match.group(1)
    
    return result


async def fetch_profile(session, pid):
    url = f"{BASE_URL}/{pid}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 200:
                html = await resp.text()
                return parse_profile(html, pid)
            else:
                return {'profile_id': pid, 'status': 'not_found'}
    except Exception as e:
        return {'profile_id': pid, 'status': 'error', 'error': str(e)[:50]}


async def scan_range(start_id, end_id, batch_num):
    results = []
    
    connector = aiohttp.TCPConnector(limit=CONCURRENCY)
    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        semaphore = asyncio.Semaphore(CONCURRENCY)
        
        async def fetch_with_sem(pid):
            async with semaphore:
                return await fetch_profile(session, pid)
        
        tasks = [fetch_with_sem(pid) for pid in range(start_id, end_id)]
        
        for coro in asyncio.as_completed(tasks):
            result = await coro
            results.append(result)
    
    return results


async def main():
    print(f"=== ID Range Scanner ===")
    print(f"Range: 0 - {MAX_ID:,}")
    print(f"Concurrency: {CONCURRENCY}")
    print(f"Saving every: {BATCH_SAVE}")
    print()
    
    # Load existing progress
    results_file = OUTPUT_DIR / "id_scan_results.json"
    if results_file.exists():
        all_results = json.loads(results_file.read_text())
    else:
        all_results = {}
    
    processed = len(all_results)
    print(f"Already processed: {processed:,}")
    
    start_time = time.time()
    batch_count = 0
    
    # Process in batches
    for batch_start in range(processed, MAX_ID, BATCH_SAVE):
        batch_end = min(batch_start + BATCH_SAVE, MAX_ID)
        
        print(f"Processing {batch_start:,} - {batch_end:,}...", end=" ", flush=True)
        
        batch_results = await scan_range(batch_start, batch_end, batch_count)
        
        for r in batch_results:
            all_results[r['profile_id']] = r
        
        # Save after each batch
        results_file.write_text(json.dumps(all_results, ensure_ascii=False))
        
        elapsed = time.time() - start_time
        total = len(all_results)
        rate = total / elapsed if elapsed > 0 else 0
        eta = (MAX_ID - total) / rate / 60 if rate > 0 else 0
        
        # Stats
        active = sum(1 for r in all_results.values() if r.get('status') == 'active')
        locked = sum(1 for r in all_results.values() if r.get('status') == 'locked')
        not_found = sum(1 for r in all_results.values() if r.get('status') == 'not_found')
        
        print(f"Done! Active: {active:,}, Locked: {locked:,}, Not found: {not_found:,}, Rate: {rate:.0f}/s, ETA: {eta:.0f}min")
        
        batch_count += 1
    
    print(f"\n=== COMPLETE ===")
    print(f"Total: {len(all_results):,}")
    
    # Summary
    active = sum(1 for r in all_results.values() if r.get('status') == 'active')
    locked = sum(1 for r in all_results.values() if r.get('status') == 'locked')
    not_found = sum(1 for r in all_results.values() if r.get('status') == 'not_found')
    empty = sum(1 for r in all_results.values() if r.get('status') == 'empty')
    
    print(f"Active (green): {active:,} ({active/len(all_results)*100:.1f}%)")
    print(f"Locked (Pro): {locked:,} ({locked/len(all_results)*100:.1f}%)")
    print(f"Not found: {not_found:,}")
    print(f"Empty: {empty:,}")


if __name__ == "__main__":
    asyncio.run(main())