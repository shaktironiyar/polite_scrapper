import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
import json
import re
import sys

from pydantic import BaseModel, Field, ValidationError, field_validator

import requests
from bs4 import BeautifulSoup

START_URL = "https://books.toscrape.com/catalogue/page-1.html"
CACHE_DIR = Path("cache")
USER_AGENT = "FlyRankInternshipA9/1.0 (+https://github.com/YOUR_USER/YOUR_REPO)"
TIMEOUT = 10        # seconds
MIN_DELAY = 0.5     # seconds between REAL requests
MAX_PAGES = 3
OUTPUT_DIR = Path("output")
RETRY_WAIT = 2  # seconds before the single retry

STATS = {"pages_fetched": 0, "cache_hits": 0, "failed_pages": 0, "failed_urls": []}

_last_request_at = 0.0


def _fail(url: str, why: str) -> None:
    STATS["failed_pages"] += 1
    STATS["failed_urls"].append(url)
    print(f"FAILED     {url}  {why}")
    return None


def fetch(url: str, cache_name: str) -> str | None:
    """HTML from cache, else from the site (polite, one retry). None on failure."""
    global _last_request_at
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / cache_name

    if path.exists():
        html = path.read_text(encoding="utf-8")
        STATS["cache_hits"] += 1
        print(f"CACHE HIT  {cache_name}  {len(html)} chars")
        return html

    for attempt in (1, 2):
        wait = MIN_DELAY - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)

        try:
            _last_request_at = time.monotonic()
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
        except requests.RequestException as e:
            retryable = isinstance(e, (requests.Timeout, requests.ConnectionError))
            if retryable and attempt == 1:
                print(f"RETRY      {url}  {type(e).__name__}")
                time.sleep(RETRY_WAIT)
                continue
            return _fail(url, type(e).__name__)

        if resp.status_code == 200:
            resp.encoding = "utf-8"
            path.write_text(resp.text, encoding="utf-8")
            STATS["pages_fetched"] += 1
            print(f"FETCH      {cache_name}  {len(resp.text)} chars")
            return resp.text

        if resp.status_code >= 500 and attempt == 1:
            print(f"RETRY      {url}  status={resp.status_code}")
            time.sleep(RETRY_WAIT)
            continue

        return _fail(url, f"status={resp.status_code}")  # 404, 403, etc.: no retry


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
            continue  # already counted as failed by fetch()
        try:
            records.append(parse_book(html, url, item["source_page"], fetched_at(name)))
        except Exception as e:
            _fail(url, f"parse error: {type(e).__name__}: {e}")
    return records

class Book(BaseModel):
    title: str = Field(min_length=1)
    product_url: str
    price_text: str
    price_gbp: float = Field(ge=0)
    availability_text: str
    rating_text: str
    description: str | None = None
    source_page: str
    fetched_at: str

    @field_validator("product_url", "source_page")
    @classmethod
    def must_be_https(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("must start with https://")
        return v


def parse_price(text: str) -> float | None:
    match = re.search(r"\d+(?:\.\d+)?", text.replace(",", ""))
    return float(match.group()) if match else None


def normalize(raw: dict) -> dict:
    """Keep the raw fields and add the clean price next to them."""
    return {**raw, "price_gbp": parse_price(raw["price_text"])}


def validate_records(raws: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (valid unique records, errors). Identity is product_url."""
    good: dict[str, dict] = {}
    errors: list[dict] = []
    for raw in raws:
        try:
            book = Book(**normalize(raw))
        except (ValidationError, KeyError, TypeError) as e:
            errors.append({
                "product_url": raw.get("product_url"),
                "reason": str(e),
                "raw": raw,
            })
            continue
        good[book.product_url] = book.model_dump()
    return list(good.values()), errors


def write_json(path: Path, data) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")



def main() -> None:
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()

    found, pages = discover_books()
    unique = dedupe(found)

    if "--with-fake" in sys.argv:  # failure test: one made-up URL
        unique.append({
            "product_url": "https://books.toscrape.com/catalogue/this-book-does-not-exist_999/index.html",
            "source_page": START_URL,
        })

    print(f"catalogue_pages={pages}, discovered={len(found)}, unique_urls={len(unique)}")

    raws = extract_details(unique)
    print(f"detail_pages={len(raws)}")

    books, errors = validate_records(raws)
    write_json(OUTPUT_DIR / "books.json", books)
    write_json(OUTPUT_DIR / "errors.json", errors)
    print(f"valid={len(books)}, invalid={len(errors)}")

    report = {
        "started_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duration_seconds": round(time.monotonic() - t0, 2),
        "pages_fetched": STATS["pages_fetched"],
        "cache_hits": STATS["cache_hits"],
        "valid_records": len(books),
        "invalid_records": len(errors),
        "failed_pages": STATS["failed_pages"],
        "failed_urls": STATS["failed_urls"],
    }
    write_json(OUTPUT_DIR / "run-report.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
    

