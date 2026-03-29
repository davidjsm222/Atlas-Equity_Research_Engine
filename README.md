# Atlas

An equity research engine dashboard for building and analyzing equity comp sets. Pulls financial statement data directly from SEC EDGAR — no data subscriptions required.

**Repository:** [github.com/davidjsm222/Atlas-Equity_Research_Engine](https://github.com/davidjsm222/Atlas-Equity_Research_Engine)

**Live app:** [atlas-er-engine.streamlit.app](https://atlas-er-engine.streamlit.app/)

**Self-host on Streamlit Community Cloud:** connect this repo with main file `dashboard.py`, add `requirements.txt`, and set Secrets per [Deploy](#deploy-streamlit-community-cloud) below.

## Features

- **Live EDGAR data** — fetches 20+ quarters of income statement, balance sheet, and cash flow data via the EDGAR XBRL API for any SEC-registered company
- **Live market data** — prices and shares outstanding from Yahoo Finance + EDGAR; no API keys needed
- **Overview table** — side-by-side snapshot of all loaded companies: valuation multiples, growth, margins, Rule of 40, balance sheet ratios
- **Company Deep Dive** — full quarterly chart suite per company (revenue, margins, net debt, deferred revenue, FCF, Rule of 40 trend)
- **Peer Comparison** — ranked bar charts and scatter plots (growth vs. margin, efficiency scaling analysis)
- **Investment Screener** — filter the loaded comp set by Rule of 40, revenue growth, P/FCF, FCF yield, and margin trend
- **Notes** — persistent per-comp-set notes saved locally to `notes.json`
- **PDF export** — generate a formatted multi-section report for any subset of companies
- **Animated ticker bars** — live scrolling market indices (S&P 500, NASDAQ, VIX, 10Y yield, BTC); loaded comps show in the second bar after you fetch from SEC EDGAR

## Setup

**Requirements:** Python 3.9+

```bash
pip install -r requirements.txt
```

**Run:**

```bash
streamlit run dashboard.py
```

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
| `requirements.txt` | Python dependencies for local runs and Streamlit Cloud |
| `notes.json` | Auto-created locally when you use Notes (gitignored; not in the repo) |
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
