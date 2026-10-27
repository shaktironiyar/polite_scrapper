from pathlib import Path
import requests

BASE = "https://books.toscrape.com/"
CACHE_DIR = Path("cache")
USER_AGENT = "FlyRankInternshipA9/1.0 (+https://github.com/shaktironiyar/polite_scrapper)"
TIMEOUT = 10  # seconds


def fetch(url: str, cache_name: str) -> str | None:
    """Return HTML from cache if present, else from the site. None on failure."""
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / cache_name

    if path.exists():
        html = path.read_text(encoding="utf-8")
        print(f"CACHE HIT  {cache_name}  {len(html)} chars")
        return html

    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    except requests.RequestException as e:
        print(f"FAILED     {url}  {e}")
        return None

    if resp.status_code != 200:
        print(f"FAILED     {url}  status={resp.status_code}")
        return None

    resp.encoding = "utf-8"  # the site is UTF-8; avoids a garbled "£"
    path.write_text(resp.text, encoding="utf-8")
    print(f"FETCH      {cache_name}  {len(resp.text)} chars")
    return resp.text


if __name__ == "__main__":
    fetch(BASE + "catalogue/page-1.html", "catalogue-page-1.html")

    

