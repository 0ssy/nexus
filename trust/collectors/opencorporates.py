"""
OpenCorporates Collector
Collects company registration data from 140+ jurisdictions globally.
Free tier: 500 requests/month, no API key needed for basic search.

What we collect:
- Company name, jurisdiction, registration number, status
- Dissolution/inactive status (negative signal)
- Registration age (positive signal)
- Officer information where available

OpenCorporates API docs: https://api.opencorporates.com/documentation
"""

import requests
import asyncio
import time
from datetime import datetime, timezone
from trust.database import (
    insert_business, insert_signal,
    get_signal_weight, get_database_stats
)

BASE_URL = "https://api.opencorporates.com/v0.4"

HEADERS = {
    "User-Agent": "NexusTrustLayer/1.0 (business intelligence research)",
    "Accept": "application/json"
}

# Search terms that surface active SMEs and businesses
SEARCH_TERMS = [
    "wholesale",
    "trading",
    "logistics",
    "supplies",
    "distribution",
    "import export",
    "merchants",
    "enterprises",
]

# Jurisdictions to search — global coverage
JURISDICTIONS = [
    "ke",      # Kenya
    "ng",      # Nigeria
    "gh",      # Ghana
    "za",      # South Africa
    "gb",      # United Kingdom
    "us_de",   # United States (Delaware)
    "in",      # India
    "au",      # Australia
    "sg",      # Singapore
    "pk",      # Pakistan
]

def search_companies(query: str, jurisdiction: str = None, page: int = 1) -> dict:
    """Search OpenCorporates for companies."""
    params = {
        "q": query,
        "per_page": 20,
        "page": page,
        "format": "json"
    }
    if jurisdiction:
        params["jurisdiction_code"] = jurisdiction

    try:
        resp = requests.get(
            f"{BASE_URL}/companies/search",
            params=params,
            headers=HEADERS,
            timeout=15
        )
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 429:
            print(f"    [RATE LIMIT] Waiting 60 seconds...")
            time.sleep(60)
            return {}
        else:
            print(f"    [WARNING] OpenCorporates returned {resp.status_code}")
            return {}
    except Exception as e:
        print(f"    [ERROR] Search failed: {e}")
        return {}

def get_company_details(company_number: str, jurisdiction: str) -> dict:
    """Get detailed info for a specific company."""
    try:
        resp = requests.get(
            f"{BASE_URL}/companies/{jurisdiction}/{company_number}",
            headers=HEADERS,
            timeout=15
        )
        if resp.status_code == 200:
            return resp.json()
        return {}
    except Exception as e:
        print(f"    [ERROR] Company details failed: {e}")
        return {}

def determine_signals(company: dict) -> list:
    """
    Analyze a company record and determine what signals it generates.
    Returns list of signal dicts.
    """
    signals = []
    status = company.get("current_status", "").lower()
    incorporation_date = company.get("incorporation_date")
    company_type = company.get("company_type", "").lower()

    # Negative signals
    if any(word in status for word in ["dissolved", "inactive", "struck", "liquidat", "wound"]):
        signals.append({
            "type": "dissolution_notice",
            "category": "negative",
            "title": f"Company status: {status}",
            "content": f"Company {company.get('name')} has status: {status}"
        })

    # Positive signals
    if any(word in status for word in ["active", "live", "good standing"]):
        signals.append({
            "type": "registration_active",
            "category": "positive",
            "title": "Active company registration",
            "content": f"Company {company.get('name')} is actively registered"
        })

    # Registration age signal
    if incorporation_date:
        try:
            inc_date = datetime.strptime(incorporation_date, "%Y-%m-%d")
            age_years = (datetime.now() - inc_date).days / 365
            if age_years >= 3:
                signals.append({
                    "type": "registration_old",
                    "category": "positive",
                    "title": f"Established business ({int(age_years)} years)",
                    "content": f"Company incorporated {int(age_years)} years ago"
                })
        except:
            pass

    return signals

async def process_company(company: dict, source_url: str) -> bool:
    """Process a single company — insert business and its signals."""
    name = company.get("name", "").strip()
    jurisdiction = company.get("jurisdiction_code", "")
    registration_number = company.get("company_number", "")
    country = jurisdiction.split("_")[0].upper() if jurisdiction else "UNKNOWN"
    status = company.get("current_status", "unknown")

    if not name or len(name) < 3:
        return False

    try:
        # Insert business
        business_id = await insert_business(
            name=name,
            country=country,
            jurisdiction=jurisdiction,
            registration_number=registration_number,
            source="opencorporates",
            source_url=source_url,
            metadata={
                "status": status,
                "company_type": company.get("company_type"),
                "incorporation_date": company.get("incorporation_date"),
                "opencorporates_url": company.get("opencorporates_url")
            }
        )

        # Determine and insert signals
        signals = determine_signals(company)
        for signal in signals:
            weight = await get_signal_weight(signal["type"])
            await insert_signal(
                business_id=business_id,
                signal_type=signal["type"],
                signal_category=signal["category"],
                source="opencorporates",
                title=signal["title"],
                content=signal["content"],
                signal_date=datetime.now(timezone.utc),
                source_url=source_url,
                weight=weight
            )

        return True

    except Exception as e:
        print(f"    [ERROR] Failed to process {name}: {e}")
        return False

async def run_collector(max_companies: int = 100):
    """
    Main collector function.
    Searches OpenCorporates across jurisdictions and terms,
    stores results in trust database.
    """
    print("\n" + "="*60)
    print("OPENCORPORATES COLLECTOR")
    print("="*60)
    print(f"Target: {max_companies} companies")
    print(f"Jurisdictions: {len(JURISDICTIONS)}")
    print(f"Search terms: {len(SEARCH_TERMS)}\n")

    total_processed = 0
    total_failed = 0

    for jurisdiction in JURISDICTIONS:
        if total_processed >= max_companies:
            break

        print(f"[→] Jurisdiction: {jurisdiction.upper()}")

        for term in SEARCH_TERMS[:3]:  # 3 terms per jurisdiction to stay within rate limits
            if total_processed >= max_companies:
                break

            print(f"    Searching: '{term}'...")
            results = search_companies(term, jurisdiction)

            if not results:
                continue

            companies = results.get("results", {}).get("companies", [])
            print(f"    Found {len(companies)} companies")

            for company_wrapper in companies:
                if total_processed >= max_companies:
                    break

                company = company_wrapper.get("company", {})
                source_url = company.get("opencorporates_url", "")

                success = await process_company(company, source_url)
                if success:
                    total_processed += 1
                else:
                    total_failed += 1

            # Polite delay between searches
            time.sleep(2)

        # Slightly longer delay between jurisdictions
        time.sleep(3)

    # Final stats
    stats = await get_database_stats()

    print(f"\n{'='*60}")
    print(f"OPENCORPORATES COLLECTOR COMPLETE")
    print(f"{'='*60}")
    print(f"Companies processed: {total_processed}")
    print(f"Failed:              {total_failed}")
    print(f"\nDatabase now contains:")
    print(f"  Businesses tracked: {stats['businesses_tracked']}")
    print(f"  Signals collected:  {stats['signals_collected']}")
    print(f"  Negative signals:   {stats['negative_signals']}")

    return total_processed

if __name__ == "__main__":
    asyncio.run(run_collector(max_companies=50))