# Amazon Search & Product Scraper

CafeScraper worker that searches Amazon by keywords and returns product list data (ASIN, title, price, rating, etc.) for analysis or export.

## Required files (project root)

| File | Purpose |
|------|--------|
| `main.py` | Entry point |
| `scraper.py` | Scraping logic |
| `requirements.txt` | Python dependencies |
| `input_schema.json` | Input form config |
| `README.md` | This file |
| `sdk.py`, `sdk_pb2.py`, `sdk_pb2_grpc.py` | CafeScraper SDK |

## Input

- **keywords** (required): list of search terms, e.g. `["iphone case", "usb c hub"]`
- **max_items_per_keyword** (default 50): max products per keyword
- **max_pages** (default 3): max result pages per keyword (1–20)
- **country** (default US): marketplace — US, UK, DE, FR, JP
- **min_rating** / **min_reviews**: optional filters; 0 = no filter
- **exclude_sponsored** (default false): drop sponsored results
- **fetch_details** (default false): open detail pages for first N items to get category path and feature bullets
- **max_detail_items** (default 5): N when fetch_details is true

## Output

Each row includes: keyword, country, pageIndex, asin, title, productUrl, priceText, price, originalPriceText, rating, reviewsCount, isPrime, brand, badges, isSponsored, imageUrl, currency; optionally categoryPath and featureBullets when fetch_details is enabled.

## Run

The platform runs `python main.py` and supplies input via the SDK. Proxy is optional via `PROXY_AUTH` (e.g. `socks5://{PROXY_AUTH}@proxy-inner.cafescraper.com:6000`).

**Playwright browsers:** The script tries to run `playwright install chromium` once at start. If the run environment has no network or no write access to the cache dir, the platform must run `playwright install chromium` (or add a build step that does) before starting the task.

**Minimal input:** If the platform only sends e.g. `{"version": "v1.0.1"}` or only a country, the worker uses default keywords and settings (see `DEFAULT_INPUT` in `main.py`). Full input can include: `keywords`, `country`, `max_pages`, `max_items_per_keyword`, `min_rating`, `min_reviews`, `exclude_sponsored`, `fetch_details`, `max_detail_items`.

## Anti-bot

Amazon uses strong anti-bot measures. This worker uses a realistic browser profile and basic CAPTCHA detection. For production, use the platform’s proxy and keep concurrency low.
