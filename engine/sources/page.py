"""Generic sale-page scraper for sites that aren't Shopify (Rack, Gilt, lululemon, BR, RL...).

Strategy, in order:
  1. Render the page in a real Chromium (Playwright) so JS-built grids load.
  2. Read schema.org JSON-LD (Product / ItemList) — many retailers embed it for Google.
  3. Fall back to CSS selectors from config.toml (card/title/brand_sel/price/link).
Selectors drift when sites redesign; when a source returns 0 items, open the page,
inspect a product tile, and update its selectors in config.toml.
"""
from __future__ import annotations

import json
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Listing, parse_money


def render(url: str, scrolls: int = 6, headless: bool = True) -> str:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
            viewport={"width": 1400, "height": 1000},
        )
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        for _ in range(scrolls):                    # trigger lazy-loaded tiles
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(900)
        html = page.content()
        browser.close()
    return html


def fetch(src: dict, html_override: str | None = None) -> list[Listing]:
    out: list[Listing] = []
    for url in src.get("urls", []):
        html = html_override if html_override is not None else render(url, headless=src.get("headless", True))
        items = parse(html, url, src)
        out.extend(items)
    return out


def parse(html: str, base_url: str, src: dict) -> list[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    items = _from_jsonld(soup, base_url, src)
    if not items and src.get("card"):
        items = _from_selectors(soup, base_url, src)
    # de-dupe by url
    seen, uniq = set(), []
    for it in items:
        if it.url not in seen:
            seen.add(it.url)
            uniq.append(it)
    return uniq


# ── JSON-LD ──────────────────────────────────────────────────
def _walk(node):
    if isinstance(node, list):
        for n in node:
            yield from _walk(n)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "itemListElement", "item", "hasVariant"):
            if key in node:
                yield from _walk(node[key])


def _from_jsonld(soup, base_url, src) -> list[Listing]:
    out = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        for node in _walk(data):
            t = node.get("@type")
            if t != "Product" and not (isinstance(t, list) and "Product" in t):
                continue
            offers = node.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price = offers.get("lowPrice") or offers.get("price")
            if price is None:
                continue
            original = offers.get("highPrice")
            spec = offers.get("priceSpecification")
            if isinstance(spec, list):
                for s in spec:
                    if "ListPrice" in str(s.get("priceType", "")) or "StrikethroughPrice" in str(s.get("priceType", "")):
                        original = s.get("price")
            brand = node.get("brand") or ""
            if isinstance(brand, dict):
                brand = brand.get("name", "")
            img = node.get("image") or ""
            if isinstance(img, list):
                img = img[0] if img else ""
            if isinstance(img, dict):
                img = img.get("url", "")
            p, o = float(price), (float(original) if original else None)
            out.append(Listing(
                source=src["name"], title=node.get("name", ""),
                brand=src.get("brand") or brand, price=p,
                original=o if o and o > p else None,
                url=urljoin(base_url, node.get("url") or offers.get("url") or ""),
                image=str(img), description=node.get("description", "") or "",
            ))
    return out


# ── CSS selectors ────────────────────────────────────────────
def _from_selectors(soup, base_url, src) -> list[Listing]:
    out = []
    for card in soup.select(src["card"]):
        title_el = card.select_one(src.get("title", "h3"))
        link_el = card.select_one(src.get("link", "a"))
        if not title_el or not link_el or not link_el.get("href"):
            continue
        brand_el = card.select_one(src["brand_sel"]) if src.get("brand_sel") else None
        price_text = " ".join(e.get_text(" ", strip=True) for e in card.select(src.get("price", "[class*=price]")))
        prices = parse_money(price_text or card.get_text(" ", strip=True))
        if not prices:
            continue
        img_el = card.select_one("img")
        price = min(prices)
        original = max(prices) if len(prices) > 1 and max(prices) > price else None
        out.append(Listing(
            source=src["name"], title=title_el.get_text(" ", strip=True),
            brand=src.get("brand") or (brand_el.get_text(" ", strip=True) if brand_el else ""),
            price=price, original=original,
            url=urljoin(base_url, link_el["href"]),
            image=(img_el.get("src") or img_el.get("data-src") or "") if img_el else "",
        ))
    return out
