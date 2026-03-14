"""
Amazon search & product scraping core logic.
Platform-agnostic: accepts log adapter and push_data callback for Apify or CafeScraper.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from playwright.async_api import BrowserContext, Locator, TimeoutError as PlaywrightTimeoutError, async_playwright


@dataclass
class AmazonSearchInput:
    """Normalized scraper input."""

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
    """Normalize and validate input, filling default values."""
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
    mapping = {
        "US": "www.amazon.com",
        "UK": "www.amazon.co.uk",
        "DE": "www.amazon.de",
        "FR": "www.amazon.fr",
        "JP": "www.amazon.co.jp",
    }
    return mapping.get(country.upper(), "www.amazon.com")


async def _parse_single_card(
    card: Locator,
    base_url: str,
    min_rating: Optional[float],
    min_reviews: Optional[int],
    exclude_sponsored: bool,
    log: Any,
) -> Optional[Dict[str, Any]]:
    """Parse a single product card into a structured item."""
    try:
        asin = await card.get_attribute("data-asin")
        if not asin:
            return None

        title_el = card.locator("a.a-link-normal.s-link-style.a-text-normal")
        if await title_el.count() == 0:
            title_el = card.locator("h2 a.a-link-normal")

        if await title_el.count() == 0:
            log.debug("Skipping card: no title link found")
            return None

        title = (await title_el.first.text_content() or "").strip()

        href = await title_el.first.get_attribute("href")
        if not href:
            log.debug("Skipping card: title link has no href")
            return None
        if href.startswith("/"):
            product_url = f"{base_url}{href.split('?')[0]}"
        else:
            product_url = href.split("?")[0]

        price_locator = card.locator("span.a-price > span.a-offscreen")
        whole = ""
        if await price_locator.count() > 0:
            whole = (await price_locator.first.text_content() or "").strip()
        price = None
        if whole:
            price_text = whole
            numeric_part = "".join(ch if (ch.isdigit() or ch in ",.") else "" for ch in whole)
            if numeric_part:
                if "," in numeric_part and "." not in numeric_part:
                    normalized = numeric_part.replace(".", "").replace(",", ".")
                else:
                    normalized = numeric_part.replace(",", "")
                try:
                    price = float(normalized)
                except ValueError:
                    price = None
        else:
            price_text = ""

        currency = ""
        if price_text:
            stripped = price_text.strip()
            if stripped and stripped[0] in "$€£¥":
                currency = stripped[0]
            else:
                last_token = stripped.split()[-1]
                if len(last_token) in {3, 4}:
                    currency = last_token

        original_price_locator = card.locator("span.a-price.a-text-price span.a-offscreen")
        original_price_text = ""
        if await original_price_locator.count() > 0:
            original_price_text = (await original_price_locator.first.text_content() or "").strip()

        rating_locator = card.locator("span.a-icon-alt")
        rating_text = ""
        if await rating_locator.count() > 0:
            rating_text = (await rating_locator.first.text_content() or "").strip()
        rating_value: Optional[float] = None
        if rating_text:
            try:
                rating_value = float(rating_text.split()[0].replace(",", "."))
            except (ValueError, IndexError):
                rating_value = None

        reviews_locator = card.locator("span.a-size-base.s-underline-text")
        reviews_text = ""
        if await reviews_locator.count() > 0:
            reviews_text = (await reviews_locator.first.text_content() or "").strip()
        reviews_count: Optional[int] = None
        if reviews_text:
            try:
                reviews_count = int(reviews_text.replace(",", "").replace(".", ""))
            except ValueError:
                reviews_count = None

        is_prime = await card.locator('i.a-icon.a-icon-prime, span[data-component-type="s-prime"]').count() > 0

        brand = await card.get_attribute("data-brand") or ""
        brand = (brand or "").strip()
        if not brand:
            brand_locator = card.locator("h5.s-line-clamp-1 span, span.a-size-base-plus.a-color-base")
            if await brand_locator.count() > 0:
                brand = (await brand_locator.first.text_content() or "").strip()

        if brand:
            lowered = brand.lower()
            badge_like_keywords = [
                "amazon's choice",
                "overall pick",
                "best seller",
                "limited time deal",
            ]
            if any(k in lowered for k in badge_like_keywords):
                brand = ""

        badge_locator = card.locator(
            "span.a-badge-text, span.s-label-popover-default, span.s-label-popover-default span.a-badge-label-inner"
        )
        badges: List[str] = []
        if await badge_locator.count() > 0:
            for i in range(await badge_locator.count()):
                text = await badge_locator.nth(i).text_content()
                if text:
                    cleaned = text.strip()
                    if cleaned and cleaned not in badges:
                        badges.append(cleaned)

        sponsored_locator = card.locator("span.s-sponsored-label-text, span.a-color-secondary")
        is_sponsored = False
        if await sponsored_locator.count() > 0:
            text = (await sponsored_locator.first.text_content() or "").strip().lower()
            if "sponsored" in text:
                is_sponsored = True

        if min_rating is not None and rating_value is not None and rating_value < min_rating:
            return None
        if min_reviews is not None and reviews_count is not None and reviews_count < min_reviews:
            return None
        if exclude_sponsored and is_sponsored:
            return None

        image_locator = card.locator("img.s-image")
        image_url = ""
        if await image_locator.count() > 0:
            image_url = (await image_locator.first.get_attribute("src")) or ""

        return {
            "asin": asin,
            "title": title,
            "productUrl": product_url,
            "priceText": price_text,
            "price": price,
            "originalPriceText": original_price_text,
            "rating": rating_value,
            "reviewsCount": reviews_count,
            "isPrime": is_prime,
            "brand": brand,
            "badges": badges,
            "isSponsored": is_sponsored,
            "imageUrl": image_url,
            "currency": currency,
        }
    except Exception:
        log.debug("Failed to parse one product card", exc_info=True)
        return None


async def _extract_product_cards(
    card_locators: List[Locator],
    base_url: str,
    min_rating: Optional[float],
    min_reviews: Optional[int],
    exclude_sponsored: bool,
    log: Any,
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for card in card_locators:
        try:
            item = await asyncio.wait_for(
                _parse_single_card(
                    card=card,
                    base_url=base_url,
                    min_rating=min_rating,
                    min_reviews=min_reviews,
                    exclude_sponsored=exclude_sponsored,
                    log=log,
                ),
                timeout=5,
            )
        except asyncio.TimeoutError:
            log.warning("Timed out while parsing a single product card, skipping it.")
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
    domain = country_to_domain(country)
    base_url = f"https://{domain}"
    from urllib.parse import quote_plus

    search_url = f"{base_url}/s?k={quote_plus(keyword)}"
    log.info(f'Start scraping keyword="{keyword}" from {search_url}')

    total_collected = 0
    page_index = 1

    while total_collected < max_items and page_index <= max_pages:
        page = await context.new_page()
        try:
            max_nav_retries = 3
            for attempt in range(1, max_nav_retries + 1):
                try:
                    await page.goto(search_url, wait_until="domcontentloaded", timeout=20_000)
                    await page.wait_for_timeout(2_000)
                    break
                except PlaywrightTimeoutError:
                    log.warning(
                        f'Navigation timeout for "{keyword}" page={page_index}, '
                        f"attempt {attempt}/{max_nav_retries}"
                    )
                    if attempt == max_nav_retries:
                        raise
                    sleep_ms = int(random.uniform(1_000, 3_000) * attempt)
                    await page.wait_for_timeout(sleep_ms)

            html_lower = (await page.content()).lower()
            captcha_markers = [
                "api-services-support@amazon.com",
                "to discuss automated access to amazon data",
                "/captcha/",
                "enter the characters you see below",
            ]
            if any(marker in html_lower for marker in captcha_markers):
                log.warning(
                    "This page looks like a bot-protection / CAPTCHA page. "
                    "No products will be parsed for this keyword."
                )
                break

            cards = await page.locator('div.s-main-slot div[data-component-type="s-search-result"]').all()
            log.info(f"Found {len(cards)} product cards on page {page_index}")

            if not cards:
                break

            remaining = max_items - total_collected
            if remaining <= 0:
                break
            if len(cards) > remaining:
                cards = cards[:remaining]

            items = await _extract_product_cards(
                cards,
                base_url=base_url,
                min_rating=min_rating,
                min_reviews=min_reviews,
                exclude_sponsored=exclude_sponsored,
                log=log,
            )
            log.info(f"Parsed {len(items)} products from cards on page {page_index}")

            if not items:
                log.info("No valid products parsed from cards, stopping for this keyword.")
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
                        detail_page = await context.new_page()
                        await detail_page.goto(detail_url, wait_until="domcontentloaded", timeout=20_000)
                        breadcrumb_locator = detail_page.locator(
                            '#wayfinding-breadcrumbs_feature_div li a, nav[aria-label="Breadcrumb"] a'
                        )
                        category_path: List[str] = []
                        if await breadcrumb_locator.count() > 0:
                            for i in range(await breadcrumb_locator.count()):
                                text = await breadcrumb_locator.nth(i).text_content()
                                if text:
                                    cleaned = text.strip()
                                    if cleaned:
                                        category_path.append(cleaned)
                        if category_path:
                            item["categoryPath"] = category_path

                        bullets_locator = detail_page.locator("#feature-bullets ul li span")
                        feature_bullets: List[str] = []
                        if await bullets_locator.count() > 0:
                            for i in range(await bullets_locator.count()):
                                text = await bullets_locator.nth(i).text_content()
                                if text:
                                    cleaned = text.strip()
                                    if cleaned:
                                        feature_bullets.append(cleaned)
                        if feature_bullets:
                            item["featureBullets"] = feature_bullets
                        detail_count += 1
                    except Exception:
                        log.debug("Failed to enrich product with detail page", exc_info=True)
                    finally:
                        try:
                            await detail_page.close()
                        except Exception:
                            pass

            for item in items:
                row = {
                    "keyword": keyword,
                    "country": country,
                    "pageIndex": page_index,
                    **item,
                }
                out = push_data(row)
                if asyncio.iscoroutine(out):
                    await out

            total_collected += len(items)
            log.info(
                f"Pushed {len(items)} items for page {page_index}, "
                f'collected {total_collected}/{max_items} items for "{keyword}" so far'
            )

            if total_collected >= max_items:
                break

            next_btn = page.locator("a.s-pagination-next:not(.s-pagination-disabled)")
            if await next_btn.count() == 0:
                log.info("No more pages, stopping pagination.")
                break

            next_href = await next_btn.first.get_attribute("href")
            if not next_href:
                break

            if next_href.startswith("/"):
                search_url = f"{base_url}{next_href}"
            else:
                search_url = next_href

            page_index += 1
        except Exception:
            log.exception(f'Failed scraping keyword="{keyword}" page={page_index}')
            break
        finally:
            await page.close()


async def run_scraper(
    input_dict: Dict[str, Any],
    *,
    launch_browser_kwargs: Optional[Dict[str, Any]] = None,
    proxy: Optional[str] = None,
    log: Any = None,
    push_data: Optional[Callable[[Dict[str, Any]], Any]] = None,
) -> None:
    """
    Run the Amazon search scraper.

    - input_dict: raw input (keywords, max_pages, country, etc.)
    - launch_browser_kwargs: passed to playwright.chromium.launch(**kwargs)
    - proxy: optional proxy URL (e.g. socks5://user:pass@host:port)
    - log: object with .debug, .info, .warning, .exception(str) methods
    - push_data: callable that accepts one dict per product row
    """
    if log is None:
        import logging
        _log = logging.getLogger("scraper_core")
        class _LogAdapter:
            def debug(self, msg, exc_info=False): _log.debug(msg, exc_info=exc_info)
            def info(self, msg): _log.info(msg)
            def warning(self, msg): _log.warning(msg)
            def exception(self, msg): _log.exception(msg)
        log = _LogAdapter()
    if push_data is None:
        push_data = lambda x: None

    parsed = normalize_input(input_dict)
    log.info(
        f"Input parsed: keywords={parsed.keywords}, "
        f"max_items_per_keyword={parsed.max_items_per_keyword}, "
        f"max_pages={parsed.max_pages}, country={parsed.country}, "
        f"min_rating={parsed.min_rating}, min_reviews={parsed.min_reviews}, "
        f"exclude_sponsored={parsed.exclude_sponsored}, "
        f"fetch_details={parsed.fetch_details}, max_detail_items={parsed.max_detail_items}"
    )

    launch_kwargs = dict(launch_browser_kwargs or {})
    if "headless" not in launch_kwargs:
        launch_kwargs["headless"] = True
    if "args" not in launch_kwargs:
        launch_kwargs["args"] = ["--disable-gpu"]

    locale_by_country = {"US": "en-US", "UK": "en-GB", "DE": "de-DE", "FR": "fr-FR", "JP": "ja-JP"}
    locale = locale_by_country.get(parsed.country, "en-US")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**launch_kwargs)
        context_options: Dict[str, Any] = {
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
            ),
            "locale": locale,
            "viewport": {"width": 1366, "height": 768},
        }
        if proxy:
            # Playwright: server can be "socks5://host:port"; auth in URL is supported
            context_options["proxy"] = {"server": proxy}
        context = await browser.new_context(**context_options)

        try:
            for keyword in parsed.keywords:
                await _scrape_keyword(
                    context=context,
                    keyword=keyword,
                    country=parsed.country,
                    max_items=parsed.max_items_per_keyword,
                    max_pages=parsed.max_pages,
                    min_rating=parsed.min_rating,
                    min_reviews=parsed.min_reviews,
                    exclude_sponsored=parsed.exclude_sponsored,
                    fetch_details=parsed.fetch_details,
                    max_detail_items=parsed.max_detail_items,
                    log=log,
                    push_data=push_data,
                )
        finally:
            await context.close()
            await browser.close()
