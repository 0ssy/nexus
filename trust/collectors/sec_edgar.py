"""
SEC EDGAR Collector
Collects US company filings from the SEC's EDGAR system.
Completely free, no API key needed.

What we collect:
- Bankruptcy filings (Chapter 7, Chapter 11)
- Insolvency notices
- Going concern warnings
- Fraud enforcement actions
- Company dissolution notices

API docs: https://efts.sec.gov/LATEST/search-index?q=bankruptcy&dateRange=custom&startdt=2024-01-01
"""

import requests
import asyncio
import time
from datetime import datetime, timedelta
from trust.database import (
    insert_business, insert_signal,
    get_signal_weight, get_database_stats,
    signal_exists
)

BASE_URL = "https://efts.sec.gov/LATEST/search-index"
SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
COMPANY_SEARCH_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
FULL_TEXT_URL = "https://efts.sec.gov/LATEST/search-index"

HEADERS = {
    "User-Agent": "Nanobits Trust Intelligence research@nanobits.ai",
    "Accept": "application/json"
}

# Search terms for negative business signals
SEARCH_QUERIES = [
    ("bankruptcy",           "insolvency_notice",   "negative"),
    ("chapter 11",           "insolvency_notice",   "negative"),
    ("chapter 7",            "insolvency_notice",   "negative"),
    ("going concern",        "insolvency_notice",   "negative"),
    ("fraud",                "fraud_allegation",    "negative"),
    ("dissolution",          "dissolution_notice",  "negative"),
    ("default",              "default_report",      "negative"),
    ("cease operations",     "dissolution_notice",  "negative"),
    ("liquidation",          "insolvency_notice",   "negative"),
    ("receivership",         "insolvency_notice",   "negative"),
]

def search_edgar(query: str, days_back: int = 90) -> list:
    """Search SEC EDGAR full-text search for filings."""
    start_date = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    end_date = datetime.utcnow().strftime("%Y-%m-%d")

    try:
        resp = requests.get(
            "https://efts.sec.gov/LATEST/search-index",
            params={
                "q": f'"{query}"',
                "dateRange": "custom",
                "startdt": start_date,
                "enddt": end_date,
                "hits.hits._source.entity_name": "",
                "hits.hits._source.file_date": "",
                "hits.hits._source.form_type": "",
            },
            headers=HEADERS,
            timeout=20
        )
        if resp.status_code == 200:
            data = resp.json()
            hits = data.get("hits", {}).get("hits", [])
            return hits
        elif resp.status_code == 429:
            print(f"    [RATE LIMIT] Waiting 30 seconds...")
            time.sleep(30)
            return []
        else:
            print(f"    [WARNING] EDGAR returned {resp.status_code}")
            return []
    except Exception as e:
        print(f"    [ERROR] EDGAR search failed: {e}")
        return []

def extract_company_info(hit: dict) -> dict:
    """Extract company information from an EDGAR filing hit."""
    source = hit.get("_source", {})

    # Company name is in display_names field
    display_names = source.get("display_names", [])
    if isinstance(display_names, list) and display_names:
        # display_names format: ["Company Name (CIK 0001234567)"]
        raw_name = display_names[0]
        # Strip the CIK part
        if " (CIK " in raw_name:
            entity_name = raw_name.split(" (CIK ")[0].strip()
        else:
            entity_name = raw_name.strip()
    elif isinstance(display_names, str):
        entity_name = display_names.split(" (CIK ")[0].strip()
    else:
        entity_name = ""

    file_date = source.get("file_date", "")
    form_type = source.get("root_forms", [""])[0] if source.get("root_forms") else ""
    file_num = source.get("file_num", [""])[0] if source.get("file_num") else ""
    ciks = source.get("ciks", [""])[0] if source.get("ciks") else ""

    # Build filing URL using CIK
    filing_url = ""
    if ciks:
        filing_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ciks}&type=&dateb=&owner=include&count=10"

    return {
        "name": entity_name,
        "file_date": file_date,
        "form_type": form_type,
        "accession_no": file_num,
        "filing_url": filing_url,
        "description": f"{form_type} filing",
        "period": source.get("period_ending", "")
    }

def is_valid_company_name(name: str) -> bool:
    """Validate that extracted name looks like a real company."""
    if not name or len(name) < 3:
        return False
    if len(name) > 100:
        return False
    if name.isdigit():
        return False
    # SEC filings have structured company names — trust them more
    return True

async def process_filing(
    company_info: dict,
    signal_type: str,
    signal_category: str
) -> bool:
    """Process a single SEC filing into the trust database."""
    name = company_info["name"]
    filing_url = company_info["filing_url"]

    if not is_valid_company_name(name):
        return False

    # Skip if already collected
    if filing_url and await signal_exists(filing_url):
        return False

    try:
        # Parse filing date
        signal_date = datetime.utcnow()
        if company_info["file_date"]:
            try:
                signal_date = datetime.strptime(
                    company_info["file_date"], "%Y-%m-%d"
                )
            except:
                pass

        # Insert business
        business_id = await insert_business(
            name=name,
            country="US",
            jurisdiction="us",
            source="sec_edgar",
            source_url=filing_url,
            metadata={
                "form_type": company_info["form_type"],
                "accession_no": company_info["accession_no"],
                "period": company_info["period"],
                "description": company_info["description"]
            }
        )

        # Insert signal
        weight = await get_signal_weight(signal_type)
        title = f"{company_info['form_type']} filing: {company_info['description'] or signal_type}"

        await insert_signal(
            business_id=business_id,
            signal_type=signal_type,
            signal_category=signal_category,
            source="sec_edgar",
            title=title[:255],
            content=f"SEC EDGAR filing by {name}. Form: {company_info['form_type']}. Date: {company_info['file_date']}",
            signal_date=signal_date,
            source_url=filing_url,
            weight=weight,
            metadata={
                "form_type": company_info["form_type"],
                "file_date": company_info["file_date"],
                "accession_no": company_info["accession_no"]
            }
        )

        return True

    except Exception as e:
        print(f"    [ERROR] Failed to process {name}: {e}")
        return False

async def run_collector(max_filings: int = 200):
    """
    Main collector function.
    Searches SEC EDGAR for negative business signals.
    """
    print("\n" + "="*60)
    print("SEC EDGAR COLLECTOR")
    print("="*60)
    print(f"Target: {max_filings} filings")
    print(f"Queries: {len(SEARCH_QUERIES)}\n")

    total_processed = 0
    total_failed = 0
    total_skipped = 0

    for query, signal_type, signal_category in SEARCH_QUERIES:
        if total_processed >= max_filings:
            break

        print(f"[→] Query: '{query}'")
        print(f"    Signal: {signal_type} ({signal_category})")

        hits = search_edgar(query, days_back=90)

        if not hits:
            print(f"    No results")
            time.sleep(1)
            continue

        print(f"    Found {len(hits)} filings")

        for hit in hits:
            if total_processed >= max_filings:
                break

            company_info = extract_company_info(hit)

            if not company_info["name"]:
                total_skipped += 1
                continue

            success = await process_filing(
                company_info, signal_type, signal_category
            )

            if success:
                total_processed += 1
                print(f"    ✓ {company_info['name']} [{company_info['form_type']}]")
            else:
                total_skipped += 1

        time.sleep(1)  # polite delay between queries

    # Final stats
    stats = await get_database_stats()

    print(f"\n{'='*60}")
    print(f"SEC EDGAR COLLECTOR COMPLETE")
    print(f"{'='*60}")
    print(f"Filings processed: {total_processed}")
    print(f"Skipped:           {total_skipped}")
    print(f"\nDatabase now contains:")
    print(f"  Businesses tracked: {stats['businesses_tracked']}")
    print(f"  Signals collected:  {stats['signals_collected']}")
    print(f"  Negative signals:   {stats['negative_signals']}")

    return total_processed

if __name__ == "__main__":
    asyncio.run(run_collector(max_filings=200))