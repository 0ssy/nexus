"""
GDELT Collector
Collects global business news signals from the GDELT Project.
Completely free, no API key, real-time global coverage.

GDELT monitors news from every country in 65 languages.
We use it to find:
- Business fraud mentions
- Insolvency and bankruptcy news
- Late payment disputes
- Supplier reliability issues
- Market disruptions

API docs: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
"""

import requests
import asyncio
import time
from datetime import datetime, timezone
from trust.database import (
    insert_business, insert_signal,
    get_signal_weight, get_database_stats
)

BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

HEADERS = {
    "User-Agent": "NexusTrustLayer/1.0 (business intelligence research)",
    "Accept": "application/json"
}

# Search queries targeting business trust signals
SEARCH_QUERIES = [
    # Negative signals — high value
    ("business fraud supplier", "fraud_allegation", "negative"),
    ("company insolvency bankruptcy", "insolvency_notice", "negative"),
    ("supplier default payment", "default_report", "negative"),
    ("wholesale fraud scam", "fraud_allegation", "negative"),
    ("business liquidation closure", "dissolution_notice", "negative"),
    ("late payment dispute supplier", "late_payment_report", "negative"),
    ("trading company fraud", "fraud_allegation", "negative"),
    ("logistics company failure", "dissolution_notice", "negative"),

    # Market signals — neutral/informational
    ("commodity price increase wholesale", "negative_news", "neutral"),
    ("supply chain disruption", "negative_news", "neutral"),
    ("trade credit tightening", "negative_news", "neutral"),
]

# Countries to focus on — global coverage
COUNTRIES = [
    "Kenya", "Nigeria", "Ghana", "South Africa",
    "United Kingdom", "India", "Indonesia",
    "Brazil", "Mexico", "Pakistan",
    "Philippines", "Vietnam", "Bangladesh"
]

def search_gdelt(query: str, country: str = None, max_records: int = 10) -> dict:
    """Search GDELT for news articles matching query."""
    full_query = query
    if country:
        full_query = f"{query} {country}"

    params = {
        "query": full_query,
        "mode": "artlist",
        "maxrecords": max_records,
        "format": "json",
        "timespan": "7d",
        "sort": "datedesc"
    }

    for attempt in range(3):  # retry up to 3 times
        try:
            resp = requests.get(
                BASE_URL,
                params=params,
                headers=HEADERS,
                timeout=30,
                allow_redirects=True
            )
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 429:
                print(f"    [RATE LIMIT] Waiting 60 seconds...")
                time.sleep(60)
            else:
                print(f"    [WARNING] GDELT returned {resp.status_code}")
                return {}
        except requests.exceptions.Timeout:
            print(f"    [TIMEOUT] Attempt {attempt+1}/3 timed out, retrying...")
            time.sleep(5)
        except Exception as e:
            print(f"    [ERROR] GDELT search failed: {e}")
            return {}

    return {}

# Known non-business words to filter out
NON_BUSINESS_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
    "for", "of", "with", "by", "from", "up", "about", "into", "through",
    "after", "before", "since", "during", "including", "until", "against",
    "among", "throughout", "despite", "towards", "upon", "concerning",
    "says", "said", "says", "report", "reports", "new", "year", "years",
    "billion", "million", "deal", "sold", "sell", "buy", "buying",
    "selling", "plan", "plans", "monday", "tuesday", "wednesday",
    "thursday", "friday", "saturday", "sunday", "january", "february",
    "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december"
}

# Known company suffixes that confirm something is a business name
COMPANY_SUFFIXES = {
    "ltd", "limited", "inc", "incorporated", "corp", "corporation",
    "llc", "plc", "gmbh", "sa", "ag", "bv", "nv", "pty",
    "group", "holdings", "enterprises", "industries", "international",
    "company", "co", "partners", "associates", "services", "solutions",
    "technologies", "tech", "logistics", "trading", "wholesale",
    "distribution", "supply", "supplies", "brands", "ventures"
}

def extract_business_name(title: str, query: str) -> str:
    """
    Extract a real business name from an article title.
    Returns None if no confident business name found.
    """
    if not title or len(title) < 5:
        return None

    # Skip non-Latin titles (Arabic, Chinese, etc.) — can't reliably extract
    non_latin = sum(1 for c in title if ord(c) > 127)
    if non_latin > len(title) * 0.3:
        return None

    words = title.split()
    if not words:
        return None

    # Strategy 1: Look for known company suffix
    title_lower = title.lower()
    for suffix in COMPANY_SUFFIXES:
        if f" {suffix}" in title_lower or f" {suffix}." in title_lower:
            # Find the company name ending with this suffix
            for i, word in enumerate(words):
                if word.lower().rstrip(".,") == suffix:
                    # Take up to 4 words before the suffix
                    start = max(0, i - 4)
                    candidate = " ".join(words[start:i+1])
                    if len(candidate) > 3:
                        return candidate.strip(".,")

    # Strategy 2: Look for capitalized sequences of 2-4 words
    candidates = []
    current = []
    for word in words:
        clean = word.strip(".,!?\"'()")
        if (clean and
            clean[0].isupper() and
            clean.lower() not in NON_BUSINESS_WORDS and
            len(clean) > 1 and
            clean.isascii()):
            current.append(clean)
        else:
            if len(current) >= 2:
                candidates.append(" ".join(current))
            current = []
    if len(current) >= 2:
        candidates.append(" ".join(current))

    if candidates:
        # Prefer longer candidates (more specific company names)
        best = max(candidates, key=len)
        # Reject if too long (likely a sentence fragment)
        if len(best.split()) <= 5:
            return best

    # Strategy 3: Single prominent capitalized word (known brands)
    for word in words:
        clean = word.strip(".,!?\"'()")
        if (clean and
            clean[0].isupper() and
            len(clean) > 3 and
            clean.lower() not in NON_BUSINESS_WORDS and
            clean.isascii() and
            clean.isupper() is False):  # skip ALL CAPS words
            return clean

    return None

def extract_country_from_article(article: dict, default_country: str) -> str:
    """Extract country from article metadata."""
    # GDELT provides domain and source country
    source_country = article.get("sourcecountry", "")
    if source_country:
        return source_country.strip()
    return default_country

async def process_article(
    article: dict,
    signal_type: str,
    signal_category: str,
    country: str
) -> bool:
    """Process a single GDELT article into a business signal."""
    title = article.get("title", "").strip()
    url = article.get("url", "")
    seendate = article.get("seendate", "")

    if not title or len(title) < 10:
        return False

    # Extract business name — skip article if no name found
    business_name = extract_business_name(title, "")
    if not business_name:
        return False  # skip articles where we can't identify a business

    article_country = extract_country_from_article(article, country)

    try:
        # Parse article date
        signal_date = datetime.now(timezone.utc)
        if seendate:
            try:
                parsed = datetime.strptime(seendate, "%Y%m%dT%H%M%SZ")
                signal_date = parsed.replace(tzinfo=timezone.utc)
            except:
                signal_date = datetime.now(timezone.utc)

        # Insert business
        business_id = await insert_business(
            name=business_name,
            country=article_country,
            source="gdelt",
            source_url=url,
            metadata={
                "article_title": title,
                "article_url": url,
                "seen_date": seendate
            }
        )

        # Skip if already collected
        from trust.database import signal_exists
        if await signal_exists(url):
            return False

        # Insert signal
        weight = await get_signal_weight(signal_type)
        await insert_signal(
            business_id=business_id,
            signal_type=signal_type,
            signal_category=signal_category,
            source="gdelt",
            title=title,
            content=title,  # GDELT gives titles, not full text
            signal_date=signal_date,
            source_url=url,
            weight=weight,
            metadata={
                "gdelt_domain": article.get("domain", ""),
                "gdelt_language": article.get("language", ""),
                "gdelt_source_country": article.get("sourcecountry", "")
            }
        )

        return True

    except Exception as e:
        print(f"    [ERROR] Failed to process article: {e}")
        return False

async def run_collector(max_articles: int = 200):
    """
    Main collector function.
    Searches GDELT for business trust signals globally.
    """
    print("\n" + "="*60)
    print("GDELT GLOBAL NEWS COLLECTOR")
    print("="*60)
    print(f"Target: {max_articles} articles")
    print(f"Queries: {len(SEARCH_QUERIES)}")
    print(f"Countries: {len(COUNTRIES)}\n")

    total_processed = 0
    total_failed = 0

    for query, signal_type, signal_category in SEARCH_QUERIES:
        if total_processed >= max_articles:
            break

        print(f"[→] Query: '{query}'")
        print(f"    Signal: {signal_type} ({signal_category})")

        # Search globally first
        results = search_gdelt(query, max_records=10)
        articles = results.get("articles", [])

        if not articles:
            print(f"    No results")
            time.sleep(1)
            continue

        print(f"    Found {len(articles)} articles globally")

        for article in articles:
            if total_processed >= max_articles:
                break
            success = await process_article(
                article, signal_type, signal_category, "GLOBAL"
            )
            if success:
                total_processed += 1
            else:
                total_failed += 1

        # Also search with country context for a few key markets
        for country in COUNTRIES[:4]:  # top 4 to avoid rate limits
            if total_processed >= max_articles:
                break

            results = search_gdelt(query, country=country, max_records=5)
            articles = results.get("articles", [])

            for article in articles:
                if total_processed >= max_articles:
                    break
                success = await process_article(
                    article, signal_type, signal_category, country
                )
                if success:
                    total_processed += 1
                else:
                    total_failed += 1

        print(f"    Processed: {total_processed} total so far")
        time.sleep(2)  # polite delay

    # Final stats
    stats = await get_database_stats()

    print(f"\n{'='*60}")
    print(f"GDELT COLLECTOR COMPLETE")
    print(f"{'='*60}")
    print(f"Articles processed: {total_processed}")
    print(f"Failed:             {total_failed}")
    print(f"\nDatabase now contains:")
    print(f"  Businesses tracked: {stats['businesses_tracked']}")
    print(f"  Signals collected:  {stats['signals_collected']}")
    print(f"  Negative signals:   {stats['negative_signals']}")

    return total_processed

if __name__ == "__main__":
    asyncio.run(run_collector(max_articles=200))