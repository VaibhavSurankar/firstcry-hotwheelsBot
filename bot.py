import os
import time
import json
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

# Note: FirstCry's search page does not appear to accept a pincode
# parameter to filter results by local availability/delivery. This
# bot alerts on new listings appearing in search overall, not on
# stock specifically at pincode 500056. If you want delivery-at-pincode
# checks, that would need per-product page scraping (each product page
# has a pincode-check widget) - let me know if you want that added.

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
def load_seen():
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

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
            channel="chromium",  # use the full Chromium build, avoid the separate headless-shell binary
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        page = browser.new_page()
        page.goto(URL, timeout=60000)
        page.wait_for_timeout(8000)

        # scroll to load more products
        for _ in range(10):
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(1500)

        links = page.query_selector_all("a[href]")
        print("Total links found:", len(links))

        for a in links:
            title = a.get_attribute("title")
            href = a.get_attribute("href")
            if not title or not href:
                continue
            if not is_valid_product(title):
                continue
            if href.startswith("/"):
                href = "https://www.firstcry.com" + href
            if href not in seen:
                seen[href] = True
                if not first_run:
                    new_items.append(f"{title}\n{href}")

        browser.close()

    save_seen(seen)

    if first_run:
        print("Baseline saved, no alerts sent.")
    elif new_items:
        send_telegram("🆕 NEW Hot Wheels detected:\n\n" + "\n\n".join(new_items[:10]))
        print(f"Sent {len(new_items)} new alerts")
    else:
        print("No new items found")

# =========================
# LOOP
# =========================
if __name__ == "__main__":
    send_telegram("🤖 Hot Wheels FirstCry bot STARTED and monitoring")
    while True:
        try:
            check()
        except Exception as e:
            print("ERROR:", e)
        time.sleep(120)  # every 2 minutes
