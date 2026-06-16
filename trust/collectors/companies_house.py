"""
UK Companies House Collector
Collects company data from the UK Companies House API.
Completely free, no API key needed for basic search.
Covers 5+ million UK companies with rich structured data.

API docs: https://developer.company-information.service.gov.uk/
"""

import requests
import asyncio
import time
from datetime import datetime, timezone
from trust.database import (
    insert_business, insert_signal,
    get_signal_weight, get_database_stats
)

BASE_URL = "https://api.company-information.service.gov.uk"

HEADERS = {
    "User-Agent": "NexusTrustLayer/1.0 (business intelligence research)",
    "Accept": "application/json"
}

# Search terms targeting SME-type businesses
SEARCH_TERMS = [
    "wholesale",
    "trading",
    "logistics",
    "supplies",
    "distribution",
    "import",
    "merchants",
    "enterprises",
    "procurement",
    "commodities"
]

# Company status mapping to signal types
STATUS_SIGNALS = {
    "active": ("registration_active", "positive"),
    "dissolved": ("dissolution_notice", "negative"),
    "liquidation": ("insolvency_notice", "negative"),
    "administration": ("insolvency_notice", "negative"),
    "receivership": ("insolvency_notice", "negative"),
    "voluntary-arrangement": ("insolvency_notice", "negative"),
    "converted-closed": ("dissolution_notice", "negative"),
    "insolvency-proceedings": ("insolvency_notice", "negative"),
}

def search_companies(query: str, start_index: int = 0) -> dict:
    """Search Companies House for companies."""
    params = {
        "q": query,
        "items_per_page": 20,
        "start_index": start_index
    }
    try:
        resp = requests.get(
            f"{BASE_URL}/search/companies",
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
            print(f"    [WARNING] Companies House returned {resp.status_code}")
            return {}
    except Exception as e:
        print(f"    [ERROR] Search failed: {e}")
        return {}

def determine_signals(company: dict) -> list:
    """
    Analyze a company record and determine what signals it generates.
    Returns list of signal dicts.
    """
    signals = []
    status = company.get("company_status", "").lower()
    date_of_creation = company.get("date_of_creation")

    # Status-based signals
    if status in STATUS_SIGNALS:
        signal_type, category = STATUS_SIGNALS[status]
        signals.append({
            "type": signal_type,
            "category": category,
            "title": f"Company status: {status}",
            "content": f"Company {company.get('title')} has status: {status}"
        })

    # Registration age signal
    if date_of_creation and status == "active":
        try:
            creation_date = datetime.strptime(date_of_creation, "%Y-%m-%d")
            age_years = (datetime.now() - creation_date).days / 365
            if age_years >= 3:
                signals.append({
                    "type": "registration_old",
                    "category": "positive",
                    "title": f"Established business ({int(age_years)} years)",
                    "content": f"Company incorporated {int(age_years)} years ago on {date_of_creation}"
                })
        except:
            pass

    return signals

async def process_company(company: dict) -> bool:
    """Process a single company — insert business and signals."""
    name = company.get("title", "").strip()
    company_number = company.get("company_number", "")
    status = company.get("company_status", "unknown")
    company_type = company.get("company_type", "")
    date_created = company.get("date_of_creation", "")

    address = company.get("registered_office_address", {})
    city = address.get("locality", "")

    source_url = f"https://find-and-update.company-information.service.gov.uk/company/{company_number}"

    if not name or len(name) < 3:
        return False

    try:
        # Insert business
        business_id = await insert_business(
            name=name,
            country="GB",
            jurisdiction="gb",
            registration_number=company_number,
            sector=company_type,
            city=city,
            source="companies_house",
            source_url=source_url,
            metadata={
                "status": status,
                "company_type": company_type,
                "date_of_creation": date_created,
                "address": address
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
                source="companies_house",
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

async def run_collector(max_companies: int = 200):
    """
    Main collector function.
    Searches Companies House and stores results in trust database.
    """
    print("\n" + "="*60)
    print("UK COMPANIES HOUSE COLLECTOR")
    print("="*60)
    print(f"Target: {max_companies} companies")
    print(f"Search terms: {len(SEARCH_TERMS)}\n")

    total_processed = 0
    total_failed = 0

    for term in SEARCH_TERMS:
        if total_processed >= max_companies:
            break

        print(f"[→] Searching: '{term}'...")
        results = search_companies(term)

        if not results:
            print(f"    No results returned")
            continue

        companies = results.get("items", [])
        total_hits = results.get("total_results", 0)
        print(f"    Found {len(companies)} companies (total hits: {total_hits})")

        active = 0
        dissolved = 0

        for company in companies:
            if total_processed >= max_companies:
                break

            success = await process_company(company)
            if success:
                total_processed += 1
                status = company.get("company_status", "")
                if status == "active":
                    active += 1
                elif status in ["dissolved", "liquidation"]:
                    dissolved += 1
            else:
                total_failed += 1

        print(f"    Processed: {active} active, {dissolved} dissolved")

        # Polite delay between searches
        time.sleep(1)

    # Final stats
    stats = await get_database_stats()

    print(f"\n{'='*60}")
    print(f"COMPANIES HOUSE COLLECTOR COMPLETE")
    print(f"{'='*60}")
    print(f"Companies processed: {total_processed}")
    print(f"Failed:              {total_failed}")
    print(f"\nDatabase now contains:")
    print(f"  Businesses tracked: {stats['businesses_tracked']}")
    print(f"  Signals collected:  {stats['signals_collected']}")
    print(f"  Negative signals:   {stats['negative_signals']}")

    return total_processed

if __name__ == "__main__":
    asyncio.run(run_collector(max_companies=200))