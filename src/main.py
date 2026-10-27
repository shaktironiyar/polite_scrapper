import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

START_URL = "https://books.toscrape.com/catalogue/page-1.html"
CACHE_DIR = Path("cache")
USER_AGENT = "FlyRankInternshipA9/1.0 (+https://github.com/YOUR_USER/YOUR_REPO)"
TIMEOUT = 10        # seconds
MIN_DELAY = 0.5     # seconds between REAL requests
MAX_PAGES = 3

_last_request_at = 0.0


def fetch(url: str, cache_name: str) -> str | None:
    """HTML from cache if present, else from the site (politely). None on failure."""
    global _last_request_at
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / cache_name

    if path.exists():
        html = path.read_text(encoding="utf-8")
        print(f"CACHE HIT  {cache_name}  {len(html)} chars")
        return html

    # polite delay: only real requests count
    wait = MIN_DELAY - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)

    try:
        _last_request_at = time.monotonic()
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    except requests.RequestException as e:
        print(f"FAILED     {url}  {e}")
        return None

    if resp.status_code != 200:
        print(f"FAILED     {url}  status={resp.status_code}")
        return None

    resp.encoding = "utf-8"
    path.write_text(resp.text, encoding="utf-8")
    print(f"FETCH      {cache_name}  {len(resp.text)} chars")
    return resp.text


def parse_catalogue(html: str, page_url: str) -> tuple[list[str], str | None]:
    """Return (absolute book URLs on this page, absolute next-page URL or None)."""
    soup = BeautifulSoup(html, "html.parser")

    book_urls = [
        urljoin(page_url, a["href"])
        for a in soup.select("article.product_pod h3 a[href]")
    ]

    next_a = soup.select_one("li.next a[href]")
    next_url = urljoin(page_url, next_a["href"]) if next_a else None
    return book_urls, next_url


def discover_books() -> tuple[list[dict], int]:
    """Crawl up to MAX_PAGES catalogue pages. Return (links with source page, pages visited)."""
    found: list[dict] = []
    page_url: str | None = START_URL
    pages = 0

    while page_url and pages < MAX_PAGES:
        pages += 1
        html = fetch(page_url, f"catalogue-page-{pages}.html")
        if html is None:
            break
        book_urls, next_url = parse_catalogue(html, page_url)
        found.extend({"product_url": u, "source_page": page_url} for u in book_urls)
        page_url = next_url

    return found, pages


def dedupe(found: list[dict]) -> list[dict]:
    """Keep the first occurrence of each product_url, preserving order."""
    unique = {}
    for item in found:
        unique.setdefault(item["product_url"], item)
    return list(unique.values())

def cache_name_for_book(url: str) -> str:
    slug = url.rstrip("/").split("/")[-2]   # e.g. a-light-in-the-attic_1000
    return f"book-{slug}.html"


def fetched_at(cache_name: str) -> str:
    """When the cached file was written, as UTC ISO-8601."""
    mtime = (CACHE_DIR / cache_name).stat().st_mtime
    return datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_book(html: str, product_url: str, source_page: str, fetched: str) -> dict:
    """Extract the 8 raw fields from one book detail page."""
    soup = BeautifulSoup(html, "html.parser")
    product = soup.select_one("article.product_page")
    main = product.select_one("div.product_main")

    title = main.select_one("h1").get_text(strip=True)
    price_text = main.select_one("p.price_color").get_text(strip=True)
    availability_text = " ".join(main.select_one("p.availability").get_text().split())

    rating_el = main.select_one("p.star-rating")
    rating_text = next((c for c in rating_el["class"] if c != "star-rating"), None)

    desc_el = product.select_one("#product_description + p")
    description = (desc_el.get_text(strip=True) or None) if desc_el else None

    return {
        "title": title,
        "product_url": product_url,
        "price_text": price_text,
        "availability_text": availability_text,
        "rating_text": rating_text,
        "description": description,
        "source_page": source_page,
        "fetched_at": fetched,
    }


def extract_details(items: list[dict]) -> list[dict]:
    records = []
    for item in items:
        url = item["product_url"]
        name = cache_name_for_book(url)
        html = fetch(url, name)
        if html is None:
            continue  # Stage 5 will log and count this properly
        records.append(parse_book(html, url, item["source_page"], fetched_at(name)))
    return records


if __name__ == "__main__":
    import json

    found, pages = discover_books()
    unique = dedupe(found)
    print(f"catalogue_pages={pages}, discovered={len(found)}, unique_urls={len(unique)}")

    records = extract_details(unique)
    print(json.dumps(records[0], indent=2, ensure_ascii=False))
    print(f"detail_pages={len(records)}")

    

