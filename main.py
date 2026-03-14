#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CafeScraper worker: Amazon search & product scraper. Entry: main.py. Uses CafeSDK for params, logging, result push."""
import asyncio
import os

from sdk import CafeSDK
from scraper import run_scraper

RESULT_TABLE_HEADERS = [
    {"label": "Keyword", "key": "keyword", "format": "text"},
    {"label": "Country", "key": "country", "format": "text"},
    {"label": "Page", "key": "pageIndex", "format": "integer"},
    {"label": "ASIN", "key": "asin", "format": "text"},
    {"label": "Title", "key": "title", "format": "text"},
    {"label": "Product URL", "key": "productUrl", "format": "text"},
    {"label": "Price text", "key": "priceText", "format": "text"},
    {"label": "Price", "key": "price", "format": "text"},
    {"label": "Original price", "key": "originalPriceText", "format": "text"},
    {"label": "Rating", "key": "rating", "format": "text"},
    {"label": "Reviews", "key": "reviewsCount", "format": "integer"},
    {"label": "Prime", "key": "isPrime", "format": "boolean"},
    {"label": "Brand", "key": "brand", "format": "text"},
    {"label": "Badges", "key": "badges", "format": "array"},
    {"label": "Sponsored", "key": "isSponsored", "format": "boolean"},
    {"label": "Image URL", "key": "imageUrl", "format": "text"},
    {"label": "Currency", "key": "currency", "format": "text"},
    {"label": "Category path", "key": "categoryPath", "format": "array"},
    {"label": "Feature bullets", "key": "featureBullets", "format": "array"},
]
HEADER_KEYS = [h["key"] for h in RESULT_TABLE_HEADERS]


class _CafeLogAdapter:
    def debug(self, msg: str, exc_info: bool = False):
        CafeSDK.Log.debug(msg)

    def info(self, msg: str):
        CafeSDK.Log.info(msg)

    def warning(self, msg: str):
        CafeSDK.Log.warn(msg)

    def exception(self, msg: str):
        CafeSDK.Log.error(msg)


def _row_for_push(row: dict) -> dict:
    return {k: row.get(k) if isinstance(row.get(k), (list, dict, str, int, float, bool, type(None))) else str(row.get(k)) for k in HEADER_KEYS}


# Defaults when platform sends minimal input (e.g. only version or country)
DEFAULT_INPUT = {
    "keywords": ["iphone 17 case"],
    "max_items_per_keyword": 50,
    "max_pages": 3,
    "country": "US",
    "min_rating": 0,
    "min_reviews": 0,
    "exclude_sponsored": False,
    "fetch_details": False,
    "max_detail_items": 5,
}


async def run():
    try:
        raw = CafeSDK.Parameter.get_input_json_dict() or {}
        input_json_dict = {**DEFAULT_INPUT, **{k: v for k, v in raw.items() if k != "version"}}
        # CafeScraper stringList sends keywords as [{"string": "a"}, {"string": "b"}]
        kw = input_json_dict.get("keywords") or []
        if kw and isinstance(kw, list) and isinstance(kw[0], dict) and "string" in (kw[0] or {}):
            input_json_dict["keywords"] = [x.get("string", "").strip() for x in kw if x and x.get("string")]
        if not input_json_dict.get("keywords"):
            CafeSDK.Log.info("No keywords in input; using default keywords and settings.")
        CafeSDK.Log.debug(f"params: {input_json_dict}")

        # CafeScraper: connect to remote fingerprint browser via CDP (no local Chromium needed)
        auth = os.environ.get("PROXY_AUTH")
        browser_cdp_url = f"ws://{auth}@chrome-ws-inner.cafescraper.com" if auth else None
        if browser_cdp_url:
            CafeSDK.Log.info("Using CafeScraper fingerprint browser (CDP)")
        else:
            CafeSDK.Log.warn("PROXY_AUTH not set; falling back to local browser (may fail in cloud)")

        CafeSDK.Result.set_table_header(RESULT_TABLE_HEADERS)

        def push_data(row: dict):
            CafeSDK.Result.push_data(_row_for_push(row))

        await run_scraper(
            input_json_dict,
            browser_cdp_url=browser_cdp_url,
            launch_browser_kwargs={"headless": True, "args": ["--disable-gpu"]},
            proxy=None,
            log=_CafeLogAdapter(),
            push_data=push_data,
        )
        CafeSDK.Log.info("Run completed")
    except Exception as e:
        CafeSDK.Log.error(f"Run error: {e}")
        CafeSDK.Result.push_data({"error": str(e), "error_code": "500", "status": "failed"})
        raise


if __name__ == "__main__":
    asyncio.run(run())
