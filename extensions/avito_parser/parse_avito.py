import time
import requests
from bs4 import BeautifulSoup
import csv
import os
import json
import argparse
from urllib.parse import urljoin

def is_valid_avito_url(url: str) -> bool:
    return url.startswith("http") and "avito.ru" in url

def fetch_avito_items(page_url: str, max_items: int = 50):
    headers = {"User-Agent": "OpenClaw-AvitoParser/1.0"}
    resp = requests.get(page_url, headers=headers, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    items = []
    for card in soup.find_all(attrs={"data-marker": "item"}):
        a = card.find("a", href=True)
        item_url = urljoin("https://www.avito.ru", a["href"]) if a and a["href"] else page_url
        title_tag = card.find(attrs={"data-marker": "item-title"})
        title = title_tag.get_text(strip=True) if title_tag else ""
        price_tag = card.find(attrs={"data-marker": "item-price"})
        price = price_tag.get_text(strip=True) if price_tag else ""
        location = ""
        loc_tag = card.find(attrs={"data-marker": "item-address"})
        if loc_tag:
            location = loc_tag.get_text(strip=True)
        items.append({"title": title, "price": price, "location": location, "url": item_url})
        if len(items) >= max_items:
            break
    return items

def items_to_csv(rows, file_path: str):
    fieldnames = ["title", "price", "location", "url"]
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    return file_path

def parse_avito(url: str, max_items: int = 50):
    if not is_valid_avito_url(url):
        raise ValueError("Invalid Avito URL")
    items = fetch_avito_items(url, max_items=max_items)
    csv_path = ""
    if items:
        csv_path = "/tmp/avito_parsed_" + str(int(time.time())) + ".csv"
        items_to_csv(items, csv_path)
    return {"records": items, "csv_path": csv_path}


def _cli_main():
    parser = argparse.ArgumentParser(description="Avito Parser CLI")
    parser.add_argument("--url", required=True, help="Avito URL to parse (category/search page)")
    parser.add_argument("--max-items", type=int, default=50, help="Maximum items to parse")
    parser.add_argument("--output", default="avito_parsed.csv", help="Output CSV path (optional)")
    args = parser.parse_args()
    res = parse_avito(args.url, max_items=args.max_items)
    # Print JSON to stdout for easy consumption by other components
    print(json.dumps(res))


if __name__ == "__main__":
    _cli_main()
