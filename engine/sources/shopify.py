"""Shopify stores expose /products.json publicly. It's the cleanest data you'll get:
real compare-at prices, variants, and per-size stock. No browser needed."""
from __future__ import annotations

import time

import requests

from ..models import Listing

UA = {"User-Agent": "Mozilla/5.0 (personal price tracker; low volume)"}


def is_shopify(domain: str) -> bool:
    try:
        r = requests.get(f"https://{domain}/products.json?limit=1", headers=UA, timeout=15)
        return r.ok and "products" in r.json()
    except Exception:
        return False


def fetch(src: dict, max_pages: int = 20) -> list[Listing]:
    domain = src["domain"]
    coll = src.get("collection", "")
    base = f"https://{domain}/collections/{coll}/products.json" if coll else f"https://{domain}/products.json"
    out: list[Listing] = []
    for page in range(1, max_pages + 1):
        r = requests.get(base, params={"limit": 250, "page": page}, headers=UA, timeout=20)
        if r.status_code == 404 and coll:          # bad collection name -> fall back to whole store
            base = f"https://{domain}/products.json"
            continue
        r.raise_for_status()
        products = r.json().get("products", [])
        if not products:
            break
        out.extend(_parse(p, src, domain) for p in products)
        time.sleep(1.0)                            # be polite
    return [x for x in out if x]


def _parse(p: dict, src: dict, domain: str) -> Listing | None:
    variants = p.get("variants") or []
    if not variants:
        return None
    avail = [v for v in variants if v.get("available", True)] or variants
    cheapest = min(avail, key=lambda v: float(v["price"]))
    price = float(cheapest["price"])
    compare = cheapest.get("compare_at_price")
    original = float(compare) if compare and float(compare) > price else None
    sizes = sorted({(v.get("option1") or v.get("title") or "").strip() for v in variants
                    if v.get("available")} - {""})
    img = (p.get("images") or [{}])[0].get("src", "")
    return Listing(
        source=src["name"],
        title=p.get("title", ""),
        brand=src.get("brand") or p.get("vendor", ""),
        price=price,
        original=original,
        url=f"https://{domain}/products/{p.get('handle')}",
        image=img,
        sizes=sizes,
        description=(p.get("body_html") or "")[:2000] + " " + " ".join(p.get("tags") or []),
    )
