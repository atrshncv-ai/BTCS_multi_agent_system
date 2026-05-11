import time
import sys
import urllib.request
import urllib.parse
import re
import csv
import json
from urllib.parse import urljoin, urlparse


BASE_URL = "https://prian.ru"
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}


def fetch_page(page_url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(page_url, headers=DEFAULT_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def is_valid_company_url(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    if not parsed.netloc:
        return False
    if "prian.ru" not in parsed.netloc:
        return False
    if "/company/" not in url:
        return False
    if not re.search(r'/company/[\w-]+\.html', url):
        return False
    return True


COUNTRY_MAP = {
    "47": "Черногория", "1": "Испания", "2": "Кипр", "3": "Турция",
    "4": "Болгария", "5": "Таиланд", "6": "Греция", "7": "ОАЭ",
    "8": "Италия", "9": "Франция", "10": "Германия", "11": "Португалия",
    "12": "Грузия", "13": "Сербия", "14": "Хорватия", "15": "Чехия",
    "16": "Венгрия", "17": "Финляндия", "18": "Великобритания",
    "19": "США", "20": "Индонезия", "21": "Вьетнам", "22": "Шри-Ланка",
    "23": "Мальта", "24": "Польша", "25": "Австрия", "26": "Швеция",
    "27": "Бали", "28": "Монако", "29": "Андорра", "30": "Словения",
    "31": "Монтенегро", "32": "Мальдивы", "33": "Египет", "34": "Камбоджа",
}


def _extract_company_data(html: str, url: str) -> dict:
    result = {
        "company_url": url,
        "company_name": "",
        "description": "",
        "phones": [],
        "emails": [],
        "whatsapp": "",
        "telegram": "",
        "manager_name": "",
        "manager_position": "",
        "manager_languages": "",
        "total_objects": 0,
        "countries": [],
    }

    name_match = re.search(r'<h1[^>]*>([^<]+)<', html)
    if name_match:
        result["company_name"] = name_match.group(1).strip()

    desc_match = re.search(r'<meta[^>]*name="description"[^>]*content="([^"]+)"', html)
    if not desc_match:
        desc_match = re.search(r'<meta[^>]*content="([^"]+)"[^>]*name="description"', html)
    if desc_match:
        result["description"] = desc_match.group(1).strip()

    phone_matches = re.findall(r'tel:([^"<]+)', html)
    result["phones"] = list(set(p.strip() for p in phone_matches if p.strip()))

    email_matches = re.findall(r'mailto:([^"<]+)', html)
    result["emails"] = list(set(e.strip() for e in email_matches if e.strip() and "@" in e))

    wa_match = re.search(r'href="https?://wa\.me/(\d+[^?"]*)"', html)
    if wa_match:
        result["whatsapp"] = "https://wa.me/" + wa_match.group(1)

    tg_match = re.search(r'href="https?://t\.me/([^"?]+)"', html)
    if tg_match:
        result["telegram"] = "https://t.me/" + tg_match.group(1)

    mgr_match = re.search(r'<p[^>]*class="name"[^>]*>([^<]+)<', html)
    if mgr_match:
        result["manager_name"] = mgr_match.group(1).strip()

    pos_match = re.search(r'<p[^>]*class="post"[^>]*>([^<]+)<', html)
    if pos_match:
        result["manager_position"] = pos_match.group(1).strip()

    lng_match = re.search(r'<p[^>]*class="lng"[^>]*>([^<]+)<', html)
    if lng_match:
        result["manager_languages"] = lng_match.group(1).strip()

    fcountry = re.search(r'name="fcountry"[^>]*value="(\d+)"', html)
    if fcountry:
        cid = fcountry.group(1)
        if cid in COUNTRY_MAP:
            result["countries"] = [COUNTRY_MAP[cid]]
        else:
            result["countries"] = [cid]
    else:
        country_links = re.findall(r'/country/([^/"]+)', html)
        if country_links:
            result["countries"] = sorted(set(c.replace("-", " ").title() for c in country_links if c and len(c) < 30))

    all_objects_match = re.search(r'Все объекты компании\s*\((\d[\d\s]*)\)', html)
    if all_objects_match:
        num_str = all_objects_match.group(1).replace("\xa0", "").replace(" ", "").strip()
        try:
            result["total_objects"] = int(num_str)
        except ValueError:
            pass
    if result["total_objects"] == 0:
        next_vals = re.findall(r'next=(\d+)', html)
        if next_vals:
            result["total_objects"] = max(int(n) for n in next_vals) + 30
    if result["total_objects"] == 0:
        result["total_objects"] = len(re.findall(r'class="obj-min', html))

    return result


def parse_company(url: str, max_pages: int = 3):
    if not is_valid_company_url(url):
        raise ValueError("Invalid company URL")

    html = fetch_page(url)
    return _extract_company_data(html, url)


def parse_company_catalog(url: str = "https://prian.ru/company/", max_pages: int = 20):
    all_companies = []
    current_url = url
    seen_ids = set()

    for page in range(max_pages):
        try:
            html = fetch_page(current_url)
        except Exception:
            break

        company_ids = re.findall(r'/company/([\w-]+)\.html', html)
        for cid in company_ids:
            if cid not in seen_ids:
                seen_ids.add(cid)
                company_url = f"https://prian.ru/company/{cid}.html"

                name_match = re.search(
                    rf'company/{re.escape(cid)}\.html"[^>]*>([^<]+)<', html
                )
                company_name = name_match.group(1).strip() if name_match else cid

                obj_count = 0
                count_match = re.search(
                    rf'company/{re.escape(cid)}\.html[^"]*"[^>]*>[^<]*</a[^>]*>[^<]*?(?:<[^>]*>[^<]*</[^>]*>)*[^<]*?\((\d[\d\s]*)\)',
                    html
                )
                if count_match:
                    try:
                        obj_count = int(count_match.group(1).replace("\xa0", "").replace(" ", "").strip())
                    except ValueError:
                        pass

                all_companies.append({
                    "company_id": cid,
                    "company_url": company_url,
                    "company_name": company_name,
                    "total_objects": obj_count,
                })

        next_vals = re.findall(r'next=(\d+)', html)
        if not next_vals:
            break

        max_next = max(int(n) for n in next_vals)
        current_next = 0
        nm = re.search(r'next=(\d+)', current_url)
        if nm:
            current_next = int(nm.group(1))

        if current_next >= max_next:
            break

        if "next=" in current_url:
            current_url = re.sub(r'next=\d+', f'next={current_next + 15}', current_url)
        else:
            current_url = current_url.rstrip("/") + "?next=15"

    return all_companies


def enrich_companies(companies: list, max_workers: int = 3):
    enriched = []
    for i, comp in enumerate(companies):
        url = comp["company_url"]
        try:
            html = fetch_page(url)
            data = _extract_company_data(html, url)
            comp.update({k: v for k, v in data.items() if v or k == "total_objects"})
        except Exception as e:
            comp["error"] = str(e)

        enriched.append(comp)
        if (i + 1) % 10 == 0:
            print(f"Enriched {i + 1}/{len(companies)}", file=sys.stderr)

    return enriched


def _cli_main():
    import argparse
    parser = argparse.ArgumentParser(description="Prian Company Parser")
    parser.add_argument("--url", required=True, help="Company URL, 'catalog' for all, or 'enrich' for catalog+contacts")
    parser.add_argument("--max-pages", type=int, default=20)
    args = parser.parse_args()

    try:
        if args.url == "catalog":
            result = parse_company_catalog(max_pages=args.max_pages)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.url == "enrich":
            catalog = parse_company_catalog(max_pages=args.max_pages)
            enriched = enrich_companies(catalog)
            print(json.dumps(enriched, ensure_ascii=False, indent=2))
        else:
            result = parse_company(args.url, max_pages=args.max_pages)
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    _cli_main()