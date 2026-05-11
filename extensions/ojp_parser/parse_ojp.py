"""
OnlineJobs.ph Bulk Parser — scrapes all active jobs and worker profiles by category.

Jobs: ~300 active, paginated search (30/page)
Workers: ~3M profiles, accessed by category via /hire/{slug} pages
Profiles by ID: /jobseekers/info/{id} — for individual detail extraction
"""

import argparse
import csv
import html as html_module
import json
import re
import time
import urllib.request
import urllib.parse
import sys

BASE_URL = "https://www.onlinejobs.ph"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

CATEGORIES = [
    "virtual-assistant", "seo", "marketing", "customer-support", "design",
    "e-commerce", "accounting", "real-estate", "project-management", "video-editing",
    "research", "advertising", "content-creation", "web-development", "web-programming",
    "website-builder", "office-and-administration", "human-resources", "sales-support",
    "telemarketing", "construction-and-engineering", "professional-services",
    "audio-editing", "coaching", "cloud-services", "loan-processing", "patent-drafting",
    "software", "systems-administration", "artificial-intelligence", "mobile-development",
]


def fetch_page(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text).strip()
    text = html_module.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text


def extract_text(pattern: str, html: str, default: str = "") -> str:
    m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
    if m:
        text = _clean(m.group(1))
    return default


def parse_job_search(html: str) -> list:
    results = []
    chunks = re.split(r'data-temp="[^"]*"', html)
    for i, chunk in enumerate(chunks[1:], 1):
        job = {
            "title": "", "job_id": "", "url": "", "employer": "",
            "job_type": "", "salary": "", "description": "",
            "skills": [], "posted_date": "", "source": "onlinejobs_ph",
            "listing_type": "job_search",
        }
        title_m = re.search(r'<h4[^>]*class="[^"]*fs-16[^"]*"[^>]*>(.*?)</h4>', chunk, re.DOTALL)
        if title_m:
            job["title"] = _clean(title_m.group(1))
        link_m = re.search(r'href="/jobseekers/job/([^"]+)"', chunk)
        if link_m:
            slug = link_m.group(1)
            job["url"] = BASE_URL + "/jobseekers/job/" + slug
            id_m = re.search(r"(\d+)$", slug)
            job["job_id"] = id_m.group(1) if id_m else slug
        type_m = re.search(r"(Full Time|Part Time|Gig|Any)", chunk, re.IGNORECASE)
        if type_m:
            job["job_type"] = type_m.group(1)
        salary_m = re.search(r"\$[\d,]+(?:\.\d+)?(?:\s*/?\s*(?:hour|hr|month|mo|week|wk|day))?", chunk, re.IGNORECASE)
        if salary_m:
            job["salary"] = salary_m.group(0)
        desc_m = re.search(r'<div[^>]*class="[^"]*desc[^"]*"[^>]*>(.*?)</div>', chunk, re.DOTALL)
        if desc_m:
            job["description"] = _clean(desc_m.group(1))[:200]
        skill_ms = re.findall(r'<a[^>]*href="/jobseekers/search/c/([^"]+)"[^>]*>([^<]+)<', chunk)
        job["skills"] = [{"slug": s[0], "name": s[1].strip()} for s in skill_ms]
        date_m = re.match(r'([^"]+)"', chunks[i]) if i < len(chunks) else None
        if date_m:
            job["posted_date"] = date_m.group(1)
        if job["title"] or job["url"]:
            results.append(job)
    return results


def parse_job_detail(html: str, url: str = "") -> dict:
    result = {
        "title": "", "job_id": "", "url": url, "employer": "",
        "employer_id": "", "job_type": "", "salary": "", "hours_per_week": "",
        "description": "", "skills": [], "posted_date": "",
        "source": "onlinejobs_ph", "listing_type": "job_detail",
    }
    title_m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL)
    if title_m:
        result["title"] = _clean(title_m.group(1))
    job_id = re.search(r"\"job_id\":\s*\"(\d+)\"", html)
    if not job_id:
        job_id = re.search(r"/jobseekers/job/(?:.*?-)?(\d+)", url)
    result["job_id"] = job_id.group(1) if job_id else ""
    type_m = re.search(r">(Full Time|Part Time|Gig|Any)\s*<", html, re.IGNORECASE)
    if not type_m:
        type_m = re.search(r'<p[^>]*class="[^"]*fs-18[^"]*"[^>]*>\s*(Full Time|Part Time|Gig|Any)\s*</p>', html, re.IGNORECASE)
    if type_m:
        result["job_type"] = type_m.group(1).strip()
    logo_m = re.search(r"employer_logos/(\d+)/", html)
    if logo_m:
        result["employer_id"] = logo_m.group(1)
    desc_m = re.search(r'<p[^>]*id="job-description"[^>]*>(.*?)</p>', html, re.DOTALL)
    if desc_m:
        result["description"] = _clean(desc_m.group(1))[:2000]
    skill_ms = re.findall(r'<a[^>]*href="/jobseekers/search/c/([^"]+)"[^>]*>([^<]+)<', html)
    result["skills"] = [{"slug": s[0], "name": s[1].strip()} for s in skill_ms]
    dt_pairs = re.findall(r"<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", html, re.DOTALL)
    for dt, dd in dt_pairs:
        dt_clean = _clean(dt).lower()
        dd_clean = _clean(dd)
        if any(k in dt_clean for k in ["salary", "wage", "rate"]):
            result["salary"] = dd_clean
        elif "hour" in dt_clean:
            result["hours_per_week"] = dd_clean
        elif any(k in dt_clean for k in ["date", "updated", "posted"]):
            result["posted_date"] = dd_clean
    salary_m = re.search(r"\$[\d,]+(?:\.\d+)?(?:\s*/?\s*(?:hour|hr|month|mo|week|wk|day))?", html, re.IGNORECASE)
    if salary_m and not result["salary"]:
        result["salary"] = salary_m.group(0)
    return result


def parse_profile(html: str, url: str = "") -> dict:
    result = {
        "profile_id": "", "name": "", "title": "", "url": url,
        "id_proof_score": "", "employment_preference": "", "education": "",
        "last_active": "", "description": "", "skills": [], "hourly_rate": "",
        "source": "onlinejobs_ph", "listing_type": "worker_profile",
    }
    profile_id = re.search(r"/jobseekers/info/(\d+)", url)
    if not profile_id:
        profile_id = re.search(r"profile[_-]?id[\":\s]+(\d+)", html)
    result["profile_id"] = profile_id.group(1) if profile_id else ""
    name_m = re.search(r"Hi,\s*I'm\s+([A-Z][a-z]+)", html)
    if not name_m:
        name_m = re.search(r'<h[1-6][^>]*class="[^"]*(?:name|profile)[^"]*"[^>]*>([^<]+)<', html)
    result["name"] = name_m.group(1).strip() if name_m else ""
    idproof = re.search(r'data-cy="idproof-value"[^>]*>(\d+)<', html)
    if idproof:
        result["id_proof_score"] = idproof.group(1)
    rate_m = re.search(r"\$(\d[\d,.]*(?:\.\d+)?)/hour", html)
    if rate_m:
        result["hourly_rate"] = "$" + rate_m.group(1) + "/hour"
    skill_ms = re.findall(r'<a[^>]*class="[^"]*rounded-full[^"]*"[^>]*>([^<]+)</a>', html)
    result["skills"] = [s.strip() for s in skill_ms if s.strip()]
    return result


def fetch_all_jobs(keyword: str = "", max_pages: int = 100) -> list:
    all_jobs = []
    seen_ids = set()
    for page in range(1, max_pages + 1):
        params = {"isFromJobsearchForm": "1", "fullTime": "on", "partTime": "on", "gig": "on"}
        if keyword:
            params["jobkeyword"] = keyword
        if page > 1:
            params["page"] = str(page)
        qs = urllib.parse.urlencode(params)
        url = f"{BASE_URL}/jobseekers/jobsearch/{(page-1)*30}?{qs}" if page > 1 else f"{BASE_URL}/jobseekers/jobsearch?{qs}"
        if page > 1:
            url = f"{BASE_URL}/jobseekers/jobsearch/{(page-1)*30}?{qs}"
        try:
            html = fetch_page(url)
        except Exception as e:
            print(f"Error page {page}: {e}", file=sys.stderr)
            break
        total_match = re.search(r'search_result_count["\s:]+(\d+)', html)
        total = int(total_match.group(1)) if total_match else 0
        jobs = parse_job_search(html)
        new = 0
        for job in jobs:
            jid = job.get("job_id", "")
            if jid and jid not in seen_ids:
                seen_ids.add(jid)
                all_jobs.append(job)
                new += 1
        print(f"Page {page}: {new} new, {len(all_jobs)} total of ~{total}", file=sys.stderr)
        if new == 0 or len(all_jobs) >= total:
            break
        time.sleep(1.5)
    return all_jobs


def fetch_profiles_by_category(category: str = "virtual-assistant", max_pages: int = 50) -> list:
    all_profiles = []
    seen_ids = set()
    for page in range(1, max_pages + 1):
        url = f"{BASE_URL}/hire/{category}?page={page}" if page > 1 else f"{BASE_URL}/hire/{category}"
        try:
            html = fetch_page(url)
        except Exception as e:
            print(f"Error {category} page {page}: {e}", file=sys.stderr)
            break
        pids = re.findall(r'/jobseekers/info/(\d+)', html)
        new = 0
        for pid in pids:
            if pid not in seen_ids:
                seen_ids.add(pid)
                profile = {
                    "profile_id": pid,
                    "url": f"{BASE_URL}/jobseekers/info/{pid}",
                    "category": category,
                    "source": "onlinejobs_ph",
                    "listing_type": "worker_profile",
                }
                all_profiles.append(profile)
                new += 1
        print(f"{category} page {page}: {new} new, {len(all_profiles)} total", file=sys.stderr)
        if new == 0:
            break
        time.sleep(1.5)
    return all_profiles


def fetch_profile_detail(profile_id: str) -> dict:
    url = f"{BASE_URL}/jobseekers/info/{profile_id}"
    html = fetch_page(url)
    result = parse_profile(html, url)
    result["profile_id"] = profile_id
    return result


def fetch_all_categories_profiles(max_pages_per_category: int = 10) -> list:
    all_profiles = []
    seen_ids = set()
    for cat in CATEGORIES:
        print(f"Fetching category: {cat}", file=sys.stderr)
        profiles = fetch_profiles_by_category(cat, max_pages=max_pages_per_category)
        for p in profiles:
            if p["profile_id"] not in seen_ids:
                seen_ids.add(p["profile_id"])
                all_profiles.append(p)
        print(f"  {cat}: {len(profiles)} new, {len(all_profiles)} total", file=sys.stderr)
        time.sleep(2)
    return all_profiles


def items_to_csv(rows: list, file_path: str):
    if not rows:
        return ""
    all_keys = list(rows[0].keys())
    for row in rows:
        for k in row:
            if k not in all_keys:
                all_keys.append(k)
    skip = {"skills"}
    fieldnames = [k for k in all_keys if k not in skip]
    with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            clean = {}
            for k in fieldnames:
                v = row.get(k, "")
                if isinstance(v, list):
                    v = ", ".join(str(x) for x in v)
                clean[k] = v
            writer.writerow(clean)
    return file_path


def _cli_main():
    p = argparse.ArgumentParser(description="OnlineJobs.ph Bulk Parser")
    p.add_argument("--mode", choices=["jobs", "detail", "profiles", "all-profiles", "all-jobs"], default="jobs")
    p.add_argument("--keyword", default="", help="Search keyword for jobs")
    p.add_argument("--category", default="virtual-assistant")
    p.add_argument("--url", default="", help="Job or profile detail URL")
    p.add_argument("--max-pages", type=int, default=3)
    p.add_argument("--full-time", action="store_true", default=True)
    p.add_argument("--part-time", action="store_true", default=False)
    args = p.parse_args()

    if args.mode == "detail" and args.url:
        result = fetch_job_detail(args.url) if "/job/" in args.url else fetch_profile_detail(args.url.split("/")[-1])
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.mode == "all-profiles":
        results = fetch_all_categories_profiles(max_pages_per_category=args.max_pages)
        print(json.dumps({"count": len(results), "results": results}, ensure_ascii=False, indent=2))
    elif args.mode == "all-jobs":
        results = fetch_all_jobs(keyword=args.keyword, max_pages=args.max_pages)
        print(json.dumps({"count": len(results), "results": results}, ensure_ascii=False, indent=2))
    elif args.mode == "profiles":
        results = fetch_profiles_by_category(args.category, max_pages=args.max_pages)
        print(json.dumps({"count": len(results), "results": results}, ensure_ascii=False, indent=2))
    elif args.mode == "jobs":
        results = fetch_all_jobs(keyword=args.keyword, max_pages=args.max_pages)
        print(json.dumps({"count": len(results), "results": results}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"error": "Provide --url for detail mode or --keyword for jobs mode"}))


if __name__ == "__main__":
    _cli_main()