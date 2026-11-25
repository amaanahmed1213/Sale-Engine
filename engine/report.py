"""Writes deals.html — a clean, phone-friendly grid of today's best finds."""
from __future__ import annotations

import html
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from .models import Listing

CSS = """
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,Inter,Helvetica,sans-serif;background:#f6f5f2;color:#1a1a1a}
header{padding:24px 16px 8px}h1{margin:0;font-size:24px;letter-spacing:-.02em}header p{color:#777;margin:6px 0 0;font-size:13px}
.bar{display:flex;gap:8px;flex-wrap:wrap;padding:12px 16px}.bar button{border:1px solid #ccc;background:#fff;border-radius:99px;padding:6px 12px;font-size:13px}
.bar button.on{background:#1a1a1a;color:#fff;border-color:#1a1a1a}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;padding:12px 16px 30px}
.card{background:#fff;border-radius:14px;overflow:hidden;text-decoration:none;color:inherit;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.card img{width:100%;aspect-ratio:3/4;object-fit:cover;background:#eee;display:block}
.b{padding:12px 14px}.brand{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:#888}
.t{font-size:14px;margin:4px 0 8px;line-height:1.3}.p{font-weight:600}.was{color:#999;text-decoration:line-through;font-weight:400;margin-left:6px;font-size:13px}
.score{float:right;font-size:12px;font-weight:700;padding:2px 8px;border-radius:99px;background:#e8f3ea;color:#1f6b35}
.score.mid{background:#fdf3dc;color:#8a5a00}.why{font-size:12px;color:#666;margin-top:8px;line-height:1.4}.src{font-size:11px;color:#aaa;margin-top:6px}
h2{font-size:17px;margin:26px 16px 4px}.sub{color:#888;font-size:12px;margin:0 16px 10px}
table{border-collapse:collapse;width:100%;background:#fff;border-radius:12px;overflow:hidden;font-size:13px}
td,th{padding:9px 10px;white-space:nowrap;border-bottom:1px solid #f0efe9;text-align:left}th{font-size:11px;text-transform:uppercase;color:#999;letter-spacing:.06em}
td.c{font:600 13px ui-monospace,monospace}a.btn{display:inline-block;margin-top:10px;font-size:13px;color:#1a1a1a;border:1px solid #1a1a1a;border-radius:99px;padding:5px 12px;text-decoration:none}
.tw{overflow-x:auto;margin:0 16px 30px;border-radius:12px}
.code{display:table;margin-top:6px;font:600 11px ui-monospace,monospace;background:#1a1a1a;color:#fff;padding:3px 7px;border-radius:5px}
"""

JS = """
const btns=document.querySelectorAll('.bar button');btns.forEach(b=>b.onclick=()=>{btns.forEach(x=>x.classList.remove('on'));b.classList.add('on');
const c=b.dataset.c;document.querySelectorAll('.card').forEach(k=>k.style.display=(c==='all'||k.dataset.c===c)?'':'none')});
"""


def write(items: list[Listing], path: str = "docs/index.html", min_score: int = 50,
          codes: list[dict] | None = None, watch: list[dict] | None = None) -> str:
    items = [i for i in items if i.score >= min_score]
    # one card per product: colour variants share a title + price
    seen, uniq = set(), []
    for i in items:
        k = (i.source, i.title.split(" - ")[0].split(" -- ")[0].lower(), round(i.best_price))
        if k not in seen:
            seen.add(k)
            uniq.append(i)
    items = uniq
    cats = sorted({i.category for i in items})
    e = html.escape
    cards = []
    for i in items:
        was = f'<span class="was">${i.original:.0f}</span>' if i.original else ""
        if i.code:
            was = f'<span class="was">${i.price:.0f}</span>' + was + f'<div class="code">code {e(i.code)}</div>'
        cls = "score" if i.score >= 70 else "score mid"
        cards.append(f"""<a class="card" data-c="{e(i.category)}" href="{e(i.url)}" target="_blank">
<img src="{e(i.image)}" loading="lazy" alt=""><div class="b"><span class="{cls}">{i.score}</span>
<div class="brand">{e(i.brand_key)}</div><div class="t">{e(i.title)}</div>
<div class="p">${i.best_price:.0f}{was}</div><div class="why">{e(' · '.join(i.reasons[:4]))}</div>
<div class="src">{e(i.source)}</div></div></a>""")
    bar = '<button class="on" data-c="all">All</button>' + "".join(
        f'<button data-c="{e(c)}">{e(c.replace("_", " ").title())}</button>' for c in cats)
    code_rows = "".join(
        f'<tr><td>{e(c["brand"].title())}</td><td class="c">{e(c["code"])}</td>'
        f'<td>{str(c["pct"]) + "%" if c.get("pct") else "?"}</td><td>{e(str(c["newest"]))}</td>'
        f'<td>{c["confidence"]}</td><td><a href="{e(c["url"])}" target="_blank">{e(c["sources"])}</a></td></tr>'
        for c in (codes or []))
    codes_html = (f"""<h2>Discount codes</h2><p class="sub">Unverified. Higher confidence = recent + seen in several places.</p>
<div class="tw"><table><tr><th>Brand</th><th>Code</th><th>Off</th><th>Last seen</th><th>Conf.</th><th>Where</th></tr>{code_rows}</table></div>"""
                  if code_rows else "")
    watch_rows = "".join(
        f'<tr><td><a href="{e(w["url"])}" target="_blank">{e(w["title"][:60])}</a></td>'
        f'<td>{"$%.0f" % w["price"] if w["price"] else "?"}</td><td>${w["target"]:.0f}</td>'
        f'<td>{"✅ hit" if w["price"] and w["price"] <= w["target"] else ""}</td></tr>' for w in (watch or []))
    watch_html = (f"""<h2>Price tracking</h2><p class="sub">Add items by editing watchlist.txt in your GitHub repo.</p>
<div class="tw"><table><tr><th>Item</th><th>Now</th><th>Target</th><th></th></tr>{watch_rows}</table></div>""" if watch_rows else "")
    repo = os.getenv("GITHUB_REPOSITORY")
    refresh = f'<a class="btn" href="https://github.com/{repo}/actions/workflows/scan.yml" target="_blank">↻ Refresh now</a>' if repo else ""
    now = datetime.now(ZoneInfo("America/New_York"))
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Deals</title><style>{CSS}</style></head><body><header><h1>Today's real deals</h1>
<p>{len(items)} picks · updated {now:%a %b %d, %I:%M %p}</p>{refresh}</header>
<div class="bar">{bar}</div><div class="grid">{''.join(cards) or '<p>No deals cleared the bar today.</p>'}</div>
{codes_html}{watch_html}
<script>{JS}</script></body></html>"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    return path
