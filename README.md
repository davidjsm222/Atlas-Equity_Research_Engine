# Atlas

A Bloomberg Terminal-inspired financial dashboard for building and analyzing equity comp sets. Pulls financial statement data directly from SEC EDGAR — no data subscriptions required.

**Repository:** [github.com/davidjsm222/Atlas-Equity_Research_Engine](https://github.com/davidjsm222/Atlas-Equity_Research_Engine)

**Run on Streamlit Community Cloud:** create an app from this repo with main file `dashboard.py`, add `requirements.txt`, set Secrets per [Deploy](#deploy-streamlit-community-cloud) below.

## Features

- **Live EDGAR data** — fetches 20+ quarters of income statement, balance sheet, and cash flow data via the EDGAR XBRL API for any SEC-registered company
- **Live market data** — prices and shares outstanding from Yahoo Finance + EDGAR; no API keys needed
- **Overview table** — side-by-side snapshot of all loaded companies: valuation multiples, growth, margins, Rule of 40, balance sheet ratios
- **Company Deep Dive** — full quarterly chart suite per company (revenue, margins, net debt, deferred revenue, FCF, Rule of 40 trend)
- **Peer Comparison** — ranked bar charts and scatter plots (growth vs. margin, efficiency scaling analysis)
- **Investment Screener** — filter the loaded comp set by Rule of 40, revenue growth, P/FCF, FCF yield, and margin trend
- **Notes** — persistent per-comp-set notes saved locally to `notes.json`
- **PDF export** — generate a formatted multi-section report for any subset of companies
- **Animated ticker bars** — live scrolling market indices (S&P 500, NASDAQ, VIX, 10Y yield, BTC) + company watchlist

## Setup

**Requirements:** Python 3.9+

```bash
pip install -r requirements.txt
```

**Run:**

```bash
streamlit run dashboard.py
```

## Deploy (Streamlit Community Cloud)

1. Connect this repo and create an app with **Main file** `dashboard.py`.
2. Add **`requirements.txt`** (already in repo).
3. Under **App settings → Secrets**, set `ATLAS_SEC_USER_AGENT` to a string that identifies you for [SEC fair access](https://www.sec.gov/developer) (see `.streamlit/secrets.toml.example`). `dashboard.py` copies that into `os.environ` before loading fetchers. You can also set the variable in your shell for local runs.
4. Users load tickers from the sidebar (SEC EDGAR). SEC or Yahoo may occasionally block or rate-limit shared cloud IPs.

## Usage

1. Enter one or more ticker symbols in the **SEC EDGAR** sidebar panel (e.g. `NTNX, NET, CRWD`)
2. Set the number of quarters of history (4–20)
3. Click **Fetch** — data is pulled live from SEC EDGAR
4. Navigate between pages using the **NAV** panel

To reset, click **Clear**.

## Files

| File | Purpose |
|---|---|
| `dashboard.py` | Main Streamlit app |
| `fetch_financials.py` | SEC EDGAR XBRL data fetcher |
| `fetch_market_data.py` | Live price + market cap fetcher |
| `pdf_generator.py` | PDF report builder (ReportLab) |
| `ticker_mapping.csv` | Watchlist tickers for the scrolling ticker bar |
| `notes.json` | Auto-created; stores per-comp-set notes |
| `.streamlit/config.toml` | Dark theme configuration |
| `.streamlit/secrets.toml.example` | Example Secrets / env for `ATLAS_SEC_USER_AGENT` (copy or use in Cloud UI) |
| `LICENSE` | MIT |

## Data Sources

| Data | Source |
|---|---|
| Financial statements (IS, BS, CF) | [SEC EDGAR Company Facts API](https://data.sec.gov/api/xbrl/companyfacts/) |
| Shares outstanding | SEC EDGAR |
| Stock price / previous close | Yahoo Finance chart API |

No API keys, rate limits, or paid subscriptions required. SEC EDGAR requests include a `User-Agent` header per their [fair-access policy](https://www.sec.gov/developer). **SEC returns 403** if the agent does not include a contact (typically an email). The built-in default uses `atlas-dashboard@example.com` so local runs work; override with **`ATLAS_SEC_USER_AGENT`** (e.g. `MyApp/1.0 you@yourcompany.com`) for production and courtesy.

## Metrics Reference

| Metric | Definition |
|---|---|
| **EV/Revenue** | Enterprise Value ÷ TTM Revenue |
| **P/FCF** | Market Cap ÷ Annual Free Cash Flow |
| **FCF Yield** | Annual FCF ÷ Market Cap |
| **Rule of 40** | Revenue Growth % + FCF Margin % |
| **Margin Trend** | 4-quarter rolling average of operating margin delta YoY |
| **TTM** | Trailing twelve months (sum of last 4 quarters) |

## Watchlist

The scrolling company ticker bar at the top is driven by `ticker_mapping.csv`. Add or remove rows to customize it:

```csv
Company,Ticker
"Nutanix, Inc.",NTNX
"Cloudflare, Inc.",NET
```

This file is independent of which tickers you load for analysis.
