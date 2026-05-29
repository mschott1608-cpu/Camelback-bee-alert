"""
Camelback Mountain Bee Swarm Alert System
------------------------------------------
Searches multiple sources hourly (4 AM - 7 PM Arizona time):
  - Google News RSS
  - Reddit (r/phoenix, r/arizona, r/hiking)
  - Phoenix Fire Department newsroom
  - Local TV news: 12News, FOX 10, AZFamily, ABC15, KTAR
  - Twitter/X via search (no API key needed)

Sends a Pushover push notification to Mike's iPhone ONLY when an alert
is found. Silent when all is clear.

Deploy on Railway.app (free tier) for 24/7 operation.
"""

import os
import re
import time
import logging
import requests
from datetime import datetime
import pytz

# ── Pushover credentials ──────────────────────────────────────────────────────
PUSHOVER_USER_TOKEN = os.environ.get("PUSHOVER_USER_TOKEN", "uwa5of3rkvxhs5j7mb5grt2bqetc2r")
PUSHOVER_API_TOKEN  = os.environ.get("PUSHOVER_API_TOKEN",  "ar7bnbugzmy8vzigiogmdzj6xxgm8u")

# ── Schedule ──────────────────────────────────────────────────────────────────
CHECK_INTERVAL_SECONDS = 3600
ARIZONA_TZ = pytz.timezone("America/Phoenix")
START_HOUR = 4
END_HOUR   = 19

# ── Keywords ──────────────────────────────────────────────────────────────────
BEE_KEYWORDS = [
    "bee swarm", "bee attack", "africanized", "bee hive", "beehive",
    "bee warning", "bee alert", "stung by bees", "bees attacking",
    "wasp swarm", "bee rescue", "bee incident", "bee sting", "bee swarm warning",
    "aggressive bees", "bees on trail"
]
LOCATION_KEYWORDS = [
    "camelback", "echo canyon", "cholla trail", "camelback mountain",
    "phoenix mountain", "scottsdale mountain", "phoenix hike", "arizona hike",
    "phoenix trail", "scottsdale trail"
]

# ── Google News search queries ────────────────────────────────────────────────
SEARCH_QUERIES = [
    "Camelback Mountain bee swarm warning 2025",
    "Camelback Mountain bee attack hiker",
    "echo canyon trail bee swarm",
    "cholla trail camelback bees",
    "Phoenix fire department bee swarm Camelback",
    "Phoenix Arizona bee swarm trail warning",
    "Camelback Mountain hiking bee alert",
]

# ── Local news RSS feeds (Phoenix area) ──────────────────────────────────────
LOCAL_NEWS_RSS = [
    # 12News (KPNX NBC)
    "https://www.12news.com/feeds/syndication/rss/news/local/",
    # AZFamily (CBS 5)
    "https://www.azfamily.com/arc/outboundfeeds/rss/?outputType=xml",
    # FOX 10 Phoenix
    "https://www.fox10phoenix.com/rss/category/news",
    # ABC15 Arizona
    "https://www.abc15.com/rss/category/news/local-news",
    # KTAR News
    "https://ktar.com/feed/",
    # Arizona Republic / AZCentral
    "https://rssfeeds.azcentral.com/rss/mggazcentral",
    # Phoenix Fire Dept newsroom
    "https://www.phoenix.gov/newsroom/fire-news.html",
]

# ── Reddit communities to check ───────────────────────────────────────────────
REDDIT_QUERIES = [
    ("Camelback Mountain bees",     "phoenix"),
    ("camelback bee swarm",         "arizona"),
    ("camelback bee attack",        "hiking"),
    ("bee swarm camelback trail",   "phoenix"),
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "CamelbackBeeAlert/2.0 (personal safety monitor)"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_operating_hours() -> bool:
    now = datetime.now(ARIZONA_TZ)
    return START_HOUR <= now.hour < END_HOUR


def contains_bee_alert(text: str) -> bool:
    """Return True only if text has BOTH a bee keyword AND a location keyword."""
    t = text.lower()
    return any(kw in t for kw in BEE_KEYWORDS) and any(kw in t for kw in LOCATION_KEYWORDS)


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text)


# ── Source 1: Google News RSS ─────────────────────────────────────────────────

def google_news_search(query: str) -> list:
    try:
        url = (f"https://news.google.com/rss/search"
               f"?q={requests.utils.quote(query)}&hl=en-US&gl=US&ceid=US:en")
        r = requests.get(url, timeout=15, headers=HEADERS)
        titles   = re.findall(r"<title>(.*?)</title>", r.text)
        snippets = re.findall(r"<description>(.*?)</description>", r.text, re.DOTALL)
        return [
            {"title": strip_html(t), "snippet": strip_html(s)[:300], "source": "Google News"}
            for t, s in zip(titles[2:], snippets[2:])
        ][:5]
    except Exception as e:
        log.warning(f"Google News error ({query}): {e}")
        return []


# ── Source 2: Local Phoenix news RSS feeds ────────────────────────────────────

def check_local_news_rss() -> list:
    results = []
    for feed_url in LOCAL_NEWS_RSS:
        try:
            r = requests.get(feed_url, timeout=15, headers=HEADERS)
            titles      = re.findall(r"<title>(.*?)</title>", r.text)
            descriptions = re.findall(r"<description>(.*?)</description>", r.text, re.DOTALL)
            # Derive a short source name from the URL
            source = feed_url.split("/")[2].replace("www.", "").split(".")[0].upper()
            for t, d in zip(titles[1:], descriptions[1:]):
                results.append({
                    "title":   strip_html(t),
                    "snippet": strip_html(d)[:300],
                    "source":  source
                })
        except Exception as e:
            log.warning(f"RSS error ({feed_url}): {e}")
    return results


# ── Source 3: Phoenix Fire Department newsroom (direct page scrape) ───────────

def check_phoenix_fire_newsroom() -> list:
    try:
        r = requests.get(
            "https://www.phoenix.gov/newsroom/fire-news.html",
            timeout=15, headers=HEADERS
        )
        # Grab all visible text snippets
        text = strip_html(r.text)
        # Split into rough chunks and look for bee content
        chunks = [text[i:i+200] for i in range(0, len(text), 150)]
        hits = []
        for chunk in chunks:
            if any(kw in chunk.lower() for kw in ["bee", "swarm", "sting"]):
                hits.append({
                    "title":   "Phoenix Fire Dept Newsroom",
                    "snippet": chunk.strip(),
                    "source":  "Phoenix Fire Dept"
                })
        return hits[:3]
    except Exception as e:
        log.warning(f"Phoenix Fire newsroom error: {e}")
        return []


# ── Source 4: Reddit ──────────────────────────────────────────────────────────

def reddit_search(query: str, subreddit: str = "") -> list:
    try:
        sub = f"r/{subreddit}/" if subreddit else ""
        url = (f"https://www.reddit.com/{sub}search.json"
               f"?q={requests.utils.quote(query)}&sort=new&limit=5&restrict_sr={'true' if subreddit else 'false'}")
        r = requests.get(url, timeout=15, headers=HEADERS)
        posts = r.json().get("data", {}).get("children", [])
        return [
            {
                "title":   p["data"]["title"],
                "snippet": p["data"].get("selftext", "")[:300],
                "source":  f"Reddit/{subreddit or 'all'}"
            }
            for p in posts
        ]
    except Exception as e:
        log.warning(f"Reddit error ({query}): {e}")
        return []


# ── Master check ──────────────────────────────────────────────────────────────

def check_all_sources() -> list:
    alerts = []

    # 1. Google News
    log.info("  Checking Google News...")
    for query in SEARCH_QUERIES:
        for item in google_news_search(query):
            combined = f"{item['title']} {item['snippet']}"
            if contains_bee_alert(combined):
                alerts.append(f"📰 {item['source']}: {item['title'].strip()}")

    # 2. Local Phoenix news RSS
    log.info("  Checking local Phoenix news RSS feeds...")
    for item in check_local_news_rss():
        combined = f"{item['title']} {item['snippet']}"
        if contains_bee_alert(combined):
            alerts.append(f"📺 {item['source']}: {item['title'].strip()}")

    # 3. Phoenix Fire Department newsroom
    log.info("  Checking Phoenix Fire Dept newsroom...")
    for item in check_phoenix_fire_newsroom():
        combined = f"{item['title']} {item['snippet']}"
        if contains_bee_alert(combined):
            alerts.append(f"🚒 Phoenix Fire: {item['snippet'][:100].strip()}")

    # 4. Reddit
    log.info("  Checking Reddit...")
    for query, sub in REDDIT_QUERIES:
        for item in reddit_search(query, sub):
            combined = f"{item['title']} {item['snippet']}"
            if contains_bee_alert(combined):
                alerts.append(f"👥 Reddit r/{sub}: {item['title'].strip()}")

    return list(dict.fromkeys(alerts))  # deduplicate, preserve order


# ── Pushover notification ─────────────────────────────────────────────────────

def send_pushover(title: str, message: str) -> bool:
    try:
        r = requests.post(
            "https://api.pushover.net/1/messages.json",
            data={
                "token":    PUSHOVER_API_TOKEN,
                "user":     PUSHOVER_USER_TOKEN,
                "title":    title,
                "message":  message,
                "priority": 1,       # high priority — bypasses quiet hours
                "sound":    "siren", # loud siren alert
            },
            timeout=15
        )
        if r.status_code == 200:
            log.info("✅ Pushover notification sent.")
            return True
        else:
            log.error(f"Pushover error {r.status_code}: {r.text}")
            return False
    except Exception as e:
        log.error(f"Pushover send failed: {e}")
        return False


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    log.info("🐝 Camelback Bee Alert System v2 started.")
    log.info(f"   Sources: Google News, 12News, FOX10, AZFamily, ABC15, KTAR, AZCentral, Phoenix Fire Dept, Reddit")
    log.info(f"   Schedule: {START_HOUR}:00 AM – {END_HOUR}:00 PM Arizona time, every hour")

    # Startup confirmation push
    send_pushover(
        "🐝 Bee Alert System Live!",
        "Camelback Mountain bee swarm monitor is now running.\n"
        "Watching: Google News, 12News, FOX10, AZFamily, ABC15, KTAR, "
        "AZCentral, Phoenix Fire Dept & Reddit.\n\n"
        "You'll only hear from me if there's an alert. Stay safe! 🏔️"
    )

    already_alerted: set = set()

    while True:
        now_az = datetime.now(ARIZONA_TZ)

        if is_operating_hours():
            log.info(f"🔎 Running full check at {now_az.strftime('%I:%M %p')} AZ time...")
            alerts = check_all_sources()

            if alerts:
                new_alerts = [a for a in alerts if a not in already_alerted]
                if new_alerts:
                    message = (
                        "⚠️ Bee swarm activity detected near Camelback Mountain!\n\n"
                        + "\n".join(new_alerts[:6])
                        + "\n\nCheck trail conditions before heading out! 🏔️"
                    )
                    log.info(f"🚨 New alert found!\n{message}")
                    if send_pushover("⚠️ BEE ALERT — Camelback Mtn", message):
                        already_alerted.update(new_alerts)
                else:
                    log.info("ℹ️  Already notified about these alerts. No duplicate push.")
            else:
                log.info("✅ All clear — no bee swarm alerts found across any source.")

        else:
            log.info(f"😴 Outside hours ({now_az.strftime('%I:%M %p')} AZ). Sleeping...")
            if now_az.hour == 0:
                already_alerted.clear()
                log.info("🔄 Midnight reset — daily alert history cleared.")

        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
