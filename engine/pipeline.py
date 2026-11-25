"""Filter → score. This is where 'actually good sale' gets decided.

Score (0–100) blends:
  • Depth vs. the brand's normal  — 40% off BR is routine; 25% off Quince isn't.
  • Price history                 — at/below the lowest price we've ever logged = big bonus;
                                    "original" price we've never actually seen = fake-MSRP penalty.
  • Under your ceiling            — below the max_price you set for the category.
  • Fabric                        — non-athletic tops in good natural fibres get a bump; mostly-poly gets flagged.
  • Size availability             — your size in stock (if the source reports sizes).
"""
from __future__ import annotations

import re

from .db import DB
from .models import Listing


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9& ]+", " ", (s or "").lower()).strip()


class Pipeline:
    def __init__(self, cfg: dict, db: DB):
        self.cfg, self.db = cfg, db
        self.brand_index: dict[str, str] = {}
        for key, b in cfg["brands"].items():
            for name in [key, *b.get("aliases", [])]:
                self.brand_index[_norm(name)] = key
        self.exclude = [_norm(x) for x in cfg["filters"]["exclude"]]
        # codes only work on the brand's own site, not at Rack/Gilt/Nordstrom
        self.own_sites = {s["name"] for s in cfg["sources"] if s.get("brand")}
        self.codes = db.best_codes(cfg.get("codes", {}).get("apply_min_confidence", 45))

    # ── matching ─────────────────────────────────────────────
    def match_brand(self, item: Listing) -> str:
        text = _norm(item.brand) or _norm(item.title)
        if text in self.brand_index:
            return self.brand_index[text]
        # longest alias that appears as a whole word in brand or title
        hay = f" {_norm(item.brand)} {_norm(item.title)} "
        for alias in sorted(self.brand_index, key=len, reverse=True):
            if len(alias) <= 2 and _norm(item.brand) != alias:   # "ag" only when it's the brand field
                continue
            if f" {alias} " in hay:
                return self.brand_index[alias]
        return ""

    def match_category(self, item: Listing) -> str:
        t = _norm(item.title)
        for name, c in self.cfg["categories"].items():
            if any(_norm(k) in t for k in c["keywords"]):
                return name
        return ""

    def excluded(self, item: Listing) -> bool:
        hay = f" {_norm(item.title)} {_norm(item.brand)} {_norm(item.url)} "
        return any(f" {x} " in hay or x in _norm(item.url) for x in self.exclude)

    def size_ok(self, item: Listing) -> bool | None:
        if not item.sizes:
            return None                                   # unknown
        mine = self.cfg["me"]["sizes_bottoms" if item.category in ("pants", "jeans") else "sizes_tops"]
        have = {s.lower().replace(" ", "") for s in item.sizes}
        return any(m.lower().replace(" ", "") in have or
                   any(h.startswith(m.lower()) for h in have) for m in mine)

    # ── scoring ──────────────────────────────────────────────
    def score(self, item: Listing) -> None:
        b = self.cfg["brands"][item.brand_key]
        cat = self.cfg["categories"][item.category]
        typical = b.get("typical_sale", 0.25)
        s, why = 0.0, []

        d = item.discount
        if d > 0:
            # 25 pts for matching the brand's normal sale, up to 45 for beating it by 30+ pts
            s += min(45, 25 * d / max(typical, 0.05)) if d <= typical else 25 + min(20, (d - typical) * 70)
            why.append(f"{d:.0%} off (brand usually ~{typical:.0%})")

        st = self.db.stats(item.uid)
        if st["low"] is not None:
            if item.best_price <= st["low"]:
                s += 25
                why.append(f"lowest price in {st['n_days']} days tracked")
            elif st["median"] and item.best_price < st["median"]:
                s += 10
                why.append(f"below its usual ${st['median']:.0f}")
            else:
                s -= 5
                why.append(f"has been cheaper (${st['low']:.0f})")
            if item.original and st["high"] and st["high"] < item.original * 0.9 and st["n_days"] >= 14:
                s -= 15
                why.append("never seen at the 'original' price → inflated MSRP?")
        else:
            why.append("new to tracker")

        if item.best_price <= cat["max_price"]:
            s += 15
            why.append(f"under your ${cat['max_price']} ceiling")
        elif item.best_price > cat["max_price"] * 1.5:
            s -= 15

        if not b.get("athletic") and item.category in ("henley", "long_sleeve"):
            desc = _norm(item.title + " " + item.description)
            if any(f in desc for f in self.cfg["filters"]["good_fabrics"]):
                s += 8
                why.append("natural fibre")
            elif re.search(r"\b(100 )?polyester\b|\bacrylic\b", desc):
                s -= 10
                why.append("mostly synthetic")

        sz = self.size_ok(item)
        if sz is True:
            s += 7
            why.append("your size in stock")
        elif sz is False:
            s -= 40
            why.append("your size sold out")

        item.score = max(0, min(100, round(s)))
        item.reasons = why

    # ── run ──────────────────────────────────────────────────
    def process(self, items: list[Listing], record: bool = True) -> list[Listing]:
        kept = []
        for it in items:
            if it.price <= 0 or self.excluded(it):
                continue
            it.brand_key = self.match_brand(it)
            if not it.brand_key:
                continue                                  # not one of your brands
            it.category = self.match_category(it)
            if not it.category:
                continue                                  # not something you wear
            c = self.codes.get(it.brand_key)
            if c and c.get("pct") and it.source in self.own_sites:
                it.code = c["code"]
                it.code_price = round(it.price * (1 - c["pct"] / 100), 2)
            self.score(it)                                # score BEFORE recording today's price
            if it.code:
                it.reasons.insert(0, f"${it.code_price:.0f} with code {it.code} (−{c['pct']}%, unverified)")
            if record:
                self.db.record(it)
            kept.append(it)
        return sorted(kept, key=lambda x: (-x.score, x.price))
