"""
Fetch current market data (price, shares outstanding, market cap) for tracked companies.

Reads ticker_mapping.csv and uses yfinance to pull live market data.
"""

import os
import pandas as pd
import yfinance as yf


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TICKER_FILE = os.path.join(SCRIPT_DIR, "ticker_mapping.csv")


def fetch_market_data(ticker_file: str = TICKER_FILE) -> pd.DataFrame:
    """Fetch current market data for each ticker in the mapping file.

    Args:
        ticker_file: Path to CSV with Company and Ticker columns.

    Returns:
        DataFrame with Company, Ticker, Price, Shares_Outstanding, Market_Cap.
    """
    mapping = pd.read_csv(ticker_file)

    rows = []
    for _, row in mapping.iterrows():
        company = row["Company"]
        ticker = row["Ticker"]
        try:
            info = yf.Ticker(ticker).info
            price = info.get("currentPrice") or info.get("regularMarketPrice")
            shares = info.get("sharesOutstanding")
            market_cap = info.get("marketCap")

            rows.append({
                "Company": company,
                "Ticker": ticker,
                "Price": price,
                "Shares_Outstanding": shares,
                "Market_Cap": market_cap,
            })
        except Exception as e:
            print(f"  Warning: Failed to fetch data for {ticker} ({company}): {e}")
            rows.append({
                "Company": company,
                "Ticker": ticker,
                "Price": None,
                "Shares_Outstanding": None,
                "Market_Cap": None,
            })

    return pd.DataFrame(rows)


def main():
    print("Fetching market data...\n")
    df = fetch_market_data()

    pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 120)
    print(df.to_string(index=False))

    # Summary
    valid = df["Market_Cap"].notna().sum()
    print(f"\nFetched data for {valid}/{len(df)} tickers.")


if __name__ == "__main__":
    main()
