#!/usr/bin/env python3
"""Sale Engine — finds real sales on the brands you actually wear.

  python run.py scan                 scan every source, score, save history, write deals.html, send alerts
  python run.py scan --only Vuori    scan one source
  python run.py probe                check which brand sites are Shopify (fast + reliable source)
  python run.py watch URL 79         track one product; alert when it drops to $79 or lower
  python run.py watchlist            show tracked products
  python run.py check                re-check watchlist prices only
  python run.py history SEARCH       price history for products matching SEARCH
  python run.py codes                find discount codes (Reddit, homepages, coupon sites, email, TikTok)
  python run.py codes alo            codes for one brand
"""
from __future__ import annotations

import argparse
import sys
import tomllib
import traceback

from engine import alerts, codes as codefinder, report
from engine.db import DB
from engine.models import Listing
from engine.pipeline import Pipeline
from engine.sources import page, shopify


def load_cfg(path="config.toml") -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def fetch_source(src: dict) -> list[Listing]:
    if src["kind"] == "shopify":
        return shopify.fetch(src)
    return page.fetch(src)


def cmd_scan(cfg, db, only=None, headful=False):
    pipe = Pipeline(cfg, db)
    everything: list[Listing] = []
    for src in cfg["sources"]:
        if only and only.lower() not in src["name"].lower():
            continue
        if headful:
            src["headless"] = False
        print(f"→ {src['name']:<28}", end="", flush=True)
        try:
            raw = fetch_source(src)
            kept = pipe.process(raw)
            print(f"{len(raw):>4} listings → {len(kept):>3} match your brands/style")
            everything.extend(kept)
        except Exception as e:
            print(f"  failed: {type(e).__name__}: {str(e)[:90]}")
            if "-v" in sys.argv:
                traceback.print_exc()

    everything.sort(key=lambda x: -x.score)
    path = report.write(everything)
    print(f"\nTop deals:")
    for it in everything[:15]:
        print("  " + alerts.line(it))
    print(f"\nFull report: {path}")
    send_alerts(cfg, db, [i for i in everything if i.score >= cfg["alerts"]["min_score"]])


def send_alerts(cfg, db, items):
    fresh = [i for i in items if not db.already_alerted(i.uid, i.price)]
    if not fresh:
        return
    a = cfg["alerts"]
    if a.get("ntfy_topic"):
        alerts.push_ntfy(a["ntfy_topic"], fresh)
    if a.get("email_to"):
        alerts.email(a["email_to"], fresh)
    for i in fresh:
        db.mark_alerted(i.uid, i.price)
    print(f"Alerted on {len(fresh)} new deal(s).")


def fetch_single(url: str) -> Listing | None:
    """Price for one product page: Shopify .json if available, else rendered JSON-LD."""
    import requests
    from urllib.parse import urlparse
    base = url.split("?")[0].rstrip("/")
    if "/products/" in base:
        try:
            r = requests.get(base + ".js", headers=shopify.UA, timeout=15)
            if r.ok:
                p = r.json()
                v = min(p["variants"], key=lambda v: v["price"])
                return Listing(source=urlparse(url).netloc, title=p["title"], brand=p.get("vendor", ""),
                               price=v["price"] / 100,
                               original=(v.get("compare_at_price") or 0) / 100 or None, url=base)
        except Exception:
            pass
    items = page.parse(page.render(url, scrolls=1), url, {"name": urlparse(url).netloc})
    return items[0] if items else None


def cmd_check(cfg, db):
    hits = []
    for w in db.watchlist():
        try:
            it = fetch_single(w["url"])
        except Exception as e:
            print(f"  ✗ {w['url'][:70]}  ({type(e).__name__})")
            continue
        if not it:
            print(f"  ? couldn't read price: {w['url'][:70]}")
            continue
        db.record(it)
        hit = it.price <= w["target"]
        st = db.stats(it.uid)
        low = f"  low ${st['low']:.0f}" if st["low"] else ""
        print(f"  {'✓' if hit else '·'} ${it.price:>6.2f}  target ${w['target']:.0f}{low}  {it.title[:50]}")
        if hit:
            it.brand_key, it.score = it.brand or it.source, 100
            it.reasons = [f"hit your ${w['target']:.0f} target"]
            hits.append(it)
    send_alerts(cfg, db, hits)


def cmd_probe(cfg):
    for src in cfg["sources"]:
        dom = src.get("domain")
        if not dom:
            from urllib.parse import urlparse
            dom = urlparse(src["urls"][0]).netloc
        print(f"  {src['name']:<28} {dom:<32} {'SHOPIFY ✓' if shopify.is_shopify(dom) else 'not shopify'}")


def cmd_codes(cfg, db, only=None, headful=False):
    cc = cfg.get("codes", {})
    days = cc.get("days", 21)
    sightings = []
    brands = {k: v for k, v in cfg["brands"].items() if not only or only.lower() in k}

    def attempt(label, fn, *a):
        try:
            got = fn(*a)
            sightings.extend(got)
            return len(got)
        except Exception as e:
            print(f"    {label}: failed ({type(e).__name__})")
            return 0

    for key, b in brands.items():
        names = [key, *b.get("aliases", [])]
        n = attempt("reddit", codefinder.from_reddit, key, names, cc.get("subreddits", ["frugalmalefashion"]), days)
        if key in cc.get("homepages", {}):
            n += attempt("homepage", codefinder.from_homepage, key, cc["homepages"][key])
        if key in cc.get("coupon_pages", {}):
            n += attempt("coupon site", codefinder.from_coupon_page, key, cc["coupon_pages"][key])
        if cc.get("web_search", True):
            n += attempt("web search", codefinder.from_web_search, key, names, days)
        if cc.get("tiktok"):
            n += attempt("tiktok", codefinder.from_tiktok, key, names, not headful)
        print(f"  {key:<16} {n} sightings")
    sightings += codefinder.from_email(brands, days)

    ranked = codefinder.rank(sightings, days)
    new = db.save_codes(ranked)
    print("\nCodes (confidence · % · last seen · where):")
    cur = None
    for c in ranked:
        if c["brand"] != cur:
            cur = c["brand"]
            print(f"\n  {cur.upper()}")
        pct = f"{c['pct']}%" if c["pct"] else "  ?"
        flag = "  ← NEW" if c in new else ""
        print(f"    {c['confidence']:>3}  {c['code']:<18} {pct:>4}  {c['age_days']:>2}d ago  {', '.join(c['sources'])}{flag}")
    if not ranked:
        print("  none found")
    topic = cfg["alerts"].get("ntfy_topic")
    fresh = [c for c in new if c["confidence"] >= cc.get("alert_min_confidence", 55)]
    if topic and fresh:
        alerts.push_codes(topic, fresh)
        print(f"\nPushed {len(fresh)} new code(s) to your phone.")


def cmd_history(db, q):
    rows = db.conn.execute("SELECT uid, source, title FROM products WHERE title LIKE ? LIMIT 20",
                           (f"%{q}%",)).fetchall()
    for r in rows:
        h = db.history(r["uid"], 365)
        trail = "  ".join(f"{x['day'][5:]} ${x['price']:.0f}" for x in h[-10:])
        print(f"{r['title'][:55]} @ {r['source']}\n    {trail}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["scan", "probe", "watch", "unwatch", "watchlist", "check", "history", "codes"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--only")
    ap.add_argument("--headful", action="store_true", help="show the browser (helps with bot checks)")
    ap.add_argument("--config", default="config.toml")
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args()
    cfg, db = load_cfg(a.config), DB()

    if a.cmd == "scan":
        cmd_scan(cfg, db, a.only, a.headful)
    elif a.cmd == "probe":
        cmd_probe(cfg)
    elif a.cmd == "watch":
        db.watch(a.args[0], float(a.args[1]), " ".join(a.args[2:]))
        print("Watching. Run `python run.py check` (or schedule it) to monitor.")
    elif a.cmd == "unwatch":
        db.unwatch(a.args[0])
    elif a.cmd == "watchlist":
        for w in db.watchlist():
            print(f"  ${w['target']:>6.0f}  {w['url']}")
    elif a.cmd == "check":
        cmd_check(cfg, db)
    elif a.cmd == "codes":
        cmd_codes(cfg, db, a.args[0] if a.args else a.only, a.headful)
    elif a.cmd == "history":
        cmd_history(db, " ".join(a.args))


if __name__ == "__main__":
    main()
