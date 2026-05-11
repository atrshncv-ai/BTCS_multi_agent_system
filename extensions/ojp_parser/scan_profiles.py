"""
OnlineJobs.ph Bulk Profile Scanner v4 - Multi-threaded

Strategy:
1. Download sitemaps → ~100K profile IDs
2. Fetch profile details in PARALLEL with thread pool
3. Save progress after each batch
4. Generate CSV/XLSX output

Optimizations:
- ThreadPoolExecutor for parallel HTTP requests
- Batch processing with configurable concurrency
- Rate limiting to avoid blocking
"""

import argparse
import csv
import html as html_module
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE_URL = "https://www.onlinejobs.ph"
SITEMAP_URLS = [
    f"{BASE_URL}/sitemap2.xml",
    f"{BASE_URL}/sitemap3.xml",
    f"{BASE_URL}/sitemap4.xml",
]
SKILLSEARCH_URL = f"{BASE_URL}/employers/skillsearch/all/a181a603769c1f98ad927e7367c7aa5112147425"
SKILLSEARCH_MAX_OFFSET = 9970
SKILLSEARCH_PAGE_SIZE = 30
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

PROGRESS_DIR = Path("/Users/aiserver/OPENCLAW BOT/ojp_progress")
PROGRESS_FILE = PROGRESS_DIR / "scan_progress.json"
IDS_FILE = PROGRESS_DIR / "profile_ids.json"
RESULTS_FILE = PROGRESS_DIR / "profiles.json"
BATCH_SIZE = 50
CONCURRENCY = 10  # parallel threads
REQUEST_DELAY = 0.2  # seconds between batches


def _ensure_progress_dir():
    PROGRESS_DIR.mkdir(parents=True, exist_ok=True)


def fetch_url(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text).strip()
    text = html_module.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text


def extract_ids_from_sitemaps() -> list:
    all_ids = []
    for sitemap_url in SITEMAP_URLS:
        try:
            xml = fetch_url(sitemap_url, timeout=30)
        except Exception as e:
            print(f"Error fetching {sitemap_url}: {e}", file=sys.stderr)
            continue
        ids = re.findall(r'/jobseekers/info/(\d+)', xml)
        all_ids.extend(ids)
        print(f"Sitemap {sitemap_url}: {len(ids)} IDs", file=sys.stderr)
        time.sleep(0.5)
    all_ids = sorted(set(all_ids), key=int)
    print(f"Total unique profile IDs from sitemaps: {len(all_ids)}", file=sys.stderr)
    return all_ids


def extract_ids_from_skillsearch() -> list:
    all_ids = set()
    total_pages = SKILLSEARCH_MAX_OFFSET // SKILLSEARCH_PAGE_SIZE + 1
    print(f"Skillsearch: fetching {total_pages} pages (offset 0-{SKILLSEARCH_MAX_OFFSET})...", file=sys.stderr)
    for offset in range(0, SKILLSEARCH_MAX_OFFSET + 1, SKILLSEARCH_PAGE_SIZE):
        url = f"{SKILLSEARCH_URL}/{offset}"
        try:
            html_text = fetch_url(url, timeout=15)
        except Exception as e:
            print(f"  Error offset {offset}: {e}", file=sys.stderr)
            continue
        page_ids = set(re.findall(r'/jobseekers/info/(\d+)', html_text))
        new_count = len(page_ids - all_ids)
        all_ids.update(page_ids)
        page_num = offset // SKILLSEARCH_PAGE_SIZE + 1
        if page_num % 50 == 0 or new_count > 0:
            print(f"  Page {page_num}/{total_pages}: +{new_count} new, total {len(all_ids)}", file=sys.stderr)
        time.sleep(0.3)
    print(f"Skillsearch: {len(all_ids)} unique IDs", file=sys.stderr)
    return sorted(all_ids, key=int)


def parse_profile(html_text: str, url: str = "") -> dict:
    result = {
        "profile_id": "",
        "name": "",
        "title": "",
        "url": url,
        "id_proof_score": "",
        "employment_preference": "",
        "education": "",
        "last_active": "",
        "description": "",
        "overview": "",
        "skills_top": [],
        "skills_other": [],
        "hourly_rate": "",
        "availability": "",
        "category": "",
        "source": "onlinejobs_ph",
        "listing_type": "worker_profile",
    }

    profile_id = re.search(r"/jobseekers/info/(\d+)", url)
    if not profile_id:
        profile_id = re.search(r"profile[_\-]?id[\":\s]+(\d+)", html_text)
    result["profile_id"] = profile_id.group(1) if profile_id else ""

    h1_m = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, re.DOTALL)
    if h1_m:
        result["category"] = _clean(h1_m.group(1))

    name_m = re.search(r'jobseeker-name[^>]*>([^<]+)', html_text)
    if name_m:
        result["name"] = name_m.group(1).strip()
    if not result["name"]:
        name_m = re.search(r"Hi,\s*I'm\s+([A-Z][a-z]+)", html_text)
        if name_m:
            result["name"] = name_m.group(1)

    overview_m = re.search(r">Overview</h3>\s*(.*?)(?:<h3|<div\s+class=\"[^\"]*card)", html_text, re.DOTALL)
    if overview_m:
        text = re.sub(r"<[^>]+>", " ", overview_m.group(1))
        text = html_module.unescape(re.sub(r"\s+", " ", text).strip())
        text = re.sub(r"\s*(Wage Questions\?|Your browser).*", "", text).strip()
        result["overview"] = text[:300]
        rate_m = re.search(r"\$([\d,.]+)/hour", text)
        if rate_m:
            result["hourly_rate"] = "$" + rate_m.group(1) + "/hour"

    desc_m = re.search(r">Profile Description</h3>\s*(.*?)(?:<h3|</div>\s*</div>)", html_text, re.DOTALL)
    if desc_m:
        text = re.sub(r"<[^>]+>", " ", desc_m.group(1))
        text = html_module.unescape(re.sub(r"\s+", " ", text).strip())
        result["description"] = text[:500]

    top_skills_m = re.search(r">Top Skills</h3>(.*?)(?:<h3|</div>\s*</div>)", html_text, re.DOTALL)
    if top_skills_m:
        skills = re.findall(r'<a[^>]*href="/jobseekers/search/c/([^"]+)"[^>]*>([^<]+)</a>', top_skills_m.group(1))
        if not skills:
            skills_raw = re.findall(r'>([^<]{2,50})</a>', top_skills_m.group(1))
            skills = [(s.strip().lower().replace(" ", "_"), s.strip()) for s in skills_raw]
        result["skills_top"] = [{"slug": s[0], "name": s[1].strip()} for s in skills]

    other_skills_m = re.search(r">Other Skills</h3>(.*?)(?:<h3|</div>\s*</div>)", html_text, re.DOTALL)
    if other_skills_m:
        skills = re.findall(r'<a[^>]*href="/jobseekers/search/c/([^"]+)"[^>]*>([^<]+)</a>', other_skills_m.group(1))
        if not skills:
            skills_raw = re.findall(r'>([^<]{2,50})</a>', other_skills_m.group(1))
            skills = [(s.strip().lower().replace(" ", "_"), s.strip()) for s in skills_raw]
        result["skills_other"] = [{"slug": s[0], "name": s[1].strip()} for s in skills]

    idproof = re.search(r'jobseeker-id-prrof[^>]*>([^<]*)<', html_text)
    if idproof:
        val = idproof.group(1).strip()
        result["id_proof_score"] = val if val else "yes"

    if not result["hourly_rate"]:
        rate_m = re.search(r"\$([\d,.]+)/(?:hour|hr)", html_text)
        if rate_m:
            result["hourly_rate"] = "$" + rate_m.group(1) + "/hour"

    avail_m = re.search(r">Availability</h3>(.*?)(?:<h3|</div>\s*</div>)", html_text, re.DOTALL)
    if avail_m:
        text = re.sub(r"<[^>]+>", " ", avail_m.group(1))
        text = html_module.unescape(re.sub(r"\s+", " ", text).strip())
        result["availability"] = text[:200]

    last_active_m = re.search(r"Last Active</strong></p>\s*<p[^>]*>([^<]+)<", html_text)
    if last_active_m:
        result["last_active"] = last_active_m.group(1).strip()

    is_active = bool(result["name"] or result["description"] or result["skills_top"])
    result["is_active"] = is_active

    return result


def fetch_profile_detail(profile_id: str) -> dict:
    url = f"{BASE_URL}/jobseekers/info/{profile_id}"
    html_text = fetch_url(url)
    result = parse_profile(html_text, url)
    result["profile_id"] = profile_id
    return result


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text())
        except Exception:
            pass
    return {"processed_ids": [], "errors": [], "last_batch": 0, "total_found": 0, "started_at": "", "last_updated": ""}


def save_progress(progress: dict):
    _ensure_progress_dir()
    PROGRESS_FILE.write_text(json.dumps(progress, ensure_ascii=False))


def save_ids(ids: list):
    _ensure_progress_dir()
    IDS_FILE.write_text(json.dumps(ids))


def load_ids() -> list:
    if IDS_FILE.exists():
        try:
            return json.loads(IDS_FILE.read_text())
        except Exception:
            pass
    return []


def load_results() -> list:
    if RESULTS_FILE.exists():
        try:
            return json.loads(RESULTS_FILE.read_text())
        except Exception:
            pass
    return []


def save_results(results: list):
    _ensure_progress_dir()
    RESULTS_FILE.write_text(json.dumps(results, ensure_ascii=False))


def phase1_sitemap_scan(sitemap_only: bool = False) -> list:
    print("Phase 1a: Downloading sitemaps...", file=sys.stderr)
    sitemap_ids = extract_ids_from_sitemaps()

    if sitemap_only:
        save_ids(sitemap_ids)
        print(f"Phase 1 complete (sitemap only): {len(sitemap_ids)} profile IDs")
        return sitemap_ids

    time.sleep(1)
    print("Phase 1b: Fetching skillsearch pages...", file=sys.stderr)
    skillsearch_ids = extract_ids_from_skillsearch()

    all_ids = sorted(set(sitemap_ids + skillsearch_ids), key=int)
    save_ids(all_ids)
    print(f"Phase 1 complete: {len(all_ids)} unique profile IDs ({len(sitemap_ids)} sitemap + {len(skillsearch_ids)} skillsearch)")
    return all_ids


def phase2_fetch_details(ids: list = None, start_from: int = 0, max_profiles: int = 0, batch_callback=None) -> dict:
    if ids is None:
        ids = load_ids()
    if not ids:
        print("No IDs loaded. Run phase1 first.", file=sys.stderr)
        return {"error": "no_ids"}

    progress = load_progress()
    results = load_results()
    processed_set = set(str(p) for p in progress.get("processed_ids", []))
    error_set = set(str(p) for p in progress.get("errors", []))

    if not progress.get("started_at"):
        import datetime
        progress["started_at"] = datetime.datetime.now().isoformat()

    ids_to_process = [pid for pid in ids if pid not in processed_set and pid not in error_set]
    if start_from > 0:
        ids_to_process = ids_to_process[start_from:]
    if max_profiles > 0:
        ids_to_process = ids_to_process[:max_profiles]

    print(f"Phase 2: Fetching {len(ids_to_process)} profiles (already processed: {len(processed_set)}, conc={CONCURRENCY})", file=sys.stderr)

    fetched = 0
    new_errors = 0
    total_active = sum(1 for r in results if r.get("is_active"))

    total = len(ids_to_process)
    
    def fetch_single(pid):
        """Fetch single profile - used by thread pool"""
        try:
            url = f"{BASE_URL}/jobseekers/info/{pid}"
            html_text = fetch_url(url, timeout=10)
            profile = parse_profile(html_text, url)
            profile["profile_id"] = pid
            return profile, None
        except Exception as e:
            return None, str(e)

    import datetime
    
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        futures = {}
        batch_num = 0
        
        for i, pid in enumerate(ids_to_process):
            future = executor.submit(fetch_single, pid)
            futures[future] = pid
            
            if len(futures) >= CONCURRENCY * 2 or i == total - 1:
                for completed in as_completed(futures):
                    pid = futures[completed]
                    try:
                        profile, error = completed.result()
                        if profile:
                            results.append(profile)
                            fetched += 1
                            if profile.get("is_active"):
                                total_active += 1
                            processed_set.add(pid)
                        else:
                            error_set.add(pid)
                            new_errors += 1
                    except Exception as e:
                        error_set.add(pid)
                        new_errors += 1
                    del futures[completed]
                
                batch_num += 1
                if batch_num % 5 == 0:
                    progress["processed_ids"] = list(processed_set)
                    progress["errors"] = list(error_set)
                    progress["last_batch"] = batch_num
                    progress["total_found"] = len(results)
                    progress["total_active"] = total_active
                    progress["last_updated"] = datetime.datetime.now().isoformat()
                    save_progress(progress)
                    save_results(results)
                    print(f"  Batch {batch_num}: fetched={fetched}, errors={new_errors}, active={total_active}/{len(results)}", file=sys.stderr)
                
                time.sleep(REQUEST_DELAY)

    progress["processed_ids"] = list(processed_set)
    progress["errors"] = list(error_set)
    progress["last_updated"] = datetime.datetime.now().isoformat()
    progress["completed_at"] = datetime.datetime.now().isoformat()
    progress["total_active"] = total_active
    save_progress(progress)
    save_results(results)

    print(f"\nPhase 2 complete: {fetched} profiles, {new_errors} errors, {total_active} active", file=sys.stderr)
    return {"total_ids": len(ids), "processed": len(processed_set), "fetched": fetched, "errors": new_errors, "results_count": len(results), "active": total_active}


def export_to_csv(results: list = None, output_path: str = "") -> str:
    if results is None:
        results = load_results()
    if not results:
        print("No results to export", file=sys.stderr)
        return ""

    if not output_path:
        output_path = str(PROGRESS_DIR / "profiles.csv")

    active = [r for r in results if r.get("is_active")]
    print(f"Exporting {len(active)} active profiles out of {len(results)} total", file=sys.stderr)

    fieldnames = ["profile_id", "name", "category", "hourly_rate", "id_proof_score",
                  "skills_top", "skills_other", "overview", "description",
                  "availability", "last_active", "url", "source", "listing_type"]
    csv_headers = fieldnames

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=csv_headers, extrasaction="ignore")
        writer.writeheader()
        for row in active:
            clean = {}
            for k in csv_headers:
                v = row.get(k, "")
                if isinstance(v, list):
                    v = ", ".join(str(x) if isinstance(x, str) else x.get("name", str(x)) for x in v)
                clean[k] = str(v) if v else ""
            writer.writerow(clean)

    print(f"Exported {len(active)} active profiles to {output_path}", file=sys.stderr)
    return output_path


def get_status() -> dict:
    ids = load_ids()
    progress = load_progress()
    results = load_results()
    processed = len(progress.get("processed_ids", []))
    errors = len(progress.get("errors", []))
    total = len(ids)
    pct = round(processed / total * 100, 1) if total else 0
    active = sum(1 for r in results if r.get("is_active"))
    return {
        "total_ids": total,
        "processed": processed,
        "errors": errors,
        "results_count": len(results),
        "active_profiles": active,
        "progress_pct": pct,
        "started_at": progress.get("started_at", ""),
        "last_updated": progress.get("last_updated", ""),
        "completed_at": progress.get("completed_at", ""),
    }


def _cli_main():
    p = argparse.ArgumentParser(description="OnlineJobs.ph Bulk Profile Scanner v2")
    p.add_argument("--mode", choices=["phase1", "phase1sitemap", "phase2", "status", "export", "full", "quick"], default="status")
    p.add_argument("--start-from", type=int, default=0, help="Resume from index N")
    p.add_argument("--max-profiles", type=int, default=0, help="Limit profiles to fetch (0=all)")
    p.add_argument("--output", default="", help="Output file path for export")
    args = p.parse_args()

    if args.mode == "phase1sitemap":
        ids = phase1_sitemap_scan(sitemap_only=True)
        print(json.dumps({"total_ids": len(ids), "source": "sitemap"}, ensure_ascii=False))

    elif args.mode == "phase1":
        ids = phase1_sitemap_scan()
        print(json.dumps({"total_ids": len(ids)}, ensure_ascii=False))

    elif args.mode == "phase2":
        ids = load_ids()
        if not ids:
            ids = phase1_sitemap_scan(sitemap_only=True)
        result = phase2_fetch_details(ids, start_from=args.start_from, max_profiles=args.max_profiles)
        print(json.dumps(result, ensure_ascii=False))

    elif args.mode == "export":
        path = export_to_csv(output_path=args.output)
        print(json.dumps({"path": path, "count": len(load_results())}, ensure_ascii=False))

    elif args.mode == "status":
        status = get_status()
        print(json.dumps(status, ensure_ascii=False, indent=2))

    elif args.mode == "full":
        ids = phase1_sitemap_scan()
        result = phase2_fetch_details(ids, max_profiles=args.max_profiles)
        export_to_csv()
        print(json.dumps(result, ensure_ascii=False))

    elif args.mode == "quick":
        ids = phase1_sitemap_scan()
        quick_results = []
        for pid in ids[:100]:
            quick_results.append({
                "profile_id": pid,
                "url": f"{BASE_URL}/jobseekers/info/{pid}",
                "source": "onlinejobs_ph",
                "listing_type": "worker_profile",
            })
        print(json.dumps({"total_ids": len(ids), "results": quick_results}, ensure_ascii=False))


if __name__ == "__main__":
    _cli_main()