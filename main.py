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
        if not raw.get("keywords"):
            CafeSDK.Log.info("No keywords in input; using default keywords and settings.")
        CafeSDK.Log.debug(f"params: {input_json_dict}")

        proxy_domain = "proxy-inner.cafescraper.com:6000"
        proxy_auth = os.environ.get("PROXY_AUTH")
        proxy_url = f"socks5://{proxy_auth}@{proxy_domain}" if proxy_auth else None
        if proxy_url:
            CafeSDK.Log.info("Using proxy for browser")

        CafeSDK.Result.set_table_header(RESULT_TABLE_HEADERS)

        def push_data(row: dict):
            CafeSDK.Result.push_data(_row_for_push(row))

        await run_scraper(
            input_json_dict,
            launch_browser_kwargs={"headless": True, "args": ["--disable-gpu"]},
            proxy=proxy_url,
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
