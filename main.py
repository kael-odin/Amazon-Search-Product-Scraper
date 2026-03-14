#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CafeScraper Worker: Amazon Search & Product Scraper.
Entry point: main.py in project root. Uses CafeSDK for params, logging, and result push.
"""
import asyncio
import os
import sys

# Ensure project root is on path so src.scraper_core can be imported
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sdk import CafeSDK

# Import after path fix
from src.scraper_core import run_scraper

# Table columns for CafeScraper result table (keys must match push_data dict keys)
RESULT_TABLE_HEADERS = [
    {"label": "关键词", "key": "keyword", "format": "text"},
    {"label": "站点", "key": "country", "format": "text"},
    {"label": "页码", "key": "pageIndex", "format": "integer"},
    {"label": "ASIN", "key": "asin", "format": "text"},
    {"label": "标题", "key": "title", "format": "text"},
    {"label": "商品链接", "key": "productUrl", "format": "text"},
    {"label": "价格文案", "key": "priceText", "format": "text"},
    {"label": "价格", "key": "price", "format": "text"},
    {"label": "原价文案", "key": "originalPriceText", "format": "text"},
    {"label": "评分", "key": "rating", "format": "text"},
    {"label": "评论数", "key": "reviewsCount", "format": "integer"},
    {"label": "Prime", "key": "isPrime", "format": "boolean"},
    {"label": "品牌", "key": "brand", "format": "text"},
    {"label": "标签", "key": "badges", "format": "array"},
    {"label": "赞助", "key": "isSponsored", "format": "boolean"},
    {"label": "图片链接", "key": "imageUrl", "format": "text"},
    {"label": "货币", "key": "currency", "format": "text"},
    {"label": "分类路径", "key": "categoryPath", "format": "array"},
    {"label": "特性要点", "key": "featureBullets", "format": "array"},
]


class _CafeLogAdapter:
    """Adapt CafeSDK.Log to scraper_core interface (debug/info/warning/exception)."""

    def debug(self, msg: str, exc_info: bool = False) -> None:
        CafeSDK.Log.debug(msg)

    def info(self, msg: str) -> None:
        CafeSDK.Log.info(msg)

    def warning(self, msg: str) -> None:
        CafeSDK.Log.warn(msg)

    def exception(self, msg: str) -> None:
        CafeSDK.Log.error(msg)


HEADER_KEYS = [h["key"] for h in RESULT_TABLE_HEADERS]


def _serialize_row(row: dict) -> dict:
    """Build row with only header keys, JSON-serializable for CafeSDK.Result.push_data."""
    out = {}
    for k in HEADER_KEYS:
        v = row.get(k)
        if v is None:
            out[k] = None
        elif isinstance(v, (list, dict, str, int, float, bool)):
            out[k] = v
        else:
            out[k] = str(v)
    return out


async def run():
    try:
        # 1. Get params
        input_json_dict = CafeSDK.Parameter.get_input_json_dict()
        CafeSDK.Log.debug(f"params: {input_json_dict}")

        # 2. Proxy configuration (CafeScraper platform)
        proxy_domain = "proxy-inner.cafescraper.com:6000"
        try:
            proxy_auth = os.environ.get("PROXY_AUTH")
            if proxy_auth:
                CafeSDK.Log.info("Proxy authentication configured")
            else:
                CafeSDK.Log.info("No PROXY_AUTH; running without proxy")
        except Exception as e:
            CafeSDK.Log.error(f"Failed to retrieve proxy authentication: {e}")
            proxy_auth = None

        proxy_url = f"socks5://{proxy_auth}@{proxy_domain}" if proxy_auth else None
        if proxy_url:
            CafeSDK.Log.info("Using proxy for browser context")

        # 3. Set result table header first (required by CafeScraper)
        CafeSDK.Result.set_table_header(RESULT_TABLE_HEADERS)

        # 4. Push callback: each row must match RESULT_TABLE_HEADERS keys
        def push_data(row: dict) -> None:
            obj = _serialize_row(row)
            CafeSDK.Result.push_data(obj)

        log = _CafeLogAdapter()
        await run_scraper(
            input_json_dict,
            launch_browser_kwargs={"headless": True, "args": ["--disable-gpu"]},
            proxy=proxy_url,
            log=log,
            push_data=push_data,
        )

        CafeSDK.Log.info("Script execution completed")

    except Exception as e:
        CafeSDK.Log.error(f"Script execution error: {e}")
        error_result = {
            "error": str(e),
            "error_code": "500",
            "status": "failed",
        }
        CafeSDK.Result.push_data(error_result)
        raise


if __name__ == "__main__":
    asyncio.run(run())
