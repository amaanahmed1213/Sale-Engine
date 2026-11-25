from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

import requests

from .models import Listing


def line(it: Listing) -> str:
    was = f" (was ${it.original:.0f})" if it.original else ""
    code = f" w/ code {it.code}" if it.code else ""
    return f"[{it.score}] {it.brand_key.title()} — {it.title}: ${it.best_price:.0f}{code}{was} @ {it.source}"


def push_ntfy(topic: str, items: list[Listing]) -> None:
    for it in items[:10]:
        requests.post(
            f"https://ntfy.sh/{topic}",
            data=(f"${it.best_price:.0f}" + (f" with code {it.code}" if it.code else "") + (f" (was ${it.original:.0f})" if it.original else "")
                  + f" @ {it.source}\n" + " · ".join(it.reasons[:3])).encode(),
            headers={"Title": f"{it.brand_key.title()}: {it.title}"[:120],
                     "Click": it.url, "Tags": "shirt", "Priority": "high" if it.score >= 85 else "default"},
            timeout=10,
        )


def email(to: str, items: list[Listing]) -> None:
    host, user, pw = os.getenv("SMTP_HOST"), os.getenv("SMTP_USER"), os.getenv("SMTP_PASS")
    if not (host and user and pw):
        print("  (email skipped: set SMTP_HOST, SMTP_USER, SMTP_PASS)")
        return
    msg = EmailMessage()
    msg["Subject"] = f"{len(items)} good deals found"
    msg["From"], msg["To"] = user, to
    msg.set_content("\n\n".join(f"{line(i)}\n{i.url}" for i in items))
    with smtplib.SMTP_SSL(host, 465) as s:
        s.login(user, pw)
        s.send_message(msg)


def push_codes(topic: str, codes: list[dict]) -> None:
    for c in codes[:8]:
        pct = f"{c['pct']}% off" if c.get("pct") else "discount"
        requests.post(f"https://ntfy.sh/{topic}",
                      data=f"{pct} · seen {c['age_days']}d ago on {', '.join(c['sources'])} · confidence {c['confidence']}".encode(),
                      headers={"Title": f"New code: {c['brand'].title()} {c['code']}", "Click": c["urls"][0],
                               "Tags": "ticket"}, timeout=10)
