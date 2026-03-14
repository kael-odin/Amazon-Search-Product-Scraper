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

**Playwright / browser:** On CafeScraper the script uses the platform’s **remote fingerprint browser** via CDP (`connect_over_cdp` to `ws://{PROXY_AUTH}@chrome-ws-inner.cafescraper.com`), so no local Chromium install is needed. See [Why Use Playwright](https://docs.cafescraper.com/why-use-playwright). When `PROXY_AUTH` is not set (e.g. local run), it falls back to launching a local browser (requires Chromium/Chrome in PATH or `playwright install chromium`).

**Input / input_schema:** CafeScraper may not use our `input_schema.json` format (their UI often shows only Execution Node, Version, Timeout, Memory). We use defaults when the platform sends minimal input (see `DEFAULT_INPUT` in `main.py`). To pass keywords or country, use whatever input form CafeScraper provides, or ask them for the correct schema format.

## Anti-bot

Amazon uses strong anti-bot measures. This worker uses a realistic browser profile and basic CAPTCHA detection. For production, use the platform’s proxy and keep concurrency low.


