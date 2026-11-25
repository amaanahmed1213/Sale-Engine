"""Offline test for the code finder. Run: python -m tests.test_codes"""
import os
import sys
import time
import tomllib
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from engine import codes
from engine.db import DB
from engine.models import Listing
from engine.pipeline import Pipeline

cfg = tomllib.load(open(os.path.join(os.path.dirname(__file__), "..", "config.toml"), "rb"))
now = time.time()


def fake_reddit(path, params):
    posts = [
        ("[Abercrombie] Extra 25% off with code AFTIKTOK25 — stacks with sale prices!", "", 2, 140, "frugalmalefashion"),
        ("Abercrombie code AFTIKTOK25 still working?", "yes just used it, worked on jeans", 1, 12, "abercrombie"),
        ("Abercrombie promo SAVE15NOW 15% off", "edit: expired, doesn't work anymore", 3, 30, "Coupons"),
        ("Old Abercrombie code SUMMER20 for 20% off", "", 60, 300, "frugalmalefashion"),   # too old
        ("Use code FREE for free shipping at Abercrombie", "", 1, 5, "deals"),            # stopword
        ("Vuori code NEWYOU 20% off first order", "", 1, 50, "frugalmalefashion"),      # wrong brand
    ]
    return {"data": {"children": [{"data": {
        "title": t, "selftext": b, "created_utc": now - d * 86400, "score": sc,
        "subreddit": sub, "permalink": f"/r/{sub}/x{i}"}} for i, (t, b, d, sc, sub) in enumerate(posts)]}}


codes._reddit_get = fake_reddit
codes.time.sleep = lambda s: None


def main():
    assert [c["code"] for c in codes.extract("Use code: “ALO30” for 30% off sitewide")] == ["ALO30"]
    assert codes.extract("use the code in my bio")[0:1] == [] or all(c["code"] != "BIO" for c in codes.extract("use the code in my bio"))
    assert codes._tiktok_date("https://www.tiktok.com/@x/video/7300000000000000000").year >= 2023

    s = codes.from_reddit("abercrombie", ["abercrombie", "abercrombie & fitch"], ["frugalmalefashion"], 21)
    s += [{"code": "AFTIKTOK25", "pct": 25, "brand": "abercrombie", "source": "tiktok",
           "url": "https://tiktok.com/x", "seen": datetime.now(timezone.utc) - timedelta(days=1),
           "votes": 2, "sentiment": 0}]
    ranked = codes.rank(s, 21)
    for c in ranked:
        print(f"  {c['confidence']:>3}  {c['code']:<12} {c['pct']}%  {c['age_days']}d  {c['sources']}")
    got = {c["code"]: c for c in ranked}
    assert "SUMMER20" not in got, "old code should drop"
    assert "FREE" not in got and "NEWYOU" not in got
    assert got["AFTIKTOK25"]["confidence"] > got["SAVE15NOW"]["confidence"]
    assert got["SAVE15NOW"]["confidence"] < 45, "expired code shouldn't be applied"

    if os.path.exists("test_codes.db"):
        os.remove("test_codes.db")
    db = DB("test_codes.db")
    db.save_codes(ranked)
    pipe = Pipeline(cfg, db)
    own = Listing("Abercrombie", "Athletic Straight Jean", "Abercrombie", 60.0, 90.0, "https://abercrombie.com/p/1")
    rack = Listing("Nordstrom Rack", "Waffle Henley", "Abercrombie & Fitch", 30.0, 50.0, "https://rack.com/p/2")
    out = pipe.process([own, rack])
    for it in out:
        print(f"  [{it.score}] {it.source:<15} ${it.best_price}  code={it.code or '-'}  {it.reasons[0]}")
    j = next(o for o in out if o.source == "Abercrombie")
    r = next(o for o in out if o.source == "Nordstrom Rack")
    assert j.code == "AFTIKTOK25" and j.code_price == 45.0
    assert r.code == "", "codes shouldn't apply at Rack"
    os.remove("test_codes.db")
    print("\ncode finder checks passed")


if __name__ == "__main__":
    main()


def test_web_search():
    """Fake DuckDuckGo results page with a TikTok link."""
    from engine import codes as c
    vid = (int(time.time() - 2 * 86400) << 32) | 12345          # a video posted 2 days ago
    html = f"""<div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.tiktok.com%2F%40styleguy%2Fvideo%2F{vid}">
    Abercrombie haul 🔥 use code STYLEGUY20 for 20% off</a><div class="result__snippet">abercrombie jeans try on, code STYLEGUY20 at checkout</div></div>"""

    class R:
        text = html
    c.requests.post = lambda *a, **k: R()
    got = c.from_web_search("abercrombie", ["abercrombie"], 21)
    assert got and got[0]["code"] == "STYLEGUY20" and got[0]["pct"] == 20
    assert got[0]["source"] == "tiktok (search)"
    assert 1 <= (datetime.now(timezone.utc) - got[0]["seen"]).days <= 2, "date should come from TikTok video ID"
    print(f"  web search → {got[0]['code']} {got[0]['pct']}% posted {(datetime.now(timezone.utc) - got[0]['seen']).days}d ago ({got[0]['source']})")
    print("web search checks passed")


if __name__ == "__main__":
    test_web_search()
