"""Discount-code finder.

Where codes actually show up, best → worst:
  1. Reddit   — r/frugalmalefashion especially; posts are dated + upvoted, so freshness is easy to judge.
  2. Email    — brand newsletters usually get codes first. Point this at a throwaway Gmail you
                subscribe to every brand with (IMAP, optional).
  3. Homepage — "Use code XYZ" banners on the brand's own site.
  4. Coupon sites — Knoji / CouponFollow / Dealspotr pages often repost influencer (TikTok) codes.
  5. TikTok   — experimental. No public search API; the page scraper works sometimes, in --headful mode.

Every sighting is stored with a date. A code's confidence comes from: how recent the newest
sighting is, how many independent places mention it, upvotes, and "worked" vs "expired" words.
"""
from __future__ import annotations

import email
import imaplib
import os
import re
import time
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "python:sale-engine-personal:v1.0 (personal deal tracker)"}

# Words that look like codes but aren't.
STOP = {"FREE", "SALE", "OFF", "THE", "AND", "CODE", "CODES", "PROMO", "USE", "USA", "TIKTOK", "LINK", "BIO",
        "SHOP", "NOW", "NEW", "TODAY", "ONLY", "ALL", "YOUR", "WITH", "THIS", "THAT", "ORDER", "ORDERS",
        "DISCOUNT", "COUPON", "SITEWIDE", "EXTRA", "PERCENT", "SHIPPING", "AT", "CHECKOUT", "HERE",
        "WORKS", "WORKED", "EXPIRED", "FOR", "ANY", "APP", "SIGN", "EMAIL", "TEXT", "FIRST", "BLACK", "FRIDAY",
        "CYBER", "MONDAY", "PSA", "EDIT", "UPDATE", "DEAL", "DEALS", "STACK", "STACKS", "MEN", "MENS", "WOMEN",
        "ABC", "ALO", "BOGO", "MSRP", "USD", "NYC", "LA", "FMF", "GOT", "GET", "OK", "YES", "NOT", "DONT", "DOES"}

CODE_RX = re.compile(
    r"(?:\buse(?:\s+(?:the\s+)?(?:promo\s+|discount\s+)?code)?|\bpromo(?:\s*code)?|\bcoupon(?:\s*code)?"
    r"|\bdiscount\s+code|\bcode|\benter(?:\s+code)?)"
    r"\s*[:\-–]?\s*[\"'“”‘’`*]*([A-Za-z0-9][A-Za-z0-9_-]{3,19})",
    re.I)
PCT_RX = re.compile(r"(\d{1,2})\s?%\s?off|(\d{1,2})\s?percent\s?off", re.I)
GOOD_WORDS = ("worked", "works", "still working", "confirmed", "just used", "stacks")
BAD_WORDS = ("expired", "didn't work", "doesnt work", "doesn't work", "not working", "invalid", "dead")


def extract(text: str) -> list[dict]:
    """Pull (code, pct) pairs out of free text."""
    out = []
    for m in CODE_RX.finditer(text or ""):
        raw = m.group(1).strip("-_")
        code = raw.upper()
        if code in STOP or not re.search(r"[A-Z]", code) or len(code) < 4:
            continue
        # real codes are usually written in caps or contain digits; skip plain lowercase words
        if raw.islower() and not re.search(r"\d", raw):
            continue
        window = text[max(0, m.start() - 80): m.end() + 80]
        pm = PCT_RX.search(window)
        pct = int(pm.group(1) or pm.group(2)) if pm else None
        out.append({"code": code, "pct": pct})
    # de-dupe within one text
    seen, uniq = set(), []
    for c in out:
        if c["code"] not in seen:
            seen.add(c["code"])
            uniq.append(c)
    return uniq


def mentions_brand(text: str, names: list[str]) -> bool:
    t = f" {re.sub(r'[^a-z0-9& ]', ' ', text.lower())} "
    return any(f" {re.sub(r'[^a-z0-9& ]', ' ', n.lower()).strip()} " in t for n in names)


def sentiment(text: str) -> int:
    t = text.lower()
    return sum(w in t for w in GOOD_WORDS) - 2 * sum(w in t for w in BAD_WORDS)


# ── Reddit ───────────────────────────────────────────────────
_token = None


def _reddit_get(path: str, params: dict) -> dict:
    """Uses the official API if REDDIT_CLIENT_ID/SECRET are set (more reliable), else public JSON."""
    global _token
    cid, sec = os.getenv("REDDIT_CLIENT_ID"), os.getenv("REDDIT_CLIENT_SECRET")
    if cid and sec:
        if not _token:
            r = requests.post("https://www.reddit.com/api/v1/access_token", auth=(cid, sec),
                              data={"grant_type": "client_credentials"}, headers=UA, timeout=15)
            _token = r.json()["access_token"]
        r = requests.get(f"https://oauth.reddit.com{path}", params=params,
                         headers={**UA, "Authorization": f"bearer {_token}"}, timeout=15)
    else:
        r = requests.get(f"https://www.reddit.com{path}.json", params=params, headers=UA, timeout=15)
    r.raise_for_status()
    time.sleep(1.2)
    return r.json()


def from_reddit(brand: str, names: list[str], subs: list[str], days: int) -> list[dict]:
    t = "week" if days <= 7 else "month" if days <= 31 else "year"
    found = []
    queries = [(f"/r/{'+'.join(subs)}/search", {"restrict_sr": 1}), ("/search", {})]
    for path, extra in queries:
        q = " OR ".join(f'"{n}"' for n in names[:3]) + " (code OR promo OR coupon)"
        data = _reddit_get(path, {"q": q, "sort": "new", "t": t, "limit": 50, **extra})
        for child in data.get("data", {}).get("children", []):
            p = child["data"]
            text = f"{p.get('title', '')}\n{p.get('selftext', '')}"
            if not mentions_brand(text, names):
                continue
            when = datetime.fromtimestamp(p["created_utc"], tz=timezone.utc)
            for c in extract(text):
                found.append({**c, "brand": brand, "source": f"reddit r/{p['subreddit']}",
                              "url": "https://reddit.com" + p["permalink"], "seen": when,
                              "votes": p.get("score", 0), "sentiment": sentiment(text)})
    return found


# ── Brand homepage banners ───────────────────────────────────
def from_homepage(brand: str, url: str) -> list[dict]:
    from .sources.page import render
    html = render(url, scrolls=1)
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    now = datetime.now(timezone.utc)
    return [{**c, "brand": brand, "source": "brand homepage", "url": url, "seen": now,
             "votes": 25, "sentiment": 1} for c in extract(text)]   # official = high trust


# ── Coupon aggregator pages (optional, per brand in config) ──
def from_coupon_page(brand: str, url: str) -> list[dict]:
    from .sources.page import render
    soup = BeautifulSoup(render(url, scrolls=2), "html.parser")
    now = datetime.now(timezone.utc)
    out = []
    # many aggregators put the code in data-code / data-clipboard-text attributes
    for el in soup.select("[data-code], [data-clipboard-text], [data-coupon-code]"):
        code = (el.get("data-code") or el.get("data-clipboard-text") or el.get("data-coupon-code") or "").upper()
        if 4 <= len(code) <= 20 and code not in STOP:
            ctx = el.find_parent().get_text(" ", strip=True) if el.find_parent() else ""
            pm = PCT_RX.search(ctx)
            out.append({"code": code, "pct": int(pm.group(1) or pm.group(2)) if pm else None,
                        "brand": brand, "source": "coupon site", "url": url, "seen": now,
                        "votes": 3, "sentiment": sentiment(ctx)})
    text = soup.get_text(" ", strip=True)
    out += [{**c, "brand": brand, "source": "coupon site", "url": url, "seen": now, "votes": 2,
             "sentiment": 0} for c in extract(text)]
    return out


# ── TikTok (experimental) ────────────────────────────────────
def from_tiktok(brand: str, names: list[str], headless: bool = False) -> list[dict]:
    """Reads captions from TikTok's search page. TikTok fights scrapers hard: expect this to
    work in --headful mode on your own laptop, and to sometimes return nothing."""
    from playwright.sync_api import sync_playwright
    q = requests.utils.quote(f"{names[0]} discount code")
    out = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=headless)
        page = b.new_page()
        page.goto(f"https://www.tiktok.com/search/video?q={q}", timeout=45000)
        page.wait_for_timeout(5000)
        for _ in range(4):
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(1200)
        caps = page.eval_on_selector_all(
            "[data-e2e='search-card-video-caption'], [data-e2e='search-card-desc'], a[href*='/video/']",
            "els => els.map(e => [e.innerText, e.closest('a') ? e.closest('a').href : e.href])")
        b.close()
    now = datetime.now(timezone.utc)
    for text, href in caps:
        if not mentions_brand(text, names):
            continue
        for c in extract(text):
            # TikTok search doesn't expose post dates reliably; the video ID encodes it.
            seen = _tiktok_date(href) or now
            out.append({**c, "brand": brand, "source": "tiktok", "url": href, "seen": seen,
                        "votes": 2, "sentiment": sentiment(text)})
    return out


def _tiktok_date(url: str):
    m = re.search(r"/video/(\d{15,})", url or "")
    if not m:
        return None
    return datetime.fromtimestamp(int(m.group(1)) >> 32, tz=timezone.utc)   # top 32 bits = unix time


# ── Web search for TikTok/Instagram code posts ──────────────
def from_web_search(brand: str, names: list[str], days: int) -> list[dict]:
    """Same thing as Googling 'abercrombie discount code tiktok', via an API.

    Search-result snippets for TikTok links usually contain the video caption, which is
    where the code lives. And every TikTok video URL encodes its upload time, so each code
    gets an exact post date even though the search engine doesn't give one.

    Uses Brave Search API if BRAVE_API_KEY is set (most reliable), else DuckDuckGo's HTML page.
    (Google's own Custom Search API closed to new sign-ups in 2026.)
    """
    queries = [f'site:tiktok.com "{names[0]}" discount code',
               f'"{names[0]}" promo code tiktok',
               f'site:instagram.com "{names[0]}" code']
    results = []                                     # (title, snippet, url, date|None)
    key = os.getenv("BRAVE_API_KEY")
    for q in queries:
        if key:
            r = requests.get("https://api.search.brave.com/res/v1/web/search",
                             params={"q": q, "count": 20, "freshness": "pw" if days <= 7 else "pm"},
                             headers={"X-Subscription-Token": key, "Accept": "application/json"}, timeout=15)
            r.raise_for_status()
            for w in r.json().get("web", {}).get("results", []):
                d = None
                if w.get("page_age"):
                    try:
                        d = datetime.fromisoformat(w["page_age"].replace("Z", "+00:00"))
                        d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
                    except ValueError:
                        pass
                results.append((w.get("title", ""), w.get("description", ""), w.get("url", ""), d))
        else:
            r = requests.post("https://html.duckduckgo.com/html/", data={"q": q, "df": "m"},
                              headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
            for res in soup.select(".result"):
                a = res.select_one(".result__a")
                snip = res.select_one(".result__snippet")
                if a:
                    href = a.get("href", "")
                    m = re.search(r"uddg=([^&]+)", href)
                    url = requests.utils.unquote(m.group(1)) if m else href
                    results.append((a.get_text(" ", strip=True), snip.get_text(" ", strip=True) if snip else "", url, None))
        time.sleep(1.5)

    out, now = [], datetime.now(timezone.utc)
    for title, snip, url, d in results:
        text = f"{title} {snip}"
        if not mentions_brand(text + " " + url, names):
            continue
        when = _tiktok_date(url) or d
        src = "tiktok (search)" if "tiktok.com" in url else "instagram (search)" if "instagram.com" in url else "web search"
        for c in extract(text):
            out.append({**c, "brand": brand, "source": src, "url": url,
                        "seen": when or now - timedelta(days=days // 2),   # undated → assume middle-aged
                        "votes": 4 if when else 1, "sentiment": sentiment(text)})
    return out


# ── Email inbox (optional, best for first-to-know codes) ─────
def from_email(brands: dict, days: int) -> list[dict]:
    host, user, pw = os.getenv("CODES_IMAP_HOST", "imap.gmail.com"), os.getenv("CODES_IMAP_USER"), os.getenv("CODES_IMAP_PASS")
    if not (user and pw):
        return []
    out = []
    M = imaplib.IMAP4_SSL(host)
    M.login(user, pw)
    M.select("INBOX")
    since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
    _, ids = M.search(None, f'(SINCE "{since}")')
    for i in ids[0].split()[-300:]:
        _, data = M.fetch(i, "(RFC822)")
        msg = email.message_from_bytes(data[0][1])
        sender, subj = msg.get("From", ""), msg.get("Subject", "")
        body = ""
        for part in msg.walk():
            if part.get_content_type() in ("text/plain", "text/html"):
                try:
                    body += part.get_payload(decode=True).decode(errors="ignore")
                except Exception:
                    pass
        text = subj + " " + BeautifulSoup(body, "html.parser").get_text(" ", strip=True)
        try:
            when = email.utils.parsedate_to_datetime(msg.get("Date"))
        except Exception:
            when = datetime.now(timezone.utc)
        for key, b in brands.items():
            names = [key, *b.get("aliases", [])]
            if mentions_brand(sender + " " + subj, names):
                out += [{**c, "brand": key, "source": "email", "url": f"email: {subj[:60]}",
                         "seen": when, "votes": 30, "sentiment": 1} for c in extract(text)]
    M.logout()
    return out


# ── Ranking ──────────────────────────────────────────────────
def rank(sightings: list[dict], days: int) -> list[dict]:
    """Merge sightings of the same brand+code and give each a 0–100 confidence."""
    now = datetime.now(timezone.utc)
    merged: dict[tuple, dict] = {}
    for s in sightings:
        if (now - s["seen"]).days > days:
            continue
        k = (s["brand"], s["code"])
        m = merged.setdefault(k, {"brand": s["brand"], "code": s["code"], "pct": s["pct"], "sources": set(),
                                  "urls": [], "newest": s["seen"], "votes": 0, "sentiment": 0, "n": 0})
        m["sources"].add(s["source"])
        m["urls"].append(s["url"])
        m["newest"] = max(m["newest"], s["seen"])
        m["votes"] += max(0, s["votes"])
        m["sentiment"] += s["sentiment"]
        m["n"] += 1
        m["pct"] = m["pct"] or s["pct"]
    out = []
    for m in merged.values():
        age = (now - m["newest"]).days
        conf = 45 * max(0, 1 - age / days)                 # recency
        conf += min(20, 7 * (len(m["sources"]) - 1) + 3 * (m["n"] - 1))  # corroboration
        conf += min(20, m["votes"] / 5)                    # upvotes / trust
        conf += max(-40, min(15, 5 * m["sentiment"]))      # worked vs expired
        m["confidence"] = max(0, min(100, round(conf)))
        m["age_days"] = age
        m["sources"] = sorted(m["sources"])
        out.append(m)
    return sorted(out, key=lambda x: (x["brand"], -x["confidence"]))
