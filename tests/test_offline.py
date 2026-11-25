"""Offline test: fake Rack page + fake Shopify feed + fake history. Run: python -m tests.test_offline"""
import json
import os
import sys
import tomllib
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from engine.db import DB
from engine.pipeline import Pipeline
from engine.sources import page, shopify
from engine import report

cfg = tomllib.load(open(os.path.join(os.path.dirname(__file__), "..", "config.toml"), "rb"))

RACK_HTML = """<html><body>
<article><a href="/s/rag-bone-waffle-henley/123"><img src="a.jpg"></a><div class="brand">rag & bone</div>
 <h3>Classic Waffle Henley</h3><div class="price">$145.00 $49.97</div></article>
<article><a href="/s/theory-zaine/9"><img src="b.jpg"></a><div class="brand">Theory</div>
 <h3>Zaine Slim Fit Pant</h3><div class="price">$225.00 $79.97</div></article>
<article><a href="/s/cheap/1"><img src="c.jpg"></a><div class="brand">Some Mall Brand</div>
 <h3>Waffle Henley</h3><div class="price">$40.00 $12.97</div></article>
<article><a href="/s/lrl/1"><div class="brand">Lauren Ralph Lauren</div></a>
 <h3>Classic Fit Chino Pant</h3><div class="price">$95.00 $39.97</div></article>
<article><a href="/s/br-factory"><div class="brand">Banana Republic Factory</div></a>
 <h3>Waffle Henley</h3><div class="price">$50.00 $19.97</div></article>
</body></html>"""

LULU_HTML = """<script type="application/ld+json">""" + json.dumps({
    "@type": "ItemList", "itemListElement": [
        {"@type": "ListItem", "item": {"@type": "Product", "name": "ABC Classic-Fit Pant 32\"",
         "url": "/p/abc-pant", "brand": {"name": "lululemon"}, "image": "abc.jpg",
         "offers": {"@type": "AggregateOffer", "lowPrice": "69", "highPrice": "128"}}},
        {"@type": "ListItem", "item": {"@type": "Product", "name": "Women's Align Legging",
         "url": "/p/align", "offers": {"price": "59"}}},
    ]}) + "</script>"

SHOPIFY = {"products": [
    {"title": "Ponto Performance Pant", "handle": "ponto", "vendor": "Vuori",
     "variants": [{"price": "89.00", "compare_at_price": "98.00", "option1": "M", "available": True}],
     "images": [{"src": "ponto.jpg"}], "tags": []},
    {"title": "Strato Tech Tee Long Sleeve", "handle": "strato-ls", "vendor": "Vuori",
     "variants": [{"price": "39.00", "compare_at_price": "68.00", "option1": "M", "available": False},
                  {"price": "39.00", "compare_at_price": "68.00", "option1": "XL", "available": True}],
     "images": [], "tags": []},
]}


def main():
    if os.path.exists("test.db"):
        os.remove("test.db")
    db = DB("test.db")
    pipe = Pipeline(cfg, db)

    rack = page.parse(RACK_HTML, "https://www.nordstromrack.com/", next(s for s in cfg["sources"] if s["name"] == "Nordstrom Rack"))
    lulu = page.parse(LULU_HTML, "https://shop.lululemon.com/", {"name": "lululemon WMTM", "brand": "lululemon"})
    vsrc = {"name": "Vuori", "brand": "vuori", "domain": "vuoriclothing.com"}
    vuori = [shopify._parse(p, vsrc, vsrc["domain"]) for p in SHOPIFY["products"]]

    # Fake 30 days of history for the Theory pant: it's been $79.97 to $99 before,
    # and has NEVER been at $225 → should get the inflated-MSRP flag.
    theory = next(x for x in rack if "Zaine" in x.title)
    for d in range(1, 31):
        theory_past = type(theory)(**{**theory.__dict__})
        theory_past.price = 99.0 if d > 10 else 79.97
        db.record(theory_past, (date.today() - timedelta(days=d)).isoformat())

    out = pipe.process(rack + lulu + vuori)
    print(f"parsed: rack={len(rack)} lulu={len(lulu)} vuori={len(vuori)} -> kept {len(out)}\n")
    for it in out:
        print(f"[{it.score:>3}] {it.brand_key:<12} {it.category:<11} ${it.price:<7} {it.title}")
        print(f"       {' · '.join(it.reasons)}")

    titles = [o.title for o in out]
    assert "Classic Fit Chino Pant" not in titles, "Lauren Ralph Lauren should be excluded"
    assert not any(o.brand_key == "banana republic" for o in out), "BR Factory should be excluded"
    assert not any("Align" in t for t in titles), "womens should be excluded"
    assert sum("Waffle Henley" in t for t in titles) == 1, "mall brand should be dropped"
    strato = next(o for o in out if "Strato" in o.title)
    assert "your size sold out" in strato.reasons
    th = next(o for o in out if "Zaine" in o.title)
    assert any("inflated" in r for r in th.reasons)
    report.write(out, "test_deals.html", min_score=0)
    print("\nall checks passed; wrote test_deals.html")


if __name__ == "__main__":
    main()
