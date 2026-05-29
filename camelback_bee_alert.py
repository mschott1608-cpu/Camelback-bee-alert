"""
Camelback Mountain Bee Swarm Alert System
------------------------------------------
Searches multiple sources hourly (4 AM - 7 PM Arizona time).
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

# ── TEST MODE — set to False after test is confirmed ─────────────────────────
TEST_MODE = False

# ── Schedule ──────────────────────────────────────────────────────────────────
CHECK_INTERVAL_SECONDS = 3600
ARIZONA_TZ = pytz.timezone("America/Phoenix")
START_HOUR = 4
END_HOUR   = 19

# ── Keywords ──────────────────────────────────────────────────────────────────
BEE_KEYWORDS = [
    "bee swarm", "bee attack", "africanized", "bee hive", "beehive",
    "bee warning", "bee alert", "stung by bees", "bees attacking",
    "wasp swarm", "bee rescue", "bee incident", "bee sting",
    "aggressive bees", "bees on trail"
]
LOCATION_KEYWORDS = [
    "camelback", "echo canyon", "cholla trail", "camelback mountain",
    "phoenix mountain", "scottsdale mountain", "phoenix hike", "arizona hike",
    "phoenix trail", "scottsdale trail"
]

# ── Test keywords (guaranteed to find something) ──────────────────────────────
TEST_BEE_KEYWORDS      = ["weather", "news", "arizona", "phoenix", "fire"]
TEST_LOCATION_KEYWORDS = ["phoenix", "arizona", "scottsdale"]

SEARCH_QUERIES = [
    "Camelback Mountain bee swarm warning 2025",
    "Camelback Mountain bee attack hiker",
    "echo canyon trail bee swarm",
    "cholla trail camelback bees",
    "Phoenix fire department bee swarm Camelback",
    "Phoenix Arizona bee swarm trail warning",
    "Camelback Mountain hiking bee alert",
]

TEST_SEARCH_QUERIES = [
    "Phoenix Arizona news today",
]

LOCAL_NEWS_RSS = [
    "https://www.12news.com/feeds/syndication/rss/news/local/",
    "https://www.azfamily.com/arc/outboundfeeds/rss/?outputType=xml",
    "https://www.fox10phoenix.com/rss/category/news",
    "https://www.abc15.com/rss/category/news/local-news",
    "https://ktar.com/feed/",
    "https://rssfeeds.azcentral.com/rss/mggazcentral",
]

REDDIT_QUERIES = [
    ("Camelback Mountain bees", "phoenix"),
    ("camelback bee swarm",     "arizona"),
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "CamelbackBeeAlert/2.0 (personal safety monitor)"}


def is_operating_hours() -> bool:
    now = datetime.now(ARIZONA_TZ)
    return START_HOUR <= now.hour < END_HOUR


def contains_alert(text: str, bee_kws: list, loc_kws: list) -> bool:
    t = text.lower()
    return any(kw in t for kw in bee_kws) and any(kw in t for kw in loc_kws)


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text)


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
        log.warning(f"Google News error: {e}")
        return []


def check_local_news_rss() -> list:
    results = []
    for feed_url in LOCAL_NEWS_RSS:
        try:
            r = requests.get(feed_url, timeout=15, headers=HEADERS)
            titles       = re.findall(r"<title>(.*?)</title>", r.text)
            descriptions = re.findall(r"<description>(.*?)</description>", r.text, re.DOTALL)
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


def reddit_search(query: str, subreddit: str = "") -> list:
    try:
        sub = f"r/{subreddit}/" if subreddit else ""
        url = (f"https://www.reddit.com/{sub}search.json"
               f"?q={requests.utils.quote(query)}&sort=new&limit=5"
               f"&restrict_sr={'true' if subreddit else 'false'}")
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
        log.warning(f"Reddit error: {e}")
        return []


def check_all_sources(test_mode: bool = False) -> list:
    bee_kws = TEST_BEE_KEYWORDS      if test_mode else BEE_KEYWORDS
    loc_kws = TEST_LOCATION_KEYWORDS if test_mode else LOCATION_KEYWORDS
    queries = TEST_SEARCH_QUERIES    if test_mode else SEARCH_QUERIES

    alerts = []

    log.info("  Checking Google News...")
    for query in queries:
        for item in google_news_search(query):
            combined = f"{item['title']} {item['snippet']}"
            if contains_alert(combined, bee_kws, loc_kws):
                alerts.append(f"📰 {item['source']}: {item['title'].strip()}")

    log.info("  Checking local Phoenix news RSS...")
    for item in check_local_news_rss():
        combined = f"{item['title']} {item['snippet']}"
        if contains_alert(combined, bee_kws, loc_kws):
            alerts.append(f"📺 {item['source']}: {item['title'].strip()}")

    if not test_mode:
        log.info("  Checking Reddit...")
        for query, sub in REDDIT_QUERIES:
            for item in reddit_search(query, sub):
                combined = f"{item['title']} {item['snippet']}"
                if contains_alert(combined, bee_kws, loc_kws):
                    alerts.append(f"👥 Reddit r/{sub}: {item['title'].strip()}")

    return list(dict.fromkeys(alerts))


def send_pushover(title: str, message: str) -> bool:
    try:
        r = requests.post(
            "https://api.pushover.net/1/messages.json",
            data={
                "token":    PUSHOVER_API_TOKEN,
                "user":     PUSHOVER_USER_TOKEN,
                "title":    title,
                "message":  message,
                "priority": 1,
                "sound":    "siren",
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


def main():
    log.info("🐝 Camelback Bee Alert System started.")

    if TEST_MODE:
        log.info("🧪 TEST MODE ACTIVE — using broad keywords to verify pipeline...")
        send_pushover(
            "🧪 TEST MODE — System Check",
            "Running a test scan with broad keywords to verify the full pipeline works. "
            "If you get an alert in the next minute, everything is working perfectly!"
        )
        alerts = check_all_sources(test_mode=True)
        if alerts:
            message = (
                "✅ TEST SUCCESSFUL! Pipeline works end-to-end.\n\n"
                "Sample matches found:\n"
                + "\n".join(alerts[:4])
                + "\n\n⚠️ This was a TEST. No real bee swarm detected."
            )
            log.info(f"🧪 Test alerts found: {alerts[:4]}")
            send_pushover("✅ TEST PASSED — Bee Alert Works!", message)
        else:
            send_pushover(
                "⚠️ TEST — No matches found",
                "The test scan didn't find matches. Check Railway logs for details."
            )
        log.info("🧪 Test complete. Switching to normal monitoring mode...")

    already_alerted: set = set()

    while True:
        now_az = datetime.now(ARIZONA_TZ)

        if is_operating_hours():
            log.info(f"🔎 Checking at {now_az.strftime('%I:%M %p')} AZ time...")
            alerts = check_all_sources(test_mode=False)

            if alerts:
                new_alerts = [a for a in alerts if a not in already_alerted]
                if new_alerts:
                    message = (
                        "⚠️ Bee swarm activity detected near Camelback Mountain!\n\n"
                        + "\n".join(new_alerts[:6])
                        + "\n\nCheck trail conditions before heading out! 🏔️"
                    )
                    log.info(f"🚨 Alert found!\n{message}")
                    if send_pushover("⚠️ BEE ALERT — Camelback Mtn", message):
                        already_alerted.update(new_alerts)
                else:
                    log.info("ℹ️  Already notified. No duplicate push.")
            else:
                log.info("✅ All clear — no bee swarm alerts found.")
        else:
            log.info(f"😴 Outside hours ({now_az.strftime('%I:%M %p')} AZ). Sleeping...")
            if now_az.hour == 0:
                already_alerted.clear()

        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
