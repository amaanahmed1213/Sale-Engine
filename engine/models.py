from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field


@dataclass
class Listing:
    """One product as seen on one retailer at one moment."""
    source: str                 # "Nordstrom Rack", "Vuori", ...
    title: str
    brand: str                  # raw brand text from the site
    price: float                # current price
    original: float | None      # list / compare-at price, if shown
    url: str
    image: str = ""
    sizes: list[str] = field(default_factory=list)   # in-stock sizes, if known
    description: str = ""

    # filled in by the pipeline
    brand_key: str = ""
    category: str = ""
    score: int = 0
    reasons: list[str] = field(default_factory=list)
    code: str = ""              # best discount code that applies (brand's own site only)
    code_price: float | None = None

    @property
    def best_price(self) -> float:
        return self.code_price if self.code_price is not None else self.price

    @property
    def discount(self) -> float:
        if not self.original or self.original <= self.best_price:
            return 0.0
        return 1 - self.best_price / self.original

    @property
    def uid(self) -> str:
        """Stable ID per retailer+product so price history lines up across runs."""
        clean = re.sub(r"[?#].*$", "", self.url.strip().lower())
        return hashlib.sha1(f"{self.source}|{clean}".encode()).hexdigest()[:16]


def parse_money(text: str) -> list[float]:
    """'$128.00 $59.97 (53% off)' -> [128.0, 59.97]"""
    vals = re.findall(r"\$\s?(\d{1,4}(?:,\d{3})*(?:\.\d{2})?)", text or "")
    return [float(v.replace(",", "")) for v in vals]
