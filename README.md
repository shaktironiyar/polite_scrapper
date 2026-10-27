# The polite scraper

Scrapes the first 3 catalogue pages of Books to Scrape (60 books) into validated JSON.
FlyRank Internship, Backend Track, W5 A9.

## Target classification
<your Stage 0 section, unchanged, including the robots.txt result and the "I will not reuse..." sentence>

## Lane and install
- Python 3.10+ with [uv](https://docs.astral.sh/uv/)
- Libraries: Requests, Beautiful Soup, Pydantic

```bash
git clone <your repo url>
cd <repo>
uv sync
```

## Run
```bash
uv run python src/main.py
```
Produces `output/books.json`, `output/errors.json`, and `output/run-report.json`.
A first run makes about 63 real requests and takes roughly a minute. Reruns read from `cache/`.

## Record schema
| Field | Type | Notes |
|---|---|---|
| title | string | required |
| product_url | string | https URL, record identity |
| price_text | string | raw, e.g. "£51.77" |
| price_gbp | float | parsed from price_text, >= 0 |
| availability_text | string | raw |
| rating_text | string | e.g. "Three" |
| description | string or null | null if the page has none |
| source_page | string | catalogue page the book was found on |
| fetched_at | string | UTC ISO-8601, when the page was downloaded |

Invalid records go to `errors.json` with the reason.

## Politeness rules
- Honest user-agent: `FlyRankInternshipA9/1.0 (+<repo url>)`
- Timeout: 10 s per request
- Delay: at least 0.5 s between real requests
- Status check: only 200 is parsed
- Cache: pages are saved to `cache/` and reused
- Retry: once on a timeout or 5xx, never on 404 or 403

## Sample run report
```json
<paste your real run-report.json>
```

## Why no browser
<one sentence: the data is already in the HTML the server sends, so a browser would only add cost.>

## Ethics note
<write this in your own words>

## Limitation
<one honest limitation>