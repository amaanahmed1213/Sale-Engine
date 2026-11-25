"""Writes deals.html — a clean, phone-friendly grid of today's best finds."""
from __future__ import annotations

import html
from datetime import datetime

from .models import Listing

CSS = """
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,Inter,Helvetica,sans-serif;background:#f6f5f2;color:#1a1a1a}
header{padding:28px 24px 8px}h1{margin:0;font-size:24px;letter-spacing:-.02em}header p{color:#777;margin:6px 0 0;font-size:13px}
.bar{display:flex;gap:8px;flex-wrap:wrap;padding:12px 24px}.bar button{border:1px solid #ccc;background:#fff;border-radius:99px;padding:6px 12px;font-size:13px}
.bar button.on{background:#1a1a1a;color:#fff;border-color:#1a1a1a}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px;padding:12px 24px 40px}
.card{background:#fff;border-radius:14px;overflow:hidden;text-decoration:none;color:inherit;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.card img{width:100%;aspect-ratio:3/4;object-fit:cover;background:#eee;display:block}
.b{padding:12px 14px}.brand{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:#888}
.t{font-size:14px;margin:4px 0 8px;line-height:1.3}.p{font-weight:600}.was{color:#999;text-decoration:line-through;font-weight:400;margin-left:6px;font-size:13px}
.score{float:right;font-size:12px;font-weight:700;padding:2px 8px;border-radius:99px;background:#e8f3ea;color:#1f6b35}
.score.mid{background:#fdf3dc;color:#8a5a00}.why{font-size:12px;color:#666;margin-top:8px;line-height:1.4}.src{font-size:11px;color:#aaa;margin-top:6px}
.code{display:inline-block;margin-top:6px;font:600 11px ui-monospace,monospace;background:#1a1a1a;color:#fff;padding:3px 7px;border-radius:5px}
"""

JS = """
const btns=document.querySelectorAll('.bar button');btns.forEach(b=>b.onclick=()=>{btns.forEach(x=>x.classList.remove('on'));b.classList.add('on');
const c=b.dataset.c;document.querySelectorAll('.card').forEach(k=>k.style.display=(c==='all'||k.dataset.c===c)?'':'none')});
"""


def write(items: list[Listing], path: str = "deals.html", min_score: int = 50) -> str:
    items = [i for i in items if i.score >= min_score]
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
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Deals</title><style>{CSS}</style></head><body><header><h1>Today's real deals</h1>
<p>{len(items)} picks · score ≥ {min_score} · {datetime.now():%a %b %d, %I:%M %p}</p></header>
<div class="bar">{bar}</div><div class="grid">{''.join(cards) or '<p>No deals cleared the bar today.</p>'}</div>
<script>{JS}</script></body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    return path
