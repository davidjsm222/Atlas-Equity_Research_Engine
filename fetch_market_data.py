"""
Fetch current market data (price, shares outstanding, market cap) for tracked companies.

Uses SEC EDGAR for shares outstanding and Yahoo Finance chart API for live price.
No yfinance library dependency — uses requests directly.
"""

from __future__ import annotations

import os
import pandas as pd
import requests


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TICKER_FILE = os.path.join(SCRIPT_DIR, "ticker_mapping.csv")

_SEC_USER_AGENT = "Atlas Dashboard atlas-dashboard@example.com"
_YAHOO_USER_AGENT = "Mozilla/5.0"


def _sec_headers() -> dict:
    return {"User-Agent": _SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"}


def _fetch_price(ticker: str) -> dict:
    """Fetch current price and previous close via Yahoo Finance chart API."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    try:
        r = requests.get(
            url,
            params={"range": "2d", "interval": "1d"},
            headers={"User-Agent": _YAHOO_USER_AGENT},
            timeout=10,
        )
        r.raise_for_status()
        meta = r.json()["chart"]["result"][0]["meta"]
        return {
            "price": meta.get("regularMarketPrice"),
            "prev_close": meta.get("chartPreviousClose"),
        }
    except Exception:
        return {"price": None, "prev_close": None}


def _fetch_shares_outstanding(ticker: str, cik_map: dict) -> int | None:
    """Fetch shares outstanding from SEC EDGAR Company Facts.

    Tries DEI EntityCommonStockSharesOutstanding first, then falls back to
    us-gaap CommonStockSharesOutstanding, then WeightedAverageNumberOfDilutedSharesOutstanding.
    """
    cik = cik_map.get(ticker.upper())
    if not cik:
        return None
    try:
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        r = requests.get(url, headers=_sec_headers(), timeout=20)
        r.raise_for_status()
        facts = r.json()

        # Priority 1: DEI namespace (most current — often updated with each filing)
        dei = facts.get("facts", {}).get("dei", {})
        concept = dei.get("EntityCommonStockSharesOutstanding", {})
        entries = concept.get("units", {}).get("shares", [])
        if entries:
            latest = max(entries, key=lambda e: e.get("end", ""))
            return latest.get("val")

        # Priority 2-3: us-gaap namespace fallbacks
        us_gaap = facts.get("facts", {}).get("us-gaap", {})
        for concept_name in [
            "CommonStockSharesOutstanding",
            "WeightedAverageNumberOfDilutedSharesOutstanding",
        ]:
            concept = us_gaap.get(concept_name, {})
            entries = concept.get("units", {}).get("shares", [])
            if entries:
                latest = max(entries, key=lambda e: e.get("end", ""))
                val = latest.get("val")
                if val and val > 0:
                    return val
    except Exception:
        pass
    return None


def _load_cik_map() -> dict:
    """Load ticker -> zero-padded CIK mapping from SEC."""
    try:
        r = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=_sec_headers(),
            timeout=15,
        )
        r.raise_for_status()
        return {
            v["ticker"].upper(): str(v["cik_str"]).zfill(10)
            for v in r.json().values()
        }
    except Exception:
        return {}


def fetch_market_data(ticker_file: str = TICKER_FILE) -> pd.DataFrame:
    """Fetch current market data for each ticker in the mapping file.

    Uses SEC EDGAR for shares outstanding and Yahoo Finance chart API for price.

    Args:
        ticker_file: Path to CSV with Company and Ticker columns.

    Returns:
        DataFrame with Company, Ticker, Price, Shares_Outstanding, Market_Cap.
    """
    mapping = pd.read_csv(ticker_file)
    cik_map = _load_cik_map()

    rows = []
    for _, row in mapping.iterrows():
        company = row["Company"]
        ticker = row["Ticker"]

        price_data = _fetch_price(ticker)
        price = price_data["price"]
        shares = _fetch_shares_outstanding(ticker, cik_map)
        market_cap = (price * shares) if price and shares else None

        rows.append({
            "Company": company,
            "Ticker": ticker,
            "Price": price,
            "Shares_Outstanding": shares,
            "Market_Cap": market_cap,
        })

    return pd.DataFrame(rows)


def fetch_single_ticker_market_data(ticker: str, cik_map: dict = None) -> dict:
    """Fetch market data for a single ticker. Used by Quick Comp path.

    Args:
        ticker: Stock ticker symbol
        cik_map: Pre-loaded CIK map (optional, loaded if not provided)

    Returns:
        dict with Company, Ticker, Price, Shares_Outstanding, Market_Cap
    """
    if cik_map is None:
        cik_map = _load_cik_map()

    price_data = _fetch_price(ticker)
    price = price_data["price"]
    shares = _fetch_shares_outstanding(ticker, cik_map)
    market_cap = (price * shares) if price and shares else None

    return {
        "Company": ticker,
        "Ticker": ticker,
        "Price": price,
        "Shares_Outstanding": shares,
        "Market_Cap": market_cap,
    }


def fetch_ticker_bar_price(ticker: str) -> dict | None:
    """Fetch price + daily change for a single ticker. Used by ticker bar.

    Returns:
        dict with label, price, change_pct or None on failure.
    """
    data = _fetch_price(ticker)
    price = data.get("price")
    prev = data.get("prev_close")
    if price and prev and prev != 0:
        change_pct = ((price - prev) / prev) * 100
        return {"label": ticker, "price": price, "change_pct": change_pct}
    return None


def main():
    print("Fetching market data...\n")
    df = fetch_market_data()

    pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 120)
    print(df.to_string(index=False))

    valid = df["Market_Cap"].notna().sum()
    print(f"\nFetched data for {valid}/{len(df)} tickers.")


if __name__ == "__main__":
    main()
