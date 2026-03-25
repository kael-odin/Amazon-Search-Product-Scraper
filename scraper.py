"""
Amazon search & product scraping logic for CafeScraper worker.
Accepts log adapter and push_data callback.
"""

from __future__ import annotations

import asyncio
import os
import random
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from playwright.async_api import BrowserContext, Locator, TimeoutError as PlaywrightTimeoutError, async_playwright

# Stealth mode to avoid bot detection
try:
    from playwright_stealth import stealth_async
    HAS_STEALTH = True
except ImportError:
    HAS_STEALTH = False


@dataclass
class AmazonSearchInput:
    keywords: List[str]
    max_items_per_keyword: int
    max_pages: int
    country: str
    min_rating: Optional[float]
    min_reviews: Optional[int]
    exclude_sponsored: bool
    fetch_details: bool
    max_detail_items: int


def normalize_input(raw: Dict[str, Any]) -> AmazonSearchInput:
    keywords = raw.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [keywords]
    keywords = [k.strip() for k in keywords if isinstance(k, str) and k.strip()]
    if not keywords:
        keywords = ["iphone 17 case"]

    max_items_per_keyword = int(raw.get("max_items_per_keyword", 50) or 50)
    if max_items_per_keyword <= 0:
        max_items_per_keyword = 50
    max_pages = int(raw.get("max_pages", 3) or 3)
    if max_pages <= 0:
        max_pages = 1
    if max_pages > 20:
        max_pages = 20
    country = (raw.get("country") or "US").upper()
    if country not in {"US", "UK", "DE", "FR", "JP"}:
        country = "US"
    min_rating_val: Optional[float] = None
    if raw.get("min_rating") is not None:
        try:
            min_rating_val = float(raw["min_rating"])
        except (TypeError, ValueError):
            min_rating_val = None
    min_reviews_val: Optional[int] = None
    if raw.get("min_reviews") is not None:
        try:
            mr = int(raw["min_reviews"])
            min_reviews_val = mr if mr > 0 else None
        except (TypeError, ValueError):
            min_reviews_val = None
    exclude_sponsored = bool(raw.get("exclude_sponsored", False))
    fetch_details = bool(raw.get("fetch_details", False))
    max_detail_items = int(raw.get("max_detail_items", 5) or 5)
    if max_detail_items <= 0:
        max_detail_items = 1
    if max_detail_items > 50:
        max_detail_items = 50
    return AmazonSearchInput(
        keywords=keywords,
        max_items_per_keyword=max_items_per_keyword,
        max_pages=max_pages,
        country=country,
        min_rating=min_rating_val,
        min_reviews=min_reviews_val,
        exclude_sponsored=exclude_sponsored,
        fetch_details=fetch_details,
        max_detail_items=max_detail_items,
    )


def country_to_domain(country: str) -> str:
    return {"US": "www.amazon.com", "UK": "www.amazon.co.uk", "DE": "www.amazon.de", "FR": "www.amazon.fr", "JP": "www.amazon.co.jp"}.get(country.upper(), "www.amazon.com")


async def _parse_single_card(
    card: Locator,
    base_url: str,
    min_rating: Optional[float],
    min_reviews: Optional[int],
    exclude_sponsored: bool,
    log: Any,
) -> Optional[Dict[str, Any]]:
    try:
        asin = await card.get_attribute("data-asin")
        if not asin:
            return None
        title_el = card.locator("a.a-link-normal.s-link-style.a-text-normal")
        if await title_el.count() == 0:
            title_el = card.locator("h2 a.a-link-normal")
        if await title_el.count() == 0:
            return None
        title = (await title_el.first.text_content() or "").strip()
        href = await title_el.first.get_attribute("href")
        if not href:
            return None
        product_url = f"{base_url}{href.split('?')[0]}" if href.startswith("/") else href.split("?")[0]

        price_locator = card.locator("span.a-price > span.a-offscreen")
        whole = (await price_locator.first.text_content() or "").strip() if await price_locator.count() > 0 else ""
        price_text = whole
        price = None
        if whole:
            numeric_part = "".join(ch if (ch.isdigit() or ch in ",.") else "" for ch in whole)
            if numeric_part:
                normalized = numeric_part.replace(".", "").replace(",", ".") if "," in numeric_part and "." not in numeric_part else numeric_part.replace(",", "")
                try:
                    price = float(normalized)
                except ValueError:
                    pass
        currency = ""
        if price_text and price_text.strip():
            s = price_text.strip()
            currency = s[0] if s[0] in "$€£¥" else (s.split()[-1] if len(s.split()[-1]) in {3, 4} else "")

        original_price_locator = card.locator("span.a-price.a-text-price span.a-offscreen")
        original_price_text = (await original_price_locator.first.text_content() or "").strip() if await original_price_locator.count() > 0 else ""

        rating_locator = card.locator("span.a-icon-alt")
        rating_text = (await rating_locator.first.text_content() or "").strip() if await rating_locator.count() > 0 else ""
        rating_value = None
        if rating_text:
            try:
                rating_value = float(rating_text.split()[0].replace(",", "."))
            except (ValueError, IndexError):
                pass
        # 尝试多种选择器获取评论数 (Amazon页面结构经常变化)
        reviews_count = None
        reviews_selectors = [
            "span.a-size-base.s-underline-text",  # 旧版选择器
            "a[href*='customerReviews'] span.a-size-base",  # 评论链接中的数字
            "span[aria-label*='stars'] + span.a-size-base",  # 星级后的数字
            "div.a-row.a-size-small span:last-child",  # 评分行最后一个数字
            "span.a-size-base.a-color-secondary",  # 次要颜色数字
        ]
        for selector in reviews_selectors:
            reviews_locator = card.locator(selector)
            if await reviews_locator.count() > 0:
                reviews_text = (await reviews_locator.first.text_content() or "").strip()
                # 过滤掉评分数字 (通常带小数点，评论数是整数)
                if reviews_text and "." not in reviews_text:
                    try:
                        # 移除千位分隔符
                        clean_text = reviews_text.replace(",", "").replace(".", "").replace("(", "").replace(")", "")
                        reviews_count = int(clean_text)
                        if reviews_count >= 0:  # 有效评论数
                            break
                    except ValueError:
                        continue
        # 如果以上选择器都失败，尝试从 aria-label 提取
        if reviews_count is None:
            rating_container = card.locator("i.a-icon-star-small, span.a-icon-alt")
            if await rating_container.count() > 0:
                aria_label = await rating_container.first.get_attribute("aria-label") or ""
                # aria-label 格式通常是 "4.5 out of 5 stars. 1,234 ratings"
                if "rating" in aria_label.lower():
                    parts = aria_label.split()
                    for i, part in enumerate(parts):
                        if part.lower() in ["ratings", "rating", "reviews", "review"]:
                            if i > 0:
                                try:
                                    reviews_count = int(parts[i-1].replace(",", "").replace(".", ""))
                                    break
                                except (ValueError, IndexError):
                                    pass
        is_prime = await card.locator('i.a-icon.a-icon-prime, span[data-component-type="s-prime"]').count() > 0
        brand = (await card.get_attribute("data-brand") or "").strip()
        if not brand:
            brand_locator = card.locator("h5.s-line-clamp-1 span, span.a-size-base-plus.a-color-base")
            if await brand_locator.count() > 0:
                brand = (await brand_locator.first.text_content() or "").strip()
        if brand and any(k in brand.lower() for k in ("amazon's choice", "overall pick", "best seller", "limited time deal")):
            brand = ""
        badge_locator = card.locator("span.a-badge-text, span.s-label-popover-default, span.s-label-popover-default span.a-badge-label-inner")
        badges = []
        if await badge_locator.count() > 0:
            for i in range(await badge_locator.count()):
                text = await badge_locator.nth(i).text_content()
                if text:
                    cleaned = text.strip()
                    if cleaned and cleaned not in badges:
                        badges.append(cleaned)
        sponsored_locator = card.locator("span.s-sponsored-label-text, span.a-color-secondary")
        is_sponsored = "sponsored" in ((await sponsored_locator.first.text_content() or "").strip().lower()) if await sponsored_locator.count() > 0 else False
        if min_rating is not None and rating_value is not None and rating_value < min_rating:
            return None
        if min_reviews is not None and reviews_count is not None and reviews_count < min_reviews:
            return None
        if exclude_sponsored and is_sponsored:
            return None
        image_locator = card.locator("img.s-image")
        image_url = (await image_locator.first.get_attribute("src")) or "" if await image_locator.count() > 0 else ""
        return {
            "asin": asin, "title": title, "productUrl": product_url, "priceText": price_text, "price": price,
            "originalPriceText": original_price_text, "rating": rating_value, "reviewsCount": reviews_count,
            "isPrime": is_prime, "brand": brand, "badges": badges, "isSponsored": is_sponsored, "imageUrl": image_url, "currency": currency,
        }
    except Exception:
        return None


async def _extract_product_cards(
    card_locators: List[Locator],
    base_url: str,
    min_rating: Optional[float],
    min_reviews: Optional[int],
    exclude_sponsored: bool,
    log: Any,
) -> List[Dict[str, Any]]:
    items = []
    for card in card_locators:
        try:
            item = await asyncio.wait_for(
                _parse_single_card(card, base_url, min_rating, min_reviews, exclude_sponsored, log), timeout=5
            )
        except asyncio.TimeoutError:
            log.warning("Timed out parsing a product card, skipping.")
            continue
        if item:
            items.append(item)
    return items


async def _scrape_keyword(
    context: BrowserContext,
    keyword: str,
    country: str,
    max_items: int,
    max_pages: int,
    min_rating: Optional[float],
    min_reviews: Optional[int],
    exclude_sponsored: bool,
    fetch_details: bool,
    max_detail_items: int,
    log: Any,
    push_data: Callable[[Dict[str, Any]], Any],
) -> None:
    from urllib.parse import quote_plus
    domain = country_to_domain(country)
    base_url = f"https://{domain}"
    search_url = f"{base_url}/s?k={quote_plus(keyword)}"
    log.info(f'Scraping keyword="{keyword}" from {search_url}')
    total_collected, page_index = 0, 1
    while total_collected < max_items and page_index <= max_pages:
        page = await context.new_page()
        
        # Apply stealth mode to avoid bot detection
        if HAS_STEALTH:
            await stealth_async(page)
            log.info("Stealth mode applied")
        
        try:
            for attempt in range(1, 4):
                try:
                    await page.goto(search_url, wait_until="domcontentloaded", timeout=20_000)
                    await page.wait_for_timeout(2_000)
                    break
                except PlaywrightTimeoutError:
                    if attempt == 3:
                        raise
                    await page.wait_for_timeout(int(random.uniform(1_000, 3_000) * attempt))
            html_content = await page.content()
            html_lower = html_content.lower()
            
            # Check for bot detection
            bot_indicators = ["api-services-support@amazon.com", "to discuss automated access to amazon data", "/captcha/", "enter the characters you see below", "robot check", "something went wrong"]
            detected_indicators = [m for m in bot_indicators if m in html_lower]
            if detected_indicators:
                log.warning(f"Bot/CAPTCHA indicators detected: {detected_indicators}")
                break
            
            # Log page title for debugging
            page_title = await page.title()
            log.info(f"Page title: {page_title}")
            
            # Try multiple selectors for product cards
            cards = await page.locator('div.s-main-slot div[data-component-type="s-search-result"]').all()
            if not cards:
                # Try alternative selector
                cards = await page.locator('div[data-component-type="s-search-result"]').all()
                log.info("Trying alternative selector: div[data-component-type='s-search-result']")
            if not cards:
                # Try another alternative
                cards = await page.locator('.s-result-item[data-asin]').all()
                log.info("Trying alternative selector: .s-result-item[data-asin]")
            
            log.info(f"Found {len(cards)} cards on page {page_index}")
            
            # If still no cards, log some page content for debugging
            if not cards:
                log.warning("No product cards found. Page content preview:")
                log.warning(html_content[:2000] if len(html_content) > 2000 else html_content)
            if not cards:
                break
            remaining = max_items - total_collected
            if remaining <= 0:
                break
            cards = cards[:remaining] if len(cards) > remaining else cards
            items = await _extract_product_cards(cards, base_url, min_rating, min_reviews, exclude_sponsored, log)
            log.info(f"Parsed {len(items)} products on page {page_index}")
            if not items:
                break
            if fetch_details and max_detail_items > 0:
                detail_count = 0
                for item in items:
                    if detail_count >= max_detail_items:
                        break
                    detail_url = item.get("productUrl")
                    if not detail_url:
                        continue
                    try:
                        dp = await context.new_page()
                        await dp.goto(detail_url, wait_until="domcontentloaded", timeout=20_000)
                        bc = dp.locator('#wayfinding-breadcrumbs_feature_div li a, nav[aria-label="Breadcrumb"] a')
                        category_path = [((await bc.nth(i).text_content()) or "").strip() for i in range(await bc.count()) if (await bc.nth(i).text_content() or "").strip()]
                        if category_path:
                            item["categoryPath"] = category_path
                        bl = dp.locator("#feature-bullets ul li span")
                        feature_bullets = [((await bl.nth(i).text_content()) or "").strip() for i in range(await bl.count()) if (await bl.nth(i).text_content() or "").strip()]
                        if feature_bullets:
                            item["featureBullets"] = feature_bullets
                        detail_count += 1
                    except Exception:
                        pass
                    finally:
                        try:
                            await dp.close()
                        except Exception:
                            pass
            for item in items:
                row = {"keyword": keyword, "country": country, "pageIndex": page_index, **item}
                out = push_data(row)
                if asyncio.iscoroutine(out):
                    await out
            total_collected += len(items)
            log.info(f"Collected {total_collected}/{max_items} for \"{keyword}\"")
            if total_collected >= max_items:
                break
            next_btn = page.locator("a.s-pagination-next:not(.s-pagination-disabled)")
            if await next_btn.count() == 0:
                break
            next_href = await next_btn.first.get_attribute("href")
            if not next_href:
                break
            search_url = f"{base_url}{next_href}" if next_href.startswith("/") else next_href
            page_index += 1
        except Exception as e:
            import traceback
            log.exception(f'Failed scraping keyword="{keyword}" page={page_index}: {e}')
            break
        finally:
            await page.close()


async def run_scraper(
    input_dict: Dict[str, Any],
    *,
    browser_cdp_url: Optional[str] = None,
    launch_browser_kwargs: Optional[Dict[str, Any]] = None,
    proxy: Optional[str] = None,
    log: Any = None,
    push_data: Optional[Callable[[Dict[str, Any]], Any]] = None,
) -> None:
    if log is None:
        import logging
        _log = logging.getLogger("scraper")
        class _LogAdapter:
            def debug(self, msg, exc_info=False): _log.debug(msg, exc_info=exc_info)
            def info(self, msg): _log.info(msg)
            def warning(self, msg): _log.warning(msg)
            def exception(self, msg):
                import traceback
                _log.error(f"{msg}\n{traceback.format_exc()}")
        log = _LogAdapter()
    if push_data is None:
        push_data = lambda x: None
    parsed = normalize_input(input_dict)
    log.info(f"Input: keywords={parsed.keywords}, max_pages={parsed.max_pages}, country={parsed.country}")
    locale = {"US": "en-US", "UK": "en-GB", "DE": "de-DE", "FR": "fr-FR", "JP": "ja-JP"}.get(parsed.country, "en-US")
    ctx_opts: Dict[str, Any] = {
        "locale": locale,
        "viewport": {"width": 1366, "height": 768},
    }
    if not browser_cdp_url:
        ctx_opts["user_agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        )
        if proxy:
            ctx_opts["proxy"] = {"server": proxy}

    async with async_playwright() as p:
        is_cdp_browser = False
        if browser_cdp_url:
            log.info("Connecting to CafeScraper fingerprint browser via CDP")
            try:
                browser = await p.chromium.connect_over_cdp(browser_cdp_url)
                is_cdp_browser = True
            except Exception as e:
                log.exception(f"Failed to connect to fingerprint browser: {e}")
                raise
        else:
            launch_kwargs = dict(launch_browser_kwargs or {})
            launch_kwargs.setdefault("headless", True)
            launch_kwargs.setdefault("args", ["--disable-gpu"])
            import shutil
            for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "chrome"):
                path = shutil.which(name)
                if path:
                    launch_kwargs["executable_path"] = path
                    log.info(f"Using system browser: {path}")
                    break
            browser = await p.chromium.launch(**launch_kwargs)
        context = await browser.new_context(**ctx_opts)
        try:
            for keyword in parsed.keywords:
                await _scrape_keyword(
                    context, keyword, parsed.country, parsed.max_items_per_keyword, parsed.max_pages,
                    parsed.min_rating, parsed.min_reviews, parsed.exclude_sponsored,
                    parsed.fetch_details, parsed.max_detail_items, log, push_data,
                )
        finally:
            await context.close()
            # Don't close CDP browser - it's managed by CafeScraper platform
            if not is_cdp_browser:
                await browser.close()
