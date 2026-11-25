# Sale Engine

Finds real sales on the brands you wear (lululemon, Vuori, Alo, Rhone, Buck Mason, rag & bone, FRAME, AG, Theory, Vince, Ralph Lauren, J.Crew, Banana Republic, Quince, Abercrombie) across Nordstrom Rack, Gilt, Nordstrom and the brands' own sites. It tracks price history and sends a push to your phone when something is actually worth buying.

## Setup (Mac, about 5 minutes)

```bash
cd sale_engine
python3 -m venv .venv && source .venv/bin/activate
pip install requests beautifulsoup4 playwright
playwright install chromium
python run.py probe        # shows which brand sites are Shopify
python run.py scan         # first full run → opens deals.html
```

Phone alerts: install **ntfy** (iOS/Android), subscribe to a random topic like `amaan-deals-8f3k`, and put that topic in `config.toml` → `[alerts] ntfy_topic`.

## How it decides what counts as a good deal

Every listing has to pass three filters: it's one of your brands, it's something you wear (pants, henleys, long sleeves, jeans), and it isn't excluded (Factory, Lauren Ralph Lauren, women's, and so on). Anything left gets a score from 0 to 100:

| Signal | Why it matters |
|---|---|
| Discount compared with the brand's usual sale | 40% off Banana Republic happens every week. 25% off Quince almost never does. |
| Lowest price we've ever tracked | The most reliable sign of a real deal. It gets stronger after about 2 weeks of daily runs. |
| Fake-MSRP check | If we've never seen an item at its "original" price, the discount gets a penalty (common at Rack). |
| Under your price ceiling | You set these per category in `config.toml`. |
| Fabric | Non-athletic tops in cotton, merino or cashmere get a boost. Tops that are mostly polyester get flagged. |
| Your size in stock | A great deal in a size you can't wear loses points. |

## Commands

```
python run.py scan                     # everything
python run.py scan --only "Rack"       # one source
python run.py scan --headful           # shows the browser (helps if a site blocks headless browsers)
python run.py watch <product-url> 79   # alert me when this drops to $79
python run.py check                    # check your watchlist
python run.py history "ABC"            # price trail
```

## Discount codes

```
python run.py codes            # every brand
python run.py codes abercrombie
```

Where it looks, and how much it trusts each place:

| Source | Notes |
|---|---|
| Reddit (r/frugalmalefashion and others) | Dated and upvoted, and replies saying "expired" lower a code's score. Works without signing up. For more reliable access, create a free "script" app at reddit.com/prefs/apps and set `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET`. |
| Web search: "abercrombie discount code tiktok" | Pulls the codes in TikTok and Instagram captions that show up in search results. Each TikTok link has its posting date built in, so every code gets an exact date. Uses DuckDuckGo for free, or the Brave Search API if you set `BRAVE_API_KEY` (more reliable). |
| Brand homepages | Reads "Use code ___" banners. |
| Coupon sites | Knoji and similar sites often repost codes from TikTok influencers. Add pages in `config.toml`. |
| Email (optional, best) | Make a throwaway Gmail, sign it up for every brand's newsletter, create an app password, then set `CODES_IMAP_USER` / `CODES_IMAP_PASS`. Codes usually show up in email first. |
| TikTok directly (experimental) | Set `tiktok = true` and run with `--headful`. TikTok blocks automated browsing, so this sometimes comes back empty. |

Each code gets a confidence score from 0 to 100 based on how recent it is, how many separate places mention it, upvotes, and whether people say it worked or expired. Codes with a score of 45 or higher are applied automatically to prices on the brand's own site, and the deal page shows the price with the code. They aren't applied at Rack, Gilt or Nordstrom, where brand codes don't work. You'll get a phone alert when a new code with a score of 55 or higher appears. All codes are unverified until you try one at checkout.

## Run it daily automatically (Mac)

`crontab -e`, then add:
```
0 9,19 * * * cd ~/sale_engine && .venv/bin/python run.py codes && .venv/bin/python run.py scan && .venv/bin/python run.py check
```

## When a source returns 0 items

Sites redesign. Open the sale URL, right-click a product tile, choose **Inspect**, then update that source's `card` / `title` / `price` selectors in `config.toml` (or update the URL). Shopify sources basically never break.

## Notes
- Keep it to personal, low-volume use (a couple of runs a day). Big retailers (Rack, Nordstrom, RL) run bot protection and may block you if you hit them hard.
- The scalable, legitimate route is affiliate product feeds (Rakuten, Impact, CJ). Most of these retailers publish full catalogs with sale prices there. It's worth applying once this works for you.
