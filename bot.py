import os
import time
import json
import signal
import requests
from playwright.sync_api import sync_playwright

# =========================
# TELEGRAM CONFIG
# =========================
# Set these as environment variables (do NOT hardcode them here).
# Locally:   export BOT_TOKEN="..." ; export CHAT_ID="..."
# Railway:   add them under your service's "Variables" tab.
BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=10
        )
        time.sleep(1)  # prevent rate-limit
    except Exception as e:
        print("Telegram error:", e)

# =========================
# FIRSTCRY CONFIG
# =========================
URL = "https://www.firstcry.com/search.aspx?q=hot+wheels"
DATA_FILE = "seen.json"

# =========================
# FILTER LISTS
# =========================
REAL_BRANDS = [
    "ferrari","porsche","mazda","honda","toyota","nissan","bmw",
    "mercedes","audi","volkswagen","vw","ford","chevrolet","chevy",
    "lamborghini","pagani","bugatti","mclaren","aston martin",
    "alfa romeo","subaru","mitsubishi","dodge","jeep","pontiac",
    "volvo","renault","bentley","koenigsegg","jaguar","land rover",
    "maserati","lexus","mini"
]

FANTASY_KEYWORDS = [
    "twin mill","bone shaker","street wiener","pixel shaker",
    "madfast","ain't fare","quick bite","power rocket",
    "layin low","driftn break","cruise bruiser",
    "el viento","feline lucky","shark","dragon","skull",
    "rodger dodger"
]

BIKE_KEYWORDS = [
    "bike","motorcycle","moto","vfr","ducati",
    "kawasaki","yamaha","triumph","harley","motocompo"
]

# =========================
# STORAGE
# =========================
# seen.json format: { href: {"title": ..., "in_stock": bool} }
def load_seen():
    try:
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
    except Exception:
        return {}
    migrated = {}
    for href, val in data.items():
        if isinstance(val, dict):
            migrated[href] = val
        else:
            migrated[href] = {"title": "", "in_stock": False}
    return migrated

def save_seen(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

# =========================
# FILTER LOGIC
# =========================
def is_valid_product(title: str) -> bool:
    t = title.lower()
    if "hot wheels" not in t:
        return False
    if any(x in t for x in FANTASY_KEYWORDS):
        return False
    if any(x in t for x in BIKE_KEYWORDS):
        return False
    if not any(x in t for x in REAL_BRANDS):
        return False
    return True

# =========================
# CORE CHECK
# =========================
def check():
    seen = load_seen()
    first_run = len(seen) == 0
    new_items = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            channel="chromium",
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        page = browser.new_page()
        page.set_default_timeout(30000)
        page.goto(URL, timeout=60000)
        page.wait_for_timeout(8000)

        for _ in range(10):
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(1500)

        raw_links = page.eval_on_selector_all(
            "a[href]",
            "els => els.map(e => ({title: e.getAttribute('title'), href: e.getAttribute('href')}))"
        )
        print("Total links found:", len(raw_links))

        # Step 1: cheap filter in Python - down from thousands of links
        # to just the handful of real Hot Wheels product titles.
        candidates = []
        for link in raw_links:
            title = link["title"]
            href = link["href"]
            if not title or not href:
                continue
            if not is_valid_product(title):
                continue
            if href.startswith("/"):
                href = "https://www.firstcry.com" + href
            candidates.append({"title": title, "href": href})

        print(f"Valid Hot Wheels candidates: {len(candidates)}")

        # Step 2: only for this small candidate list, do the expensive
        # stock-text lookup (walking up parent elements triggers layout
        # reflow, so doing it for thousands of links hung the browser -
        # doing it for a few dozen candidates instead is fast).
        candidate_hrefs = [c["href"] for c in candidates]
        stock_map = page.eval_on_selector_all(
            "a[href]",
            """
            (els, hrefList) => {
                const hrefSet = new Set(hrefList);
                const result = {};
                for (const e of els) {
                    let href = e.getAttribute('href');
                    if (!href) continue;
                    if (href.startsWith('/')) href = 'https://www.firstcry.com' + href;
                    if (!hrefSet.has(href)) continue;
                    let ctx = '';
                    let node = e;
                    for (let i = 0; i < 2 && node; i++) {
                        node = node.parentElement;
                        if (node) ctx += ' ' + node.innerText;
                    }
                    result[href] = ctx.toLowerCase();
                }
                return result;
            }
            """,
            candidate_hrefs
        )
        print("Stock-context lookup done.")

        restocks = []
        new_in_stock = []
        still_out = []

        for c in candidates:
            href = c["href"]
            title = c["title"]
            context = stock_map.get(href, "")
            out_of_stock = "out of stock" in context  # dropped "notify me" - too generic, caused false positives
            in_stock = not out_of_stock
            if out_of_stock:
                still_out.append(title)

            prev = seen.get(href)
            if prev is None:
                seen[href] = {"title": title, "in_stock": in_stock}
                if in_stock and not first_run:
                    new_in_stock.append(f"{title}\n{href}")
            else:
                if in_stock and not prev.get("in_stock", False) and not first_run:
                    restocks.append(f"{title}\n{href}")
                seen[href] = {"title": title, "in_stock": in_stock}

        if still_out:
            print(f"Marked OUT OF STOCK this cycle ({len(still_out)}): {still_out}")

        # Debug: show a snippet of captured context for a few IN-STOCK
        # items, so we can verify (from logs alone) whether the search
        # grid card actually shows "out of stock" text when it should,
        # or whether the detection is missing it.
        sample_in_stock = [c["title"] for c in candidates if not ("out of stock" in stock_map.get(c["href"], ""))][:3]
        for t in sample_in_stock:
            match = next((c for c in candidates if c["title"] == t), None)
            if match:
                snippet = stock_map.get(match["href"], "")[:150]
                print(f"IN-STOCK sample -> {t[:50]} | context snippet: {snippet!r}")

        browser.close()

    save_seen(seen)

    alerts = new_in_stock + restocks
    if first_run:
        print("Baseline saved, no alerts sent.")
    elif alerts:
        send_telegram("🆕 Hot Wheels IN STOCK:\n\n" + "\n\n".join(alerts[:10]))
        print(f"Sent {len(alerts)} alerts ({len(new_in_stock)} new, {len(restocks)} restocked)")
    else:
        print("No new items found")

# =========================
# LOOP
# =========================
class WatchdogTimeout(Exception):
    pass

def _watchdog_handler(signum, frame):
    raise WatchdogTimeout("check() exceeded hard watchdog limit")

signal.signal(signal.SIGALRM, _watchdog_handler)

if __name__ == "__main__":
    send_telegram("🤖 Hot Wheels FirstCry bot STARTED and monitoring")
    while True:
        signal.alarm(90)  # hard cap: force check() to error out if it ever hangs
        try:
            check()
        except WatchdogTimeout as e:
            print("WATCHDOG:", e)
        except Exception as e:
            print("ERROR:", e)
        finally:
            signal.alarm(0)
        time.sleep(120)  # every 2 minutes
