"""
World Bank Collector
Collects commodity prices and economic indicators globally.
Completely free, no API key needed.

What we collect:
- Commodity prices (oil, food, metals)
- Inflation rates by country
- GDP growth indicators
- Trade volume data

These become market_prices records and economic context signals.

API docs: https://datahelpdesk.worldbank.org/knowledgebase/articles/889392
"""

import requests
import asyncio
import time
from datetime import datetime
from trust.database import (
    insert_market_price,
    get_database_stats
)

BASE_URL = "https://api.worldbank.org/v2"

HEADERS = {
    "User-Agent": "NexusTrustLayer/1.0 (business intelligence research)",
    "Accept": "application/json"
}

# Commodity price indicators from World Bank
COMMODITY_INDICATORS = [
    ("PCOALAUUSDM",  "Coal",           "USD/mt"),
    ("POILAPSPUSDM", "Crude Oil Brent", "USD/bbl"),
    ("PNGASUSUSDM",  "Natural Gas US",  "USD/mmbtu"),
    ("PWHEAMTUSDM",  "Wheat",          "USD/mt"),
    ("PMAIZMTUSDM",  "Maize/Corn",     "USD/mt"),
    ("PSOYBUSDM",    "Soybeans",       "USD/mt"),
    ("PSUGAUSAUSDM", "Sugar",          "USD/kg"),
    ("PCOFFOTMUSDM", "Coffee",         "USD/kg"),
    ("PTEAUSDM",     "Tea",            "USD/kg"),
    ("PCOTTINDUSDM", "Cotton",         "USD/kg"),
    ("PIORECRUSDM",  "Iron Ore",       "USD/dmt"),
    ("PCOPPERINDM",  "Copper",         "USD/mt"),
    ("PALUMINUSDM",  "Aluminum",       "USD/mt"),
    ("PZINCINDM",    "Zinc",           "USD/mt"),
    ("PGOLDMTROZU",  "Gold",           "USD/troy oz"),
]

# Country inflation indicators
INFLATION_INDICATORS = [
    ("FP.CPI.TOTL.ZG", "Inflation CPI"),
]

# Key countries for SME trade context
COUNTRIES = [
    "KE", "NG", "GH", "ZA",  # Africa
    "IN", "PK", "BD",          # South Asia
    "ID", "PH", "VN",          # Southeast Asia
    "BR", "MX", "CO",          # Latin America
    "GB", "DE", "FR",          # Europe
    "US", "CN",                # Major economies
]

def fetch_commodity_prices(indicator: str, mrv: int = 12) -> list:
    """
    Fetch recent commodity prices from World Bank.
    mrv = most recent values count
    """
    params = {
        "format": "json",
        "mrv": mrv,
        "per_page": 50
    }
    try:
        url = f"{BASE_URL}/country/all/indicator/{indicator}"
        resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if len(data) >= 2:
                return data[1] or []
        else:
            print(f"    [WARNING] World Bank returned {resp.status_code} for {indicator}")
        return []
    except Exception as e:
        print(f"    [ERROR] Failed to fetch {indicator}: {e}")
        return []

def fetch_country_indicator(country: str, indicator: str, mrv: int = 5) -> list:
    """Fetch a specific indicator for a country."""
    params = {
        "format": "json",
        "mrv": mrv,
        "per_page": 10
    }
    try:
        url = f"{BASE_URL}/country/{country}/indicator/{indicator}"
        resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if len(data) >= 2:
                return data[1] or []
        return []
    except Exception as e:
        print(f"    [ERROR] Failed to fetch {country}/{indicator}: {e}")
        return []

async def process_commodity_price(
    indicator_code: str,
    commodity_name: str,
    unit: str,
    records: list
) -> int:
    """Process commodity price records into database."""
    inserted = 0
    for record in records:
        if not record or record.get("value") is None:
            continue

        try:
            price = float(record["value"])
            date_str = record.get("date", "")
            country_info = record.get("country", {})
            country = country_info.get("value", "Global")

            # Parse date
            try:
                if len(date_str) == 7:  # YYYY-MM format
                    recorded_at = datetime.strptime(date_str, "%Y-%m")
                elif len(date_str) == 4:  # YYYY format
                    recorded_at = datetime.strptime(date_str, "%Y")
                else:
                    recorded_at = datetime.utcnow()
            except:
                recorded_at = datetime.utcnow()

            await insert_market_price(
                commodity=commodity_name,
                price=price,
                currency="USD",
                unit=unit,
                market="Global",
                country=country,
                source="worldbank",
                source_url=f"https://data.worldbank.org/indicator/{indicator_code}",
                metadata={
                    "indicator_code": indicator_code,
                    "date": date_str,
                    "country_code": country_info.get("id", "")
                }
            )
            inserted += 1

        except Exception as e:
            print(f"    [ERROR] Failed to insert price: {e}")

    return inserted

async def run_collector():
    """
    Main collector function.
    Fetches commodity prices and economic indicators
    from World Bank and stores in trust database.
    """
    print("\n" + "="*60)
    print("WORLD BANK COLLECTOR")
    print("="*60)
    print(f"Commodities: {len(COMMODITY_INDICATORS)}")
    print(f"Countries:   {len(COUNTRIES)}\n")

    total_prices = 0

    # Collect commodity prices
    print("[→] Collecting commodity prices...")
    for indicator_code, commodity_name, unit in COMMODITY_INDICATORS:
        print(f"    {commodity_name}...")
        records = fetch_commodity_prices(indicator_code, mrv=6)

        if records:
            inserted = await process_commodity_price(
                indicator_code, commodity_name, unit, records
            )
            total_prices += inserted
            print(f"    ✓ {inserted} price points collected")
        else:
            print(f"    No data returned")

        time.sleep(0.5)  # polite delay

    # Collect country inflation data
    print(f"\n[→] Collecting inflation data for {len(COUNTRIES)} countries...")
    inflation_collected = 0

    for country in COUNTRIES:
        for indicator_code, indicator_name in INFLATION_INDICATORS:
            records = fetch_country_indicator(country, indicator_code, mrv=3)

            for record in records:
                if record and record.get("value") is not None:
                    try:
                        await insert_market_price(
                            commodity=f"Inflation Rate",
                            price=float(record["value"]),
                            currency="percent",
                            unit="annual %",
                            market=country,
                            country=country,
                            source="worldbank",
                            source_url=f"https://data.worldbank.org/indicator/{indicator_code}",
                            metadata={
                                "indicator": indicator_name,
                                "indicator_code": indicator_code,
                                "date": record.get("date", ""),
                                "country": country
                            }
                        )
                        inflation_collected += 1
                    except Exception as e:
                        print(f"    [ERROR] {e}")

        time.sleep(0.3)

    total_prices += inflation_collected
    print(f"    ✓ {inflation_collected} inflation data points collected")

    # Final stats
    stats = await get_database_stats()

    print(f"\n{'='*60}")
    print(f"WORLD BANK COLLECTOR COMPLETE")
    print(f"{'='*60}")
    print(f"Price points collected: {total_prices}")
    print(f"\nDatabase now contains:")
    print(f"  Businesses tracked: {stats['businesses_tracked']}")
    print(f"  Signals collected:  {stats['signals_collected']}")
    print(f"  Market prices:      {stats['market_prices']}")

    return total_prices

if __name__ == "__main__":
    asyncio.run(run_collector())