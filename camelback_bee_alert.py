"""
Camelback Mountain Bee Swarm Alert System v3
---------------------------------------------
- Checks hourly 4:30 AM - 7:00 PM Arizona time
- Only alerts on articles published within the last 24 hours
- Sources: Google News, 12News, FOX10, AZFamily, ABC15, KTAR, AZCentral,
           Phoenix Fire Dept, Reddit
- Pushover push notification only when fresh alert found
"""

import os
import re
import time
import logging
import requests
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import pytz

# ── Pushover credentials ──────────────────────────────────────────────────────
PUSHOVER_USER_TOKEN = os.environ.get("PUSHOVER_USER_TOKEN", "uwa5of3rkvxhs5j7mb5grt2bqetc2r")
PUSHOVER_API_TOKEN  = os.environ.get("PUSHOVER_API_TOKEN",  "ar7bnbugzmy8vzigiogmdzj6xxgm8u")

# ── Schedule ──────────────────────────────────────────────────────────────────
CHECK_INTERVAL_SECONDS = 3600
ARIZONA_TZ  = pytz.timezone("America/Phoenix")
START_HOUR  = 4
START_MIN   = 30   # 4:30 AM
END_HOUR    = 19   # 7:00 PM

# ── How fresh must an article be? ─────────────────────────────────────────────
MAX_ARTICLE_AGE_HOURS = 24

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

SEARCH_QUERIES = [
    "Camelback Mountain bee swarm warning",
    "Camelback Mountain bee attack hiker",
    "echo canyon trail bee swarm",
    "cholla trail camelback bees",
    "Phoenix fire department bee swarm Camelback",
    "Phoenix Arizona bee swarm trail warning",
    "Camelback Mountain hiking bee alert",
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
HEADERS = {"User-Agent": "CamelbackBeeAlert/3.0 (personal safety monitor)"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_operating_hours() -> bool:
    now = datetime.now(ARIZONA_TZ)
    after_start = (now.hour > START_HOUR) or (now.hour == START_HOUR and now.minute >= START_MIN)
    before_end  = now.hour < END_HOUR
    return after_start and before_end


def is_fresh(pub_date_str: str) -> bool:
    """Return True if the article was published within MAX_ARTICLE_AGE_HOURS."""
    if not pub_date_str:
        return True  # if no date, don't filter it out
    try:
        pub_dt = parsedate_to_datetime(pub_date_str)
        # Make sure it's timezone-aware
        if pub_dt.tzinfo is None:
            pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - pub_dt
        return age <= timedelta(hours=MAX_ARTICLE_AGE_HOURS)
    except Exception:
        return True  # if we can't parse the date, include it


def contains_bee_alert(text: str) -> bool:
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

        # Parse items including pubDate
        items = []
        entries = re.findall(r"<item>(.*?)</item>", r.text, re.DOTALL)
        for entry in entries[:5]:
            title    = re.search(r"<title>(.*?)</title>", entry)
            desc     = re.search(r"<description>(.*?)</description>", entry, re.DOTALL)
            pub_date = re.search(r"<pubDate>(.*?)</pubDate>", entry)
            t = strip_html(title.group(1)) if title else ""
            d = strip_html(desc.group(1))[:300] if desc else ""
            p = pub_date.group(1).strip() if pub_date else ""
            if is_fresh(p):
                items.append({"title": t, "snippet": d, "source": "Google News", "pubDate": p})
            else:
                log.info(f"  ⏰ Skipping old article: {t[:60]} ({p})")
        return items
    except Exception as e:
        log.warning(f"Google News error: {e}")
        return []


# ── Source 2: Local Phoenix news RSS ─────────────────────────────────────────

def check_local_news_rss() -> list:
    results = []
    for feed_url in LOCAL_NEWS_RSS:
        try:
            r = requests.get(feed_url, timeout=15, headers=HEADERS)
            source = feed_url.split("/")[2].replace("www.", "").split(".")[0].upper()
            entries = re.findall(r"<item>(.*?)</item>", r.text, re.DOTALL)
            for entry in entries[:10]:
                title    = re.search(r"<title>(.*?)</title>", entry)
                desc     = re.search(r"<description>(.*?)</description>", entry, re.DOTALL)
                pub_date = re.search(r"<pubDate>(.*?)</pubDate>", entry)
                t = strip_html(title.group(1)) if title else ""
                d = strip_html(desc.group(1))[:300] if desc else ""
                p = pub_date.group(1).strip() if pub_date else ""
                if is_fresh(p):
                    results.append({"title": t, "snippet": d, "source": source, "pubDate": p})
        except Exception as e:
            log.warning(f"RSS error ({feed_url}): {e}")
    return results


# ── Source 3: Phoenix Fire Dept newsroom ──────────────────────────────────────

def check_phoenix_fire_newsroom() -> list:
    try:
        r = requests.get(
            "https://www.phoenix.gov/newsroom/fire-news.html",
            timeout=15, headers=HEADERS
        )
        text   = strip_html(r.text)
        chunks = [text[i:i+200] for i in range(0, len(text), 150)]
        hits   = []
        for chunk in chunks:
            if any(kw in chunk.lower() for kw in ["bee", "swarm", "sting"]):
                hits.append({
                    "title":   "Phoenix Fire Dept Newsroom",
                    "snippet": chunk.strip(),
                    "source":  "Phoenix Fire Dept",
                    "pubDate": ""
                })
        return hits[:3]
    except Exception as e:
        log.warning(f"Phoenix Fire error: {e}")
        return []


# ── Source 4: Reddit ──────────────────────────────────────────────────────────

def reddit_search(query: str, subreddit: str = "") -> list:
    try:
        sub = f"r/{subreddit}/" if subreddit else ""
        url = (f"https://www.reddit.com/{sub}search.json"
               f"?q={requests.utils.quote(query)}&sort=new&limit=5"
               f"&restrict_sr={'true' if subreddit else 'false'}")
        r   = requests.get(url, timeout=15, headers=HEADERS)
        posts = r.json().get("data", {}).get("children", [])
        results = []
        for p in posts:
            created = p["data"].get("created_utc", 0)
            pub_dt  = datetime.fromtimestamp(created, tz=timezone.utc)
            age     = datetime.now(timezone.utc) - pub_dt
            if age <= timedelta(hours=MAX_ARTICLE_AGE_HOURS):
                results.append({
                    "title":   p["data"]["title"],
                    "snippet": p["data"].get("selftext", "")[:300],
                    "source":  f"Reddit/{subreddit or 'all'}",
                    "pubDate": pub_dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
                })
            else:
                log.info(f"  ⏰ Skipping old Reddit post: {p['data']['title'][:60]}")
        return results
    except Exception as e:
        log.warning(f"Reddit error: {e}")
        return []


# ── Master check ──────────────────────────────────────────────────────────────

def check_all_sources() -> list:
    alerts = []

    log.info("  Checking Google News (fresh only)...")
    for query in SEARCH_QUERIES:
        for item in google_news_search(query):
            combined = f"{item['title']} {item['snippet']}"
            if contains_bee_alert(combined):
                alerts.append(f"📰 {item['source']}: {item['title'].strip()}")

    log.info("  Checking local Phoenix RSS feeds (fresh only)...")
    for item in check_local_news_rss():
        combined = f"{item['title']} {item['snippet']}"
        if contains_bee_alert(combined):
            alerts.append(f"📺 {item['source']}: {item['title'].strip()}")

    log.info("  Checking Phoenix Fire Dept newsroom...")
    for item in check_phoenix_fire_newsroom():
        combined = f"{item['title']} {item['snippet']}"
        if contains_bee_alert(combined):
            alerts.append(f"🚒 Phoenix Fire: {item['snippet'][:100].strip()}")

    log.info("  Checking Reddit (fresh only)...")
    for query, sub in REDDIT_QUERIES:
        for item in reddit_search(query, sub):
            combined = f"{item['title']} {item['snippet']}"
            if contains_bee_alert(combined):
                alerts.append(f"👥 Reddit r/{sub}: {item['title'].strip()}")

    return list(dict.fromkeys(alerts))


# ── Pushover ──────────────────────────────────────────────────────────────────

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


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    log.info("🐝 Camelback Bee Alert System v3 started.")
    log.info(f"   Hours: {START_HOUR}:{START_MIN:02d} AM – {END_HOUR}:00 PM Arizona time")
    log.info(f"   Freshness filter: last {MAX_ARTICLE_AGE_HOURS} hours only")

    send_pushover(
        "🐝 Bee Alert System v3 Live!",
        f"Camelback Mountain monitor running.\n"
        f"✅ Fresh news only (last {MAX_ARTICLE_AGE_HOURS} hours)\n"
        f"✅ Hours: 4:30 AM – 7:00 PM AZ time\n"
        f"Silent unless there's a real alert. Stay safe! 🏔️"
    )

    already_alerted: set = set()

    while True:
        now_az = datetime.now(ARIZONA_TZ)

        if is_operating_hours():
            log.info(f"🔎 Checking at {now_az.strftime('%I:%M %p')} AZ time...")
            alerts = check_all_sources()

            if alerts:
                new_alerts = [a for a in alerts if a not in already_alerted]
                if new_alerts:
                    message = (
                        "⚠️ FRESH bee swarm activity detected near Camelback!\n\n"
                        + "\n".join(new_alerts[:6])
                        + "\n\nCheck trail conditions before heading out! 🏔️"
                    )
                    log.info(f"🚨 Fresh alert found!\n{message}")
                    if send_pushover("⚠️ BEE ALERT — Camelback Mtn", message):
                        already_alerted.update(new_alerts)
                else:
                    log.info("ℹ️  Already notified. No duplicate push.")
            else:
                log.info("✅ All clear — no fresh bee swarm alerts found.")
        else:
            log.info(f"😴 Outside hours ({now_az.strftime('%I:%M %p')} AZ). Sleeping...")
            if now_az.hour == 0:
                already_alerted.clear()
                log.info("🔄 Midnight reset.")

        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
