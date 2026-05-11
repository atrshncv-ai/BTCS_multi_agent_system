import time
import urllib.request
import re
import csv
import json
import argparse
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse


BASE_URL = "https://prian.ru"
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}


def is_valid_prian_url(url: str) -> bool:
    parsed = urlparse(url)
    if not parsed.netloc:
        return False
    return "prian.ru" in parsed.netloc


def normalize_url(url: str) -> str:
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return BASE_URL + url
    if url.startswith("http"):
        return url
    return BASE_URL + "/" + url


def fetch_page(page_url: str, timeout: int = 10) -> str:
    req = urllib.request.Request(page_url, headers=DEFAULT_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def extract_text(regex_pattern: str, html: str, default: str = "", group: int = 1) -> str:
    match = re.search(regex_pattern, html, re.DOTALL)
    if match:
        return match.group(group).strip()
    return default


def extract_all_text(regex_pattern: str, html: str) -> list:
    return re.findall(regex_pattern, html, re.DOTALL)


def extract_listings_regex(html: str) -> list:
    results = []
    
    card_pattern = r'<div[^>]*class="obj-min\s*[^\"]*"[^>]*>(.*?)</div>\s*</div>'
    cards = re.findall(card_pattern, html, re.DOTALL)
    
    for card in cards:
        result = {
            "title": "", "price": "", "location": "", "area": "",
            "bedrooms": "", "bathrooms": "", "url": "", "image_url": "",
            "description": "", "features": "",
            "company_name": "", "company_url": "",
            "agent_name": "", "agent_position": "", "agent_languages": "",
            "whatsapp": "", "telegram": "", "email": "", "phone": "",
            "listing_type": "listing",
        }
        
        title_match = re.search(r'<a[^>]*href="//prian\.ru/([^"]+)"[^>]*title="([^"]+)"', card)
        if title_match:
            result["url"] = "https://prian.ru/" + title_match.group(1)
            result["title"] = title_match.group(2)
            # Extract price from title (e.g. "Апартаменты за 160 000 евро")
            price_in_title = re.search(r'за\s*([\d\s]+)\s*(евро|€|руб|$)', result["title"], re.IGNORECASE)
            if price_in_title:
                result["price"] = price_in_title.group(1).strip() + " " + price_in_title.group(2).upper()
        
        if not result["title"]:
            title_match = re.search(r'<a[^>]*title="([^"]+)"[^>]*href', card)
            if title_match:
                result["title"] = title_match.group(1)
        
        price_match = re.search(r'<div[^>]*class="price"[^>]*>([^<]+)<', card)
        if price_match:
            result["price"] = price_match.group(1).strip()
        
        img_match = re.search(r'<img[^>]*data-srcset="([^"]+)"', card)
        if not img_match:
            img_match = re.search(r'<img[^>]*src="([^"]+(?:jpg|png|jpeg|webp)[^"]*)"', card, re.IGNORECASE)
        if img_match:
            img_url = img_match.group(1)
            if img_url.startswith("//"):
                img_url = "https:" + img_url
            result["image_url"] = img_url
        
        area_match = re.search(r'(\d+(?:\.\d+)?\s*м[²²])', card)
        if area_match and not result["area"]:
            result["area"] = area_match.group(1)
        
        bedroom_match = re.search(r'(\d+)\s*спал', card, re.IGNORECASE)
        if bedroom_match and not result["bedrooms"]:
            result["bedrooms"] = bedroom_match.group(1) + " спален"
        
        bathroom_match = re.search(r'(\d+)\s*ванн', card, re.IGNORECASE)
        if bathroom_match and not result["bathrooms"]:
            result["bathrooms"] = bathroom_match.group(1) + " ванных"
        
        location = ""
        for country in ["Турция", "Таиланд", "ОАЭ", "Испания", "Кипр", "Греция", "Болгария",
                         "Черногория", "Грузия", "Италия", "Франция", "Германия", "Португалия"]:
            if country.lower() in card.lower():
                location = country
                break
        result["location"] = location
        
        if result["title"] or result["url"]:
            results.append(result)
    
    return results


def extract_detail_regex(html: str, url: str = "") -> list:
    result = {
        "title": "", "price": "", "location": "", "area": "",
        "bedrooms": "", "bathrooms": "", "url": url, "image_url": "",
        "description": "", "features": "",
        "company_name": "", "company_url": "",
        "agent_name": "", "agent_position": "", "agent_languages": "",
        "whatsapp": "", "telegram": "", "email": "", "phone": "",
        "listing_type": "detail",
    }
    
    # Extract from JSON-LD schema
    json_ld_match = re.search(r'<script[^>]*type="application/ld\+json"[^>]*>(.+?)</script>', html, re.DOTALL)
    if json_ld_match:
        try:
            import json
            data = json.loads(json_ld_match.group(1))
            if isinstance(data, dict):
                result["title"] = data.get("name", "")
                offers = data.get("offers", {})
                if offers:
                    result["price"] = f"{offers.get('price', '')} {offers.get('priceCurrency', '')}"
                    addr = offers.get("availableAtOrFrom", {}).get("address", {})
                    if addr:
                        locality = addr.get("addressLocality", "")
                        country = addr.get("addressCountry", "")
                        result["location"] = f"{locality}, {country}".strip(", ")
                result["image_url"] = data.get("image", "")
                # Extract bedrooms/bathrooms from description
                desc = data.get("description", "")
                bed = re.search(r'(\d+)\s*спал', desc)
                bath = re.search(r'(\d+)\s*санузел|ванн', desc)
                if bed and not result["bedrooms"]:
                    result["bedrooms"] = bed.group(1) + " спален"
                if bath and not result["bathrooms"]:
                    result["bathrooms"] = bath.group(1) + " ванных"
        except Exception as e:
            pass
    
    # Fallback to h1
    if not result["title"]:
        h1_match = re.search(r'<h1[^>]*>([^<]+)<', html)
        if h1_match:
            result["title"] = h1_match.group(1).strip()
    
    price_match = re.search(r'<div[^>]*class="price"[^>]*>([€₽$\d\s,]+)<', html)
    if price_match and not result["price"]:
        result["price"] = price_match.group(1).strip()
    
    img_match = re.search(r'<img[^>]+alt="[^"]+"[^>]*src="([^"]+)"', html)
    if not img_match:
        img_match = re.search(r'<img[^>]*src="([^"]+(?:jpg|png|jpeg)[^"]*)"', html, re.IGNORECASE)
    if img_match:
        result["image_url"] = normalize_url(img_match.group(1))
    
    area_match = re.search(r'(\d+(?:\.\d+)?\s*м[²²])', html)
    if area_match:
        result["area"] = area_match.group(1)
    
    bedroom_match = re.search(r'(\d+)\s*спал', html, re.IGNORECASE)
    if bedroom_match:
        result["bedrooms"] = bedroom_match.group(1) + " спален"
    
    bathroom_match = re.search(r'(\d+)\s*ванн', html, re.IGNORECASE)
    if bathroom_match:
        result["bathrooms"] = bathroom_match.group(1) + " ванных"
    
    company_match = re.search(r'<a[^>]*href="/company/[^"]*"[^>]*>([^<]+)<', html)
    if company_match:
        result["company_name"] = company_match.group(1).strip()
        result["company_url"] = BASE_URL + "/company/"
    
    wa_match = re.search(r'href="(https?://wa\.me/[^"]+)"', html)
    if wa_match:
        result["whatsapp"] = wa_match.group(1).split("?")[0]
    
    tg_match = re.search(r'href="(https?://t\.me/[^"]+)"', html)
    if tg_match:
        result["telegram"] = tg_match.group(1)
    
    # Extract agent info from contacts block
    agent_name = re.search(r'<div[^>]*class="c-contacts__name"[^>]*>([^<]+)<', html)
    if agent_name:
        result["agent_name"] = agent_name.group(1).strip()
    
    agent_pos = re.search(r'<div[^>]*class="c-contacts__position"[^>]*>([^<]+)<', html)
    if agent_pos:
        result["agent_position"] = agent_pos.group(1).strip()
    
    agent_lng = re.search(r'<div[^>]*class="c-contacts__lng"[^>]*>([^<]+)<', html)
    if agent_lng:
        result["agent_languages"] = agent_lng.group(1).strip()
    
    # Company from contacts
    company_in_contacts = re.search(r'<a[^>]*href="/company/[^"]*"[^>]*>([^<]+)<', html)
    if company_in_contacts and not result["company_name"]:
        result["company_name"] = company_in_contacts.group(1).strip()
        result["company_url"] = BASE_URL + "/company/"
    
    email_match = re.search(r'href="(mailto:[^"]+@[^"]+)"', html)
    if email_match:
        result["email"] = email_match.group(1).replace("mailto:", "")
    
    phone_match = re.search(r'(\+[\d\s\(\)\-]{10,})', html)
    if phone_match:
        result["phone"] = phone_match.group(1).strip()
    
    return [result]


def extract_company_page_regex(html: str, page_url: str = "") -> list:
    results = []
    
    h1_match = re.search(r'<h1[^>]*>([^<]+)<', html)
    company_name = h1_match.group(1).strip() if h1_match else ""
    
    address_match = re.search(r'<address[^>]*>([^<]+)<', html)
    address = address_match.group(1).strip() if address_match else ""
    
    agent_blocks = re.findall(r'<div[^>]*class="wrap-face"[^>]*>(.*?)</div>\s*</div>', html, re.DOTALL)
    for block in agent_blocks:
        result = {
            "title": company_name,
            "price": "",
            "location": address,
            "area": "",
            "bedrooms": "",
            "bathrooms": "",
            "url": page_url,
            "image_url": "",
            "description": "",
            "features": "",
            "company_name": company_name,
            "company_url": page_url,
            "agent_name": "",
            "agent_position": "",
            "agent_languages": "",
            "whatsapp": "",
            "telegram": "",
            "email": "",
            "phone": "",
            "listing_type": "company_agent",
        }
        
        name_match = re.search(r'<p[^>]*class="name"[^>]*>([^<]+)<', block)
        if name_match:
            result["agent_name"] = name_match.group(1).strip()
        
        post_match = re.search(r'<p[^>]*class="post"[^>]*>([^<]+)<', block)
        if post_match:
            result["agent_position"] = post_match.group(1).strip()
        
        lng_match = re.search(r'<p[^>]*class="lng"[^>]*>([^<]+)<', block)
        if lng_match:
            result["agent_languages"] = lng_match.group(1).strip()
        
        wa_match = re.search(r'href="(https?://wa\.me/[^"]+)"', block)
        if wa_match:
            result["whatsapp"] = wa_match.group(1).split("?")[0]
        
        tg_match = re.search(r'href="(https?://t\.me/[^"]+)"', block)
        if tg_match:
            result["telegram"] = tg_match.group(1)
        
        email_match = re.search(r'href="(mailto:[^"]+)"', block)
        if email_match:
            result["email"] = email_match.group(1).replace("mailto:", "")
        
        if result["agent_name"]:
            results.append(result)
    
    listings = extract_listings_regex(html)
    for listing in listings:
        listing["company_name"] = company_name
        listing["company_url"] = page_url
        listing["listing_type"] = "company_listing"
        results.append(listing)
    
    return results


def extract_company_catalog_regex(html: str) -> list:
    results = []
    
    links = re.findall(r'<a[^>]*href="(/company/[^"]+\.html)"[^>]*>([^<]+)<', html)
    for href, text in links:
        if text and len(text) > 2 and len(text) < 100 and "Компании" not in text:
            results.append({
                "title": text.strip(),
                "company_name": text.strip(),
                "company_url": normalize_url(href),
                "listing_type": "company_catalog_item",
            })
    
    return results


def get_next_page_url(current_url: str, html: str) -> str:
    import re
    from urllib.parse import unquote
    # First try explicit next link from HTML
    next_match = re.search(r'<a[^>]*href="([^"]*&?next=\d+[^"]*)"', html)
    if next_match:
        href = next_match.group(1)
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = "https://prian.ru" + href
        elif not href.startswith("http"):
            href = "https://prian.ru/" + href
        # Use URL-encoded brackets as-is from HTML (don't decode/recode)
        return href
    
    # Build next param from decoded URL
    decoded_url = unquote(current_url)
    
    if "next=" in decoded_url:
        match = re.search(r'next=(\d+)', decoded_url)
        if match:
            new_val = int(match.group(1)) + 30
            # Replace in decoded URL
            start = match.start(1)
            end = match.end(1)
            new_url = decoded_url[:start] + str(new_val) + decoded_url[end:]
            # Fix bracket encoding - ensure consistent format type[] not type[0]
            new_url = re.sub(r'type%5B0%5D', 'type%5B%5D', new_url.replace('type[0]', 'type[]'))
            return new_url
    
    return ""


def get_max_pages(html: str, default: int = 50) -> int:
    """Extract max pages from pagination links"""
    import re
    matches = re.findall(r'next=(\d+)', html)
    if not matches:
        return default
    max_next = max(int(m) for m in matches if m.isdigit())
    # Allow up to 2000 pages
    return min((max_next // 30) + 5, 2000)


def get_page_type(url: str, html: str = "") -> str:
    if "/price/" in url and "/contact" not in url:
        return "detail"
    if "/company/" in url and ".html" in url:
        # Check if there's listing content (then it's paginated listing, not company info page)
        if "obj-min" in html and html.count("obj-min") > 1:
            return "listing"
        return "company_page"
    if "/company/" in url or "/search/" in url:
        return "company_catalog" if not html else "listing"
    return "listing"


def items_to_csv(rows: list, file_path: str):
    fieldnames = [
        "title", "price", "location", "area", "bedrooms", "bathrooms",
        "url", "image_url", "description", "features",
        "company_name", "company_url",
        "agent_name", "agent_position", "agent_languages",
        "whatsapp", "telegram", "email", "phone",
        "listing_type",
    ]
    with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fieldnames})
    return file_path


def fetch_prian_items(page_url: str, max_items: int = 50, max_pages: int = 3):
    all_items = []
    current_url = page_url
    pages_fetched = 0
    page_type = ""
    seen_urls = set()

    while len(all_items) < max_items and pages_fetched < max_pages:
        try:
            html = fetch_page(current_url)
            page_type = get_page_type(current_url, html)

            if pages_fetched == 0 and page_type == "listing":
                suggested_pages = get_max_pages(html, max_pages)
                max_pages = max(suggested_pages, max_pages)  # Use the larger value!

            if page_type == "detail":
                all_items.extend(extract_detail_regex(html, current_url))
                break
            elif page_type == "company_page":
                # Also extract listings, but continue to pagination!
                items = extract_listings_regex(html)
                for item in items:
                    if item.get("url", "") not in seen_urls:
                        seen_urls.add(item.get("url", ""))
                        all_items.append(item)
                # Don't break - continue to next pages
            elif page_type == "company_catalog":
                all_items.extend(extract_company_catalog_regex(html))
                break
            else:
                items = extract_listings_regex(html)
                if not items:
                    break
                
                new_urls = [item.get("url", "") for item in items if item.get("url") and item.get("url") not in seen_urls]
                
                if len(new_urls) == 0:
                    break
                
                for item in items:
                    item_url = item.get("url", "")
                    if item_url and item_url not in seen_urls:
                        seen_urls.add(item_url)
                        all_items.append(item)
                
                pages_fetched += 1
                
                next_url = _get_next_url_simple(current_url, pages_fetched)
                
                if not next_url or len(all_items) >= max_items:
                    break
                
                current_url = next_url
        except Exception as e:
            break

    return all_items[:max_items]


def _get_next_url_simple(url: str, page_num: int) -> str:
    """Simple next URL generator"""
    import re
    
    if page_num == 1:
        return url + ("&" if "?" in url else "?") + "next=30"
    
    match = re.search(r'next=(\d+)', url)
    if not match:
        return ""
    
    current_next = int(match.group(1))
    new_next = current_next + 30
    
    # Replace next=XX with next=YY preserving URL structure
    return re.sub(r'next=\d+', f'next={new_next}', url)


def parse_prian(url: str, max_items: int = 50, max_pages: int = 3):
    if not is_valid_prian_url(url):
        raise ValueError("Invalid Prian URL")
    items = fetch_prian_items(url, max_items=max_items, max_pages=max_pages)
    csv_path = ""
    if items:
        csv_path = "/tmp/prian_parsed_" + str(int(time.time())) + ".csv"
        items_to_csv(items, csv_path)
    return {"records": items, "csv_path": csv_path, "count": len(items)}


def _cli_main():
    parser = argparse.ArgumentParser(description="Prian Parser CLI")
    parser.add_argument("--url", required=True, help="Prian URL")
    parser.add_argument("--max-items", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=3)
    args = parser.parse_args()
    res = parse_prian(args.url, max_items=args.max_items, max_pages=args.max_pages)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli_main()