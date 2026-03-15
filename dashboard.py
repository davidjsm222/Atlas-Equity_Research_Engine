"""
Quarterly Metrics Dashboard — Streamlit app for visualizing processed CapIQ data.

Usage:
    streamlit run dashboard.py
"""

import os
import re
import glob
import json
import tempfile
import traceback
from datetime import datetime
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from fetch_market_data import fetch_market_data
from pdf_generator import PDFReport

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Quarterly Metrics Dashboard",
    layout="wide",
    initial_sidebar_state="expanded"
)

if "quick_comp_active" not in st.session_state:
    st.session_state.quick_comp_active = False
if "quick_comp_data" not in st.session_state:
    st.session_state.quick_comp_data = None
if "quick_comp_cashflow" not in st.session_state:
    st.session_state.quick_comp_cashflow = None
if "quick_comp_valuation" not in st.session_state:
    st.session_state.quick_comp_valuation = None
if "quick_comp_tickers" not in st.session_state:
    st.session_state.quick_comp_tickers = []
if "quick_comp_max_quarters" not in st.session_state:
    st.session_state.quick_comp_max_quarters = 12


def render_ticker_bars(company_data_bar, market_data_bar):
    """Render two animated scrolling ticker bars using CSS marquee animation."""

    def format_item(label, price, change_pct, is_index=False):
        color = "#22C55E" if change_pct >= 0 else "#EF4444"
        arrow = "▲" if change_pct >= 0 else "▼"
        if is_index:
            if label == "10Y YIELD":
                price_str = f"{price:.2f}%"
            elif label == "VIX":
                price_str = f"{price:.2f}"
            elif label == "BTC":
                price_str = f"${price:,.0f}"
            else:
                price_str = f"{price:,.0f}"
        else:
            price_str = f"${price:.2f}"

        item_html = (
            '<span style="display:inline-flex;align-items:center;gap:0.5rem;margin:0 2rem;white-space:nowrap;">'
            f'<span style="color:#6B8CAE;font-size:0.65rem;font-weight:700;letter-spacing:1px;">{label}</span>'
            f'<span style="color:#FFFFFF;font-size:0.7rem;font-family:monospace;">{price_str}</span>'
            f'<span style="color:{color};font-size:0.65rem;font-family:monospace;">{arrow} {abs(change_pct):.2f}%</span>'
            '</span>'
            '<span style="color:#1E2D45;margin:0 0.5rem;">|</span>'
        )
        return item_html

    # Build market bar content
    market_items = ""
    for item in market_data_bar:
        market_items += format_item(item["label"], item["price"], item["change_pct"], is_index=True)

    # Build company bar content
    company_items = ""
    for item in company_data_bar:
        company_items += format_item(item["label"], item["price"], item["change_pct"], is_index=False)

    # Duplicate content for seamless loop
    market_content = market_items * 4
    company_content = company_items * 4

    # Scale animation duration by item count so both bars appear to move at same visual speed
    # (more items = wider content = longer duration for same pixels/second)
    n_market = len(market_data_bar)
    n_company = len(company_data_bar)
    base_duration = 40
    ref_items = 6  # typical market indices count
    market_duration = max(int(base_duration * max(n_market, 1) / ref_items), 20)
    company_duration = max(int(base_duration * max(n_company, 1) / ref_items), 20)

    # CSS with duration injected via .format() to avoid f-string brace conflicts
    css = """
<style>
@keyframes scroll-left {{
    0% {{ transform: translateX(0); }}
    100% {{ transform: translateX(-50%); }}
}}
.ticker-track {{
    display: inline-flex;
    animation: scroll-left {market_duration}s linear infinite;
    will-change: transform;
}}
.ticker-track-slow {{
    display: inline-flex;
    animation: scroll-left {company_duration}s linear infinite;
    will-change: transform;
}}
.ticker-bar {{
    background: #0A0F1E;
    border-bottom: 1px solid #1E2D45;
    overflow: hidden;
    white-space: nowrap;
    height: 32px;
    display: flex;
    align-items: center;
    width: 100%;
}}
.ticker-bar-2 {{
    background: #0D0D0D;
    border-bottom: 2px solid #1E2D45;
    overflow: hidden;
    white-space: nowrap;
    height: 32px;
    display: flex;
    align-items: center;
    width: 100%;
}}
</style>
""".format(market_duration=market_duration, company_duration=company_duration)

    ticker_html = css + f"""
<div style="margin:-1.5rem -2.5rem 1.5rem -2.5rem;">
    <div class="ticker-bar">
        <div style="background:#111827;border-right:1px solid #1E2D45;padding:0 0.75rem;height:100%;display:flex;align-items:center;flex-shrink:0;">
            <span style="color:#4F9EFF;font-size:0.6rem;font-weight:700;letter-spacing:1.5px;white-space:nowrap;">MARKETS</span>
        </div>
        <div style="overflow:hidden;flex:1;">
            <div class="ticker-track">{market_content}</div>
        </div>
    </div>
    <div class="ticker-bar-2">
        <div style="background:#111827;border-right:1px solid #1E2D45;padding:0 0.75rem;height:100%;display:flex;align-items:center;flex-shrink:0;">
            <span style="color:#4F9EFF;font-size:0.6rem;font-weight:700;letter-spacing:1.5px;white-space:nowrap;">WATCHLIST</span>
        </div>
        <div style="overflow:hidden;flex:1;">
            <div class="ticker-track-slow">{company_content}</div>
        </div>
    </div>
</div>
"""
    st.markdown(ticker_html, unsafe_allow_html=True)


def inject_terminal_theme():
    """Inject polished dark blue theme CSS."""
    terminal_css = """
    <style>
    /* Base */
    body, .stApp { background-color: #0D0D0D; }
    .main .block-container {
        padding: 1.5rem 2.5rem;
        max-width: 100%;
    }

    /* Sidebar */
    section[data-testid="stSidebar"] {
        background-color: #0A0F1E;
        border-right: 1px solid #1E2D45;
    }

    /* Metric cards */
    [data-testid="stMetric"] {
        background: linear-gradient(135deg, #111827 0%, #1A2235 100%);
        padding: 1rem 1.25rem;
        border: 1px solid #1E2D45;
        border-radius: 8px;
        box-shadow: 0 2px 12px rgba(79, 158, 255, 0.06);
    }
    [data-testid="stMetricValue"] {
        font-family: 'Courier New', monospace;
        font-size: 1.6rem;
        font-weight: 700;
        color: #4F9EFF;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.7rem;
        color: #6B8CAE;
        text-transform: uppercase;
        letter-spacing: 1px;
        font-weight: 600;
    }

    /* Tables */
    .dataframe { font-size: 0.75rem; border-collapse: collapse; }
    .dataframe td {
        padding: 0.4rem 0.6rem;
        border-bottom: 1px solid #1E2D45;
    }
    .dataframe th {
        background-color: #111827;
        color: #6B8CAE;
        font-weight: 600;
        padding: 0.6rem;
        border-bottom: 2px solid #1E2D45;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        font-size: 0.7rem;
    }
    .dataframe td:nth-child(n+4) {
        text-align: right;
        font-family: 'Courier New', monospace;
    }

    /* Headers */
    h1 {
        color: #4F9EFF;
        font-size: 1.6rem;
        font-weight: 700;
        letter-spacing: 2px;
        border-bottom: 1px solid #1E2D45;
        padding-bottom: 0.75rem;
        margin-bottom: 1.25rem;
    }
    h2, h3 {
        color: #CBD5E1;
        font-size: 0.95rem;
        font-weight: 600;
        letter-spacing: 0.5px;
        margin-top: 1.25rem;
        margin-bottom: 0.5rem;
    }

    /* Expanders */
    .streamlit-expanderHeader {
        background-color: #111827;
        border: 1px solid #1E2D45;
        border-radius: 6px;
        color: #6B8CAE;
        font-size: 0.8rem;
    }

    /* Buttons */
    .stButton > button {
        background: linear-gradient(135deg, #1E3A5F 0%, #2D5A8E 100%);
        color: #4F9EFF;
        border: 1px solid #2D5A8E;
        border-radius: 6px;
        font-family: 'Courier New', monospace;
        font-size: 0.8rem;
        letter-spacing: 1px;
        font-weight: 600;
        transition: all 0.2s;
    }
    .stButton > button:hover {
        background: linear-gradient(135deg, #2D5A8E 0%, #3D7AB8 100%);
        border-color: #4F9EFF;
        box-shadow: 0 0 12px rgba(79, 158, 255, 0.3);
    }

    /* Multiselect tags */
    [data-testid="stMultiSelect"] span[data-baseweb="tag"] {
        background-color: #1E3A5F;
        border: 1px solid #2D5A8E;
        border-radius: 4px;
        color: #4F9EFF;
        font-size: 0.75rem;
    }

    /* Info/warning boxes */
    [data-testid="stAlert"] {
        background-color: #111827;
        border: 1px solid #1E2D45;
        border-left: 3px solid #4F9EFF;
        border-radius: 6px;
        color: #CBD5E1;
        font-size: 0.8rem;
    }

    /* Selectbox */
    [data-testid="stSelectbox"] > div > div {
        background-color: #111827;
        border: 1px solid #1E2D45;
        border-radius: 6px;
        color: #CBD5E1;
    }

    /* Hide branding */
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
    [data-testid="collapsedControl"] {
        display: flex !important;
        visibility: visible !important;
    }
    </style>
    """
    st.markdown(terminal_css, unsafe_allow_html=True)


inject_terminal_theme()

# Bloomberg Terminal-inspired color palette
TERMINAL_COLORS = {
    "bg_primary": "#0D0D0D",
    "bg_panel": "#111827",
    "bg_panel_light": "#1A2235",
    "text_primary": "#CBD5E1",
    "text_muted": "#6B8CAE",
    "accent": "#4F9EFF",
    "positive": "#22C55E",
    "negative": "#EF4444",
    "neutral": "#60A5FA",
    "border": "#1E2D45",
}


def apply_terminal_chart_theme(fig):
    """Apply polished dark theme to Plotly chart (transparent over card bg)."""
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(17,24,39,0)",
        plot_bgcolor="rgba(17,24,39,0)",
        font=dict(family="Courier New, monospace", size=10, color="#94A3B8"),
        xaxis=dict(
            gridcolor="#1E2D45",
            gridwidth=1,
            showgrid=True,
            zeroline=False,
        ),
        yaxis=dict(
            gridcolor="#1E2D45",
            gridwidth=1,
            showgrid=True,
            zeroline=False,
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            bordercolor="#1E2D45",
            borderwidth=1,
            font=dict(size=9),
        ),
        margin=dict(l=40, r=20, t=20, b=40),
    )
    return fig


DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "processed_data")
NOTES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "notes.json")

# ---------------------------------------------------------------------------
# Metric definitions for tooltips
# ---------------------------------------------------------------------------
METRIC_DEFINITIONS = {
    # Valuation Metrics
    "Market Cap": "Total market value of company's outstanding shares (Price × Shares Outstanding)",
    "EV": "Enterprise Value = Market Cap + Net Debt. Represents total company value including debt",
    "EV/Revenue": "Enterprise Value ÷ TTM Revenue. Lower is cheaper. Typical SaaS: 5-15x",
    "P/FCF": "Price ÷ Free Cash Flow. How many years of FCF to pay back market cap. Lower is better",
    "FCF Yield": "Free Cash Flow ÷ Market Cap. Inverse of P/FCF. Higher is better (>5% is good)",
    "Price_to_Book": "Market Cap ÷ Book Value (Total Equity). Measures premium to accounting value",
    # Growth & Revenue
    "Revenue": "Quarterly revenue (in thousands USD)",
    "TTM Revenue": "Trailing 12 Months Revenue = sum of last 4 quarters. Smooths seasonality",
    "Revenue Growth YoY": "Year-over-year revenue growth comparing to same quarter last year",
    # Profitability Metrics
    "Gross Margin": "Gross Profit ÷ Revenue. What's left after COGS. SaaS typically 70-80%",
    "TTM Gross Margin": "TTM Gross Profit ÷ TTM Revenue. 4-quarter average, smooths volatility",
    "Operating Margin": "Operating Income ÷ Revenue. Profit after all operating expenses",
    "TTM Operating Margin": "TTM Operating Income ÷ TTM Revenue. 4-quarter average margin",
    "Op Margin Delta YoY": "Change in operating margin vs same quarter last year (in percentage points)",
    "Margin Trend": "4-quarter average margin delta. Expanding (>+2pp), Contracting (<-2pp), or Stable",
    "FCF_Margin": "Free Cash Flow ÷ Revenue. Cash generation efficiency",
    # SaaS-Specific Metrics
    "Rule of 40": "Revenue Growth % + FCF Margin %. SaaS health benchmark (≥40% is good)",
    "Deferred Revenue": "Cash collected upfront for future services. Leading indicator for SaaS",
    "Def Rev Growth YoY": "Year-over-year growth in deferred revenue. Predicts future revenue",
    "Rev Recog Quality": "Deferred Revenue ÷ Quarterly Revenue. Higher = more contracted revenue",
    # Balance Sheet Ratios
    "Current Ratio": "Current Assets ÷ Current Liabilities. Liquidity measure (>1.5x is healthy)",
    "Debt/Equity": "Total Debt ÷ Total Equity. Leverage ratio (<1x is conservative, >2x is risky)",
    "Net Debt": "Total Debt - Cash. Negative = net cash position (good)",
    "ROE": "Return on Equity = Net Income ÷ Total Equity. Profitability measure (>15% is good)",
    "Asset Turnover": "Revenue ÷ Total Assets. How efficiently assets generate revenue",
}


def show_metric_help(metric_name: str):
    """Return help text for a metric if definition exists."""
    return METRIC_DEFINITIONS.get(metric_name)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _clean_company_name(raw: str) -> str:
    """Normalize CapIQ company names for consistent matching.

    Handles CamelCase splitting, comma spacing, and common suffixes so that
    names from CSV filenames and ticker_mapping.csv produce identical keys.
    """
    name = raw.strip()

    # Pre-process known abbreviations and brand names before CamelCase split.
    # Order matters: longer/more specific patterns first.
    _PRE_REPLACE = [
        ("CrowdStrikeHoldings", "CrowdStrike Holdings"),
        ("TDSYNNEX", "TD SYNNEX"),
        ("SAndPGlobal", "S&P Global"),
        ("SAndP", "S&P"),
        ("MSCIInc", "MSCI Inc"),
    ]
    for pattern, replacement in _PRE_REPLACE:
        if pattern in name:
            name = name.replace(pattern, replacement, 1)

    # Insert space before uppercase letter preceded by lowercase (CamelCase),
    # but skip known brand tokens that are already correct.
    parts = name.split(" ")
    _BRAND_TOKENS = {"CrowdStrike", "MSCI", "TD", "SYNNEX", "S&P"}
    processed = []
    for part in parts:
        if part in _BRAND_TOKENS:
            processed.append(part)
        else:
            processed.append(re.sub(r"(?<=[a-z])(?=[A-Z])", " ", part))
    name = " ".join(processed)

    # Insert space before uppercase preceded by closing paren/period only
    # when not part of abbreviations like N.V.
    name = re.sub(r"(?<=\))(?=[A-Z])", " ", name)

    # Ensure space before common suffixes when directly abutting a word
    for suffix in ["Inc.", "Ltd.", "N.V.", " plc", "Corporation", "Incorporated"]:
        cleaned_suffix = suffix.strip()
        name = re.sub(rf"(?<=[a-zA-Z])(?<!\s){re.escape(cleaned_suffix)}", f" {cleaned_suffix}", name)

    # Normalize comma spacing: "Foo,Bar" -> "Foo, Bar"
    name = re.sub(r",\s*", ", ", name)

    # Collapse multiple spaces
    name = re.sub(r"\s{2,}", " ", name)

    return name.strip()


def _get_comp_set_key(company_data: dict, valuation: dict) -> str:
    """Derive stable key from active comp set. Uses tickers where available, else company name."""
    parts = []
    for name in company_data.keys():
        ticker = valuation.get(name, {}).get("Ticker")
        if pd.notna(ticker) and ticker:
            parts.append(str(ticker).strip().upper())
        else:
            parts.append(name)  # fallback to company name
    return "|".join(sorted(parts))


def _load_notes() -> dict:
    """Load notes.json. Returns {} if file missing or invalid."""
    if not os.path.exists(NOTES_PATH):
        return {}
    try:
        with open(NOTES_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_notes(notes: dict) -> None:
    """Save notes dict to notes.json."""
    with open(NOTES_PATH, "w") as f:
        json.dump(notes, f, indent=2)


@st.cache_data
def load_all_data():
    """Load every *_quarterly_metrics.csv in processed_data/ into a dict keyed by company name."""
    files = sorted(glob.glob(os.path.join(DATA_DIR, "*_quarterly_metrics.csv")))
    data = {}
    for f in files:
        raw = os.path.basename(f).replace("_quarterly_metrics.csv", "")
        name = _clean_company_name(raw)
        df = pd.read_csv(f)
        df["Date"] = pd.to_datetime(df["Date"])
        data[name] = df
    return data


@st.cache_data
def load_cashflow_data():
    """Load every *_annual_cashflow.csv in processed_data/ into a dict keyed by company name."""
    files = sorted(glob.glob(os.path.join(DATA_DIR, "*_annual_cashflow.csv")))
    data = {}
    for f in files:
        raw = os.path.basename(f).replace("_annual_cashflow.csv", "")
        name = _clean_company_name(raw)
        df = pd.read_csv(f)
        df["Date"] = pd.to_datetime(df["Date"])
        data[name] = df
    return data


@st.cache_data(ttl=300)
def load_market_data():
    """Fetch live market data and normalize company names to match load_all_data() keys."""
    mkt = fetch_market_data()
    mkt["Company"] = mkt["Company"].apply(_clean_company_name)
    return mkt


@st.cache_data(ttl=60)
def fetch_ticker_bar_data():
    """Fetch macro index data for the market ticker bar. Cached 60s."""
    from fetch_market_data import _fetch_price

    market_tickers = {
        "S&P 500": "^GSPC",
        "NASDAQ": "^IXIC",
        "10Y YIELD": "^TNX",
        "VIX": "^VIX",
        "DOW": "^DJI",
        "BTC": "BTC-USD",
    }

    market_results = []
    for label, ticker in market_tickers.items():
        data = _fetch_price(ticker)
        price = data.get("price")
        prev = data.get("prev_close")
        if price and prev and prev != 0:
            change_pct = ((price - prev) / prev) * 100
            market_results.append({
                "label": label,
                "price": price,
                "change_pct": change_pct,
                "is_index": True,
            })

    return market_results


@st.cache_data(ttl=60)
def fetch_company_ticker_bar(tickers: tuple):
    """Fetch daily change data for company watchlist. Cached 60s."""
    from fetch_market_data import fetch_ticker_bar_price

    results = []
    for ticker_sym in tickers:
        item = fetch_ticker_bar_price(ticker_sym)
        if item:
            results.append(item)
    return results


capiq_company_data = load_all_data()
capiq_cashflow_data = load_cashflow_data()

if not capiq_company_data:
    st.error("No CSV files found in processed_data/. Run parse_capiq_data.py first.")
    st.stop()

if st.session_state.quick_comp_active and st.session_state.quick_comp_data:
    company_data = st.session_state.quick_comp_data
    cashflow_data = st.session_state.quick_comp_cashflow or {}
    data_source = "Quick Comp"
else:
    company_data = capiq_company_data
    cashflow_data = capiq_cashflow_data
    data_source = "CapIQ"

company_names = list(company_data.keys())


def analyze_data_freshness(company_data):
    """Analyze data freshness for all companies.
    
    Returns:
        dict: {company_name: {
            'latest_quarter': str,
            'latest_date': datetime,
            'days_old': int,
            'is_stale': bool (>90 days old)
        }}
    """
    from datetime import datetime
    
    freshness = {}
    today = pd.Timestamp.now().normalize()
    
    for name, df in company_data.items():
        latest_date = pd.Timestamp(df.iloc[-1]["Date"])
        days_old = (today - latest_date).days
        
        freshness[name] = {
            "latest_quarter": df.iloc[-1]["Quarter"],
            "latest_date": latest_date,
            "days_old": days_old,
            "is_stale": days_old > 90  # Flag if >90 days old
        }
    
    return freshness


def format_fy_quarter(quarter_str):
    """Convert quarter string from '2025 FQ4' format to 'FY2025 Q4' format."""
    if not quarter_str:
        return "N/A"
    parts = quarter_str.split()
    if len(parts) >= 2 and "FQ" in parts[1]:
        year = parts[0]
        q_num = parts[1].replace("FQ", "Q")
        return f"FY{year} {q_num}"
    return quarter_str  # Fallback to original if format unexpected


def _fy_quarter_sort_key(quarter_str):
    """Return (year, quarter) for sorting; FY Q3 2025 < FY Q4 2025."""
    if not quarter_str:
        return (0, 0)
    parts = quarter_str.split()
    if len(parts) >= 2 and "FQ" in parts[1]:
        try:
            year = int(parts[0])
            q = int(parts[1].replace("FQ", ""))
            return (year, q)
        except (ValueError, TypeError):
            pass
    return (0, 0)


# ---------------------------------------------------------------------------
# Market data & valuation metrics
# ---------------------------------------------------------------------------
if st.session_state.quick_comp_active:
    from fetch_market_data import fetch_single_ticker_market_data, _load_cik_map
    _cik_map = _load_cik_map()
    market_rows = []
    for _ticker in st.session_state.quick_comp_tickers:
        market_rows.append(fetch_single_ticker_market_data(_ticker, cik_map=_cik_map))
    market_data = pd.DataFrame(market_rows)
    market_data["Company"] = market_data["Company"].apply(_clean_company_name)
else:
    market_data = load_market_data()
    market_data["Company"] = market_data["Company"].apply(_clean_company_name)

market_lookup = market_data.set_index("Company").to_dict("index")

# Fetch and render ticker bars — only show companies in the active comp set
_active_company_names = set(company_data.keys())
_active_market = market_data[market_data["Company"].isin(_active_company_names)]
ticker_syms = tuple(_active_market["Ticker"].dropna().tolist())
company_ticker_bar = fetch_company_ticker_bar(ticker_syms)
market_bar_data = fetch_ticker_bar_data()
render_ticker_bars(company_ticker_bar, market_bar_data)

# Pre-compute valuation metrics per company (current market data + latest quarter financials)
if st.session_state.quick_comp_active and st.session_state.quick_comp_valuation:
    valuation = st.session_state.quick_comp_valuation
else:
    # Build mapping from company_data keys to cleaned company names (for Quick Comp mode)
    ticker_to_company_lookup = {}
    if st.session_state.quick_comp_active:
        for ticker in st.session_state.quick_comp_tickers:
            cleaned = _clean_company_name(ticker)
            ticker_to_company_lookup[ticker] = cleaned
    else:
        # In CapIQ mode, keys are already company names
        for name in company_data.keys():
            ticker_to_company_lookup[name] = name
    
    valuation = {}
    for _name, _df in company_data.items():
        # Use cleaned company name for market_lookup (matches market_data Company column)
        _lookup_name = ticker_to_company_lookup.get(_name, _name)
        _mkt = market_lookup.get(_lookup_name, {})
        _mcap = _mkt.get("Market_Cap")
        _last = _df.iloc[-1]
        _nd = _last.get("Net_Debt") if "Net_Debt" in _df.columns else None
        _te = _last.get("Total_Equity") if "Total_Equity" in _df.columns else None

        # EV = Market_Cap (dollars) + Net_Debt (thousands) * 1000
        _ev = None
        if pd.notna(_mcap) and pd.notna(_nd):
            _ev = _mcap + _nd * 1_000

        # EV / Revenue using trailing-twelve-months (sum of last 4 quarters)
        _ev_rev = None
        if _ev is not None:
            _ttm = _df["Revenue"].tail(4).sum()
            if pd.notna(_ttm) and _ttm > 0:
                _ev_rev = _ev / (_ttm * 1_000)

        # Price-to-Book; negative equity → NaN
        _ptb = None
        if pd.notna(_mcap) and pd.notna(_te) and _te > 0:
            _ptb = _mcap / (_te * 1_000)

        # FCF Yield & P/FCF using most recent annual FCF
        _fcf_yield = None
        _p_fcf = None
        _fcf_margin = None
        _cf = cashflow_data.get(_name)
        if _cf is not None and not _cf.empty and "Free_Cash_Flow" in _cf.columns:
            _latest_fcf = _cf.iloc[-1].get("Free_Cash_Flow")
            if pd.notna(_mcap) and pd.notna(_latest_fcf) and _latest_fcf != 0:
                _fcf_dollars = _latest_fcf * 1_000
                _fcf_yield = _fcf_dollars / _mcap
                _p_fcf = _mcap / _fcf_dollars
            if "FCF_Margin" in _cf.columns:
                _fcf_margin = _cf.iloc[-1].get("FCF_Margin")

        # Rule of 40: Revenue Growth + FCF Margin
        _rule_of_40 = None
        _rev_growth = _last.get("Revenue_Growth_YoY")
        if pd.notna(_rev_growth) and pd.notna(_fcf_margin):
            _rule_of_40 = _rev_growth + _fcf_margin

        valuation[_name] = {
            "Ticker": _mkt.get("Ticker"),
            "Price": _mkt.get("Price"),
            "Market_Cap": _mcap,
            "EV": _ev,
            "EV_Revenue": _ev_rev,
            "Price_to_Book": _ptb,
            "FCF_Yield": _fcf_yield,
            "P_FCF": _p_fcf,
            "Rule_of_40": _rule_of_40,
        }

    if st.session_state.quick_comp_active:
        st.session_state.quick_comp_valuation = valuation

# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------
def get_terminal_table_styles():
    """Return table styles for terminal theme."""
    return [
        {
            "selector": "thead th",
            "props": [
                ("background-color", TERMINAL_COLORS["bg_panel_light"]),
                ("color", TERMINAL_COLORS["text_primary"]),
                ("font-family", "monospace"),
                ("font-size", "0.75rem"),
                ("font-weight", "600"),
                ("border-bottom", f"2px solid {TERMINAL_COLORS['border']}"),
            ],
        },
        {
            "selector": "tbody td",
            "props": [
                ("font-size", "0.75rem"),
                ("padding", "0.25rem 0.5rem"),
                ("border-bottom", f"1px solid {TERMINAL_COLORS['border']}"),
            ],
        },
        {
            "selector": "tbody td:nth-child(n+4)",
            "props": [
                ("text-align", "right"),
                ("font-family", "monospace"),
            ],
        },
    ]


def render_top_bar(page_name: str, company_names: list = None, selected: str = None, data_source: str = None):
    """Render polished top command bar with gradient and visual weight."""
    if company_names and selected:
        content = f'''
            <span style="color: #4F9EFF; font-family: monospace; font-size: 0.7rem; font-weight: 700; letter-spacing: 2px;">{page_name}</span>
            <span style="color: #1E2D45; font-size: 1rem;">│</span>
            <span style="color: #CBD5E1; font-family: monospace; font-size: 0.8rem;">{selected}</span>
        '''
    else:
        content = f'<span style="color: #4F9EFF; font-family: monospace; font-size: 0.7rem; font-weight: 700; letter-spacing: 2px;">{page_name}</span>'

    if data_source:
        content += f'<span style="color: #1E2D45; font-size: 1rem; margin-left: auto;">│</span><span style="color: #6B8CAE; font-size: 0.65rem; font-family: monospace;">{data_source}</span>'

    st.markdown(f'''
        <div style="
            background: linear-gradient(90deg, #111827 0%, #0D0D0D 100%);
            border: 1px solid #1E2D45;
            border-radius: 6px;
            padding: 0.6rem 1.25rem;
            margin-bottom: 1.25rem;
            display: flex;
            align-items: center;
            gap: 1rem;
        ">{content}</div>
    ''', unsafe_allow_html=True)


def render_info_badge(label: str, value: str):
    """Render styled info badge (replaces default st.info for KPI metadata)."""
    st.markdown(f'''
        <div style="background: #111827; border: 1px solid #1E2D45; border-radius: 6px; padding: 0.6rem 1rem;">
            <div style="color: #6B8CAE; font-size: 0.65rem; font-family: monospace; letter-spacing: 1px; text-transform: uppercase;">{label}</div>
            <div style="color: #4F9EFF; font-size: 0.9rem; font-family: monospace; font-weight: 600; margin-top: 0.2rem;">{value}</div>
        </div>
    ''', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Quick Comp Sidebar Section
# ---------------------------------------------------------------------------
st.sidebar.markdown("""
    <div style="padding: 1.25rem 1rem 0.75rem; border-bottom: 1px solid #1E2D45; margin-bottom: 0.5rem;">
        <div style="display: flex; align-items: center; gap: 0.5rem;">
            <div style="width: 3px; height: 16px; background: #4F9EFF; border-radius: 2px;"></div>
            <span style="color: #4F9EFF; font-family: monospace; font-size: 0.7rem; font-weight: 700; letter-spacing: 2px;">QUICK COMP</span>
        </div>
    </div>
""", unsafe_allow_html=True)

ticker_input = st.sidebar.text_input(
    "Enter tickers (comma-separated)",
    value="",
    help="Example: NTNX, NET, CRWD",
    key="quick_comp_input"
)

max_quarters = st.sidebar.slider(
    "Quarters of history",
    min_value=4,
    max_value=20,
    value=st.session_state.quick_comp_max_quarters,
    step=1,
    help="Number of quarters to fetch from SEC EDGAR. More quarters = richer YoY and trend analysis.",
    key="quick_comp_max_quarters_slider"
)
st.session_state.quick_comp_max_quarters = max_quarters

col_qc1, col_qc2 = st.sidebar.columns(2)
with col_qc1:
    if st.button("Fetch", use_container_width=True, key="quick_comp_fetch"):
        if ticker_input.strip():
            tickers = [t.strip().upper() for t in ticker_input.split(",") if t.strip()]
            if tickers:
                with st.spinner(f"Fetching data for {', '.join(tickers)}..."):
                    from fetch_financials import fetch_peer_set as _fetch_peer_set
                    qc_data, qc_cf = _fetch_peer_set(tickers, max_quarters=st.session_state.quick_comp_max_quarters)
                    if qc_data:
                        st.session_state.quick_comp_data = qc_data
                        st.session_state.quick_comp_cashflow = qc_cf
                        st.session_state.quick_comp_tickers = tickers
                        st.session_state.quick_comp_active = True
                        st.session_state.quick_comp_valuation = None
                        st.rerun()
                    else:
                        st.sidebar.error("Failed to fetch data. Check ticker symbols.")
with col_qc2:
    if st.button("Clear", use_container_width=True, key="quick_comp_clear"):
        st.session_state.quick_comp_active = False
        st.session_state.quick_comp_data = None
        st.session_state.quick_comp_cashflow = None
        st.session_state.quick_comp_valuation = None
        st.session_state.quick_comp_tickers = []
        st.rerun()

if st.session_state.quick_comp_active and st.session_state.quick_comp_data:
    _qc_quarter_counts = {k: len(v) for k, v in st.session_state.quick_comp_data.items()}
    _qc_min_q = min(_qc_quarter_counts.values()) if _qc_quarter_counts else 0
    _qc_max_q = max(_qc_quarter_counts.values()) if _qc_quarter_counts else 0
    _qc_q_label = f"{_qc_min_q}Q" if _qc_min_q == _qc_max_q else f"{_qc_min_q}-{_qc_max_q}Q"
    st.sidebar.markdown(f'''
        <div style="background: #111827; border: 1px solid #1E2D45; border-left: 3px solid #22C55E; border-radius: 6px; padding: 0.4rem 0.75rem; margin-bottom: 0.5rem;">
            <span style="color: #22C55E; font-size: 0.65rem; font-family: monospace; font-weight: 600;">ACTIVE</span>
            <span style="color: #6B8CAE; font-size: 0.65rem; font-family: monospace; margin-left: 0.5rem;">{", ".join(st.session_state.quick_comp_tickers)}</span>
            <span style="color: #4F9EFF; font-size: 0.6rem; font-family: monospace; margin-left: 0.5rem;">({_qc_q_label})</span>
        </div>
    ''', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# NAV
# ---------------------------------------------------------------------------
st.sidebar.markdown("""
    <div style="padding: 1.25rem 1rem 1rem; border-bottom: 1px solid #1E2D45; margin-bottom: 0.5rem;">
        <div style="display: flex; align-items: center; gap: 0.5rem;">
            <div style="width: 3px; height: 16px; background: #4F9EFF; border-radius: 2px;"></div>
            <span style="color: #4F9EFF; font-family: monospace; font-size: 0.7rem; font-weight: 700; letter-spacing: 2px;">NAV</span>
        </div>
    </div>
""", unsafe_allow_html=True)

page = st.sidebar.radio("View", ["Overview", "Company Deep Dive", "Peer Comparison", "Screener", "Notes"], label_visibility="collapsed")

# ---------------------------------------------------------------------------
# PDF Report Generation
# ---------------------------------------------------------------------------
st.sidebar.markdown("""
    <div style="padding: 1.25rem 1rem 0.75rem; border-top: 1px solid #1E2D45; border-bottom: 1px solid #1E2D45; margin-top: 1.5rem; margin-bottom: 0.5rem;">
        <div style="display: flex; align-items: center; gap: 0.5rem;">
            <div style="width: 3px; height: 16px; background: #4F9EFF; border-radius: 2px;"></div>
            <span style="color: #4F9EFF; font-family: monospace; font-size: 0.7rem; font-weight: 700; letter-spacing: 2px;">GENERATE REPORT</span>
        </div>
    </div>
""", unsafe_allow_html=True)

# Company selection
report_companies = st.sidebar.multiselect(
    "Select Companies",
    options=company_names,
    default=company_names,  # All companies by default
    help="Choose companies to include in the report"
)

# Section selection
section_options = {
    "Overview": "overview",
    "Company Deep Dives": "deep_dive",
    "Screener": "screener"
}

selected_section_labels = st.sidebar.multiselect(
    "Select Sections",
    options=list(section_options.keys()),
    default=list(section_options.keys()),  # All sections by default
    help="Choose which sections to include in the report"
)

# Convert labels to internal section names
report_sections = [section_options[label] for label in selected_section_labels]

# Export button — store PDF in session_state so download persists across Streamlit reruns
if st.sidebar.button("Export PDF", type="primary", use_container_width=True):
    if not report_companies:
        st.sidebar.error("Please select at least one company")
    elif not report_sections:
        st.sidebar.error("Please select at least one section")
    else:
        try:
            with st.spinner("Generating PDF report..."):
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp_path = tmp.name

                report = PDFReport(
                    company_data=company_data,
                    cashflow_data=cashflow_data,
                    valuation=valuation,
                    selected_companies=report_companies,
                    sections=report_sections
                )
                report.build(tmp_path)

                with open(tmp_path, "rb") as f:
                    pdf_bytes = f.read()

                os.unlink(tmp_path)
                st.session_state["_pdf_export_bytes"] = pdf_bytes
                st.session_state["_pdf_export_ready"] = True

        except Exception as e:
            st.session_state["_pdf_export_ready"] = False
            st.sidebar.error("PDF generation failed")
            error_details = f"**Error:** {type(e).__name__}: {str(e)}\n\n**Traceback:**\n```\n{traceback.format_exc()}\n```"
            st.sidebar.expander("Error Details", expanded=True).markdown(error_details)

# Persistent download button — shown whenever a PDF was successfully generated (survives reruns)
if st.session_state.get("_pdf_export_ready") and "_pdf_export_bytes" in st.session_state:
    st.sidebar.success("Report ready for download")
    st.sidebar.download_button(
        label="Download Report",
        data=st.session_state["_pdf_export_bytes"],
        file_name="atlas_report.pdf",
        mime="application/pdf",
        type="primary",
        use_container_width=True,
        key="pdf_download_btn"
    )


# ---------------------------------------------------------------------------
# Helper: format helpers
# ---------------------------------------------------------------------------
PCT_COLS = [
    "Revenue_Growth_YoY",
    "Gross_Margin",
    "Operating_Margin",
    "Operating_Margin_Delta_YoY",
]


def fmt_pct(v):
    if pd.isna(v):
        return "N/A"
    return f"{v:.1%}"


def fmt_revenue(v):
    if pd.isna(v):
        return "N/A"
    return f"${v / 1_000:,.1f}M"


def color_revenue_growth(v):
    if pd.isna(v):
        return ""
    if v > 0.20:
        return f"color: {TERMINAL_COLORS['positive']}"
    if v < 0.05:
        return f"color: {TERMINAL_COLORS['negative']}"
    return ""


def color_margin(v):
    if pd.isna(v):
        return ""
    if v > 0.70:
        return f"color: {TERMINAL_COLORS['positive']}"
    if v < 0.40:
        return f"color: {TERMINAL_COLORS['negative']}"
    return ""


def color_op_margin(v):
    if pd.isna(v):
        return ""
    if v > 0.20:
        return f"color: {TERMINAL_COLORS['positive']}"
    if v < 0.0:
        return f"color: {TERMINAL_COLORS['negative']}"
    return ""


def color_delta(v):
    if pd.isna(v):
        return ""
    if v > 0.02:
        return f"color: {TERMINAL_COLORS['positive']}"
    if v < -0.02:
        return f"color: {TERMINAL_COLORS['negative']}"
    return ""


def color_margin_trend(v):
    """Color code margin trend classification."""
    if pd.isna(v) or v == "":
        return ""
    if v == "Expanding":
        return f"color: {TERMINAL_COLORS['positive']}"
    if v == "Contracting":
        return f"color: {TERMINAL_COLORS['negative']}"
    return ""  # Stable gets no color


def fmt_ratio(v):
    if pd.isna(v):
        return "N/A"
    return f"{v:.1f}x"


def fmt_millions(v):
    """Format CapIQ values (in thousands) as millions."""
    if pd.isna(v):
        return "N/A"
    return f"${v / 1_000:,.1f}M"


def fmt_price(v):
    if pd.isna(v):
        return "N/A"
    return f"${v:,.2f}"


def fmt_market_val(v):
    """Format dollar values as $X.XB or $X.XM."""
    if pd.isna(v):
        return "N/A"
    if abs(v) >= 1e9:
        return f"${v / 1e9:,.1f}B"
    return f"${v / 1e6:,.1f}M"


def color_current_ratio(v):
    if pd.isna(v):
        return ""
    if v >= 2.0:
        return f"color: {TERMINAL_COLORS['positive']}"
    if v < 1.0:
        return f"color: {TERMINAL_COLORS['negative']}"
    return ""


def color_roe(v):
    if pd.isna(v):
        return ""
    if v > 0.10:
        return f"color: {TERMINAL_COLORS['positive']}"
    if v < 0:
        return f"color: {TERMINAL_COLORS['negative']}"
    return ""


def color_debt_to_equity(v):
    if pd.isna(v):
        return ""
    if v < 0:
        return f"color: {TERMINAL_COLORS['negative']}"
    if v > 2.0:
        return f"color: {TERMINAL_COLORS['negative']}"
    if v <= 0.5:
        return f"color: {TERMINAL_COLORS['positive']}"
    return ""


def color_fcf_yield(v):
    if pd.isna(v):
        return ""
    if v > 0.05:
        return f"color: {TERMINAL_COLORS['positive']}"
    if v < 0.02:
        return f"color: {TERMINAL_COLORS['negative']}"
    return ""


def color_p_fcf(v):
    if pd.isna(v):
        return ""
    if v < 0:
        return f"color: {TERMINAL_COLORS['negative']}"
    if v < 15:
        return f"color: {TERMINAL_COLORS['positive']}"
    if v > 30:
        return f"color: {TERMINAL_COLORS['negative']}"
    return ""


def color_deferred_rev_growth(v):
    if pd.isna(v):
        return ""
    if v > 0.20:
        return f"color: {TERMINAL_COLORS['positive']}"
    if v < 0.05:
        return f"color: {TERMINAL_COLORS['negative']}"
    return ""


def color_rule_of_40(v):
    if pd.isna(v):
        return ""
    if v >= 0.40:
        return f"color: {TERMINAL_COLORS['positive']}"
    if v < 0.20:
        return f"color: {TERMINAL_COLORS['negative']}"
    return ""


def color_data_age(v):
    """Color code data age: green <30 days, yellow 30-90, red >90."""
    if pd.isna(v):
        return ""
    if v < 30:
        return f"color: {TERMINAL_COLORS['positive']}"  # Green - fresh
    if v < 90:
        return f"color: {TERMINAL_COLORS['accent']}"  # Yellow - aging
    return f"color: {TERMINAL_COLORS['negative']}"  # Red - stale


# ---------------------------------------------------------------------------
# PAGE: Overview
# ---------------------------------------------------------------------------
if page == "Overview":
    render_top_bar("OVERVIEW", company_names=None, data_source=data_source)
    st.markdown('''
    <div style="margin-bottom: 1.5rem;">
        <div style="display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.25rem;">
            <div style="width: 4px; height: 28px; background: linear-gradient(180deg, #4F9EFF, #1E3A5F); border-radius: 2px;"></div>
            <h1 style="color: #FFFFFF; font-family: monospace; font-size: 1.4rem; font-weight: 700; letter-spacing: 3px; margin: 0; border: none; padding: 0;">OVERVIEW</h1>
        </div>
        <div style="height: 1px; background: linear-gradient(90deg, #1E2D45, transparent); margin-left: 1rem;"></div>
    </div>
''', unsafe_allow_html=True)

    # Metric definitions expander
    with st.expander("Metric Definitions (Click to expand)"):
        st.markdown("### Valuation Metrics")
        for metric in ["Market Cap", "EV", "EV/Revenue", "P/FCF", "FCF Yield"]:
            if metric in METRIC_DEFINITIONS:
                st.markdown(f"**{metric}**: {METRIC_DEFINITIONS[metric]}")
        st.markdown("### Growth & Revenue")
        for metric in ["Revenue", "TTM Revenue", "Revenue Growth YoY"]:
            if metric in METRIC_DEFINITIONS:
                st.markdown(f"**{metric}**: {METRIC_DEFINITIONS[metric]}")
        st.markdown("### Profitability Metrics")
        for metric in ["Gross Margin", "TTM Gross Margin", "Operating Margin", "TTM Operating Margin", "Op Margin Delta YoY", "Margin Trend"]:
            if metric in METRIC_DEFINITIONS:
                st.markdown(f"**{metric}**: {METRIC_DEFINITIONS[metric]}")
        st.markdown("### SaaS-Specific Metrics")
        for metric in ["Rule of 40", "Deferred Revenue", "Def Rev Growth YoY", "Rev Recog Quality"]:
            if metric in METRIC_DEFINITIONS:
                st.markdown(f"**{metric}**: {METRIC_DEFINITIONS[metric]}")
        st.markdown("### Balance Sheet Ratios")
        for metric in ["Current Ratio", "Debt/Equity", "Net Debt", "ROE", "Asset Turnover"]:
            if metric in METRIC_DEFINITIONS:
                st.markdown(f"**{metric}**: {METRIC_DEFINITIONS[metric]}")

    # Data freshness analysis
    freshness = analyze_data_freshness(company_data)
    stale_companies = [name for name, info in freshness.items() if info["is_stale"]]

    if stale_companies:
        st.markdown(f'''
    <div style="
        background: #111827;
        border: 1px solid #1E2D45;
        border-left: 3px solid #F59E0B;
        border-radius: 6px;
        padding: 0.6rem 1rem;
        margin-bottom: 1rem;
        display: flex;
        align-items: center;
        gap: 0.75rem;
    ">
        <span style="color: #F59E0B; font-size: 0.8rem;">⚠</span>
        <span style="color: #94A3B8; font-size: 0.75rem; font-family: monospace;">
            STALE DATA: {", ".join(stale_companies)}
        </span>
    </div>
''', unsafe_allow_html=True)

    col_fresh1, col_fresh2 = st.columns(2)
    with col_fresh1:
        oldest = min(freshness.values(), key=lambda x: _fy_quarter_sort_key(x["latest_quarter"]))
        oldest_fy_q = format_fy_quarter(oldest["latest_quarter"])
        st.metric("Oldest Data", oldest_fy_q)
    with col_fresh2:
        newest = max(freshness.values(), key=lambda x: _fy_quarter_sort_key(x["latest_quarter"]))
        newest_fy_q = format_fy_quarter(newest["latest_quarter"])
        st.metric("Newest Data", newest_fy_q)

    rows = []
    for name, df in company_data.items():
        last = df.iloc[-1]
        val = valuation.get(name, {})
        
        # Calculate margin trend based on last 4 quarters
        _margin_deltas = df["Operating_Margin_Delta_YoY"].tail(4).dropna()
        if len(_margin_deltas) >= 3:
            _avg_delta = _margin_deltas.mean()
            if _avg_delta > 0.02:
                _margin_trend = "Expanding"
            elif _avg_delta < -0.02:
                _margin_trend = "Contracting"
            else:
                _margin_trend = "Stable"
        else:
            _margin_trend = None
        
        rows.append(
            {
                "Company": name,
                "Ticker": val.get("Ticker"),
                "Quarter": last["Quarter"],
                "Price": val.get("Price"),
                "Market Cap": val.get("Market_Cap"),
                "EV": val.get("EV"),
                "EV/Revenue": val.get("EV_Revenue"),
                "FCF Yield": val.get("FCF_Yield"),
                "P/FCF": val.get("P_FCF"),
                "Revenue": last["Revenue"],
                "TTM Revenue": last.get("TTM_Revenue"),
                "Revenue Growth YoY": last.get("Revenue_Growth_YoY"),
                "Gross Margin": last.get("Gross_Margin"),
                "TTM Gross Margin": last.get("TTM_Gross_Margin"),
                "Operating Margin": last.get("Operating_Margin"),
                "TTM Operating Margin": last.get("TTM_Operating_Margin"),
                "Op Margin Delta YoY": last.get("Operating_Margin_Delta_YoY"),
                "Margin Trend": _margin_trend,
                "Current Ratio": last.get("Current_Ratio"),
                "Debt/Equity": last.get("Debt_to_Equity"),
                "ROE": last.get("ROE"),
                "Net Debt": last.get("Net_Debt"),
                "Deferred Revenue": last.get("Deferred_Revenue"),
                "Def Rev Growth YoY": last.get("Deferred_Revenue_Growth_YoY"),
                "Rev Recog Quality": last.get("Revenue_Recognition_Quality"),
                "Rule of 40": val.get("Rule_of_40"),
            }
        )

    overview = pd.DataFrame(rows)
    overview = overview.sort_values("Revenue Growth YoY", ascending=False, na_position="last")
    overview = overview.reset_index(drop=True)

    styled = (
        overview.style
        .format(
            {
                "Price": lambda v: fmt_price(v),
                "Market Cap": lambda v: fmt_market_val(v),
                "EV": lambda v: fmt_market_val(v),
                "EV/Revenue": lambda v: fmt_ratio(v),
                "FCF Yield": lambda v: fmt_pct(v),
                "P/FCF": lambda v: fmt_ratio(v),
                "Revenue": lambda v: fmt_revenue(v),
                "TTM Revenue": lambda v: fmt_revenue(v),
                "Revenue Growth YoY": lambda v: fmt_pct(v),
                "Gross Margin": lambda v: fmt_pct(v),
                "TTM Gross Margin": lambda v: fmt_pct(v),
                "Operating Margin": lambda v: fmt_pct(v),
                "TTM Operating Margin": lambda v: fmt_pct(v),
                "Op Margin Delta YoY": lambda v: fmt_pct(v),
                "Margin Trend": lambda v: v if pd.notna(v) else "N/A",
                "Current Ratio": lambda v: fmt_ratio(v),
                "Debt/Equity": lambda v: fmt_ratio(v),
                "ROE": lambda v: fmt_pct(v),
                "Net Debt": lambda v: fmt_millions(v),
                "Deferred Revenue": lambda v: fmt_millions(v),
                "Def Rev Growth YoY": lambda v: fmt_pct(v),
                "Rev Recog Quality": lambda v: fmt_ratio(v),
                "Rule of 40": lambda v: fmt_pct(v),
            }
        )
        .map(color_fcf_yield, subset=["FCF Yield"])
        .map(color_p_fcf, subset=["P/FCF"])
        .map(color_revenue_growth, subset=["Revenue Growth YoY"])
        .map(color_margin, subset=["Gross Margin"])
        .map(color_margin, subset=["TTM Gross Margin"])
        .map(color_op_margin, subset=["Operating Margin"])
        .map(color_op_margin, subset=["TTM Operating Margin"])
        .map(color_delta, subset=["Op Margin Delta YoY"])
        .map(color_margin_trend, subset=["Margin Trend"])
        .map(color_current_ratio, subset=["Current Ratio"])
        .map(color_debt_to_equity, subset=["Debt/Equity"])
        .map(color_roe, subset=["ROE"])
        .map(color_deferred_rev_growth, subset=["Def Rev Growth YoY"])
        .map(color_rule_of_40, subset=["Rule of 40"])
        .set_table_styles(get_terminal_table_styles())
        .hide(axis="index")
    )

    st.dataframe(styled, use_container_width=True, hide_index=True)

    st.markdown('''
    <div style="
        background: #0A0F1E;
        border: 1px solid #1E2D45;
        border-radius: 6px;
        padding: 0.75rem 1rem;
        margin-top: 1rem;
    ">
        <div style="color: #4F9EFF; font-size: 0.6rem; font-weight: 700; letter-spacing: 1.5px; margin-bottom: 0.4rem;">METHODOLOGY</div>
        <p style="color: #475569; font-size: 0.65rem; font-family: monospace; line-height: 1.6; margin: 0;">
            EV/Revenue uses trailing-twelve-months revenue. FCF Yield and P/FCF use most recent annual free cash flow. Rev Recog Quality = Deferred Revenue / Revenue. Rule of 40 = Revenue Growth % + FCF Margin % (SaaS health benchmark). Margin Trend = 4-quarter average operating margin delta (Expanding &gt;+2pp, Contracting &lt;-2pp, Stable otherwise). TTM metrics = sum of last 4 quarters (smooths seasonal volatility). Green: Revenue Growth &gt;20%, Margins &gt;70% (gross) / &gt;20% (operating), Delta &gt;+2pp, Margin Trend Expanding, Current Ratio &gt;=2x, D/E &lt;=0.5x, ROE &gt;10%, FCF Yield &gt;5%, P/FCF &lt;15x, Def Rev Growth &gt;20%, Rule of 40 &gt;=40%. Red: Growth &lt;5%, Gross Margin &lt;40%, Operating Margin &lt;0%, Delta &lt;-2pp, Margin Trend Contracting, Current Ratio &lt;1x, D/E &gt;2x or negative, ROE &lt;0%, FCF Yield &lt;2%, P/FCF &gt;30x or negative, Def Rev Growth &lt;5%, Rule of 40 &lt;20%.
        </p>
    </div>
''', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# PAGE: Company Deep Dive
# ---------------------------------------------------------------------------
elif page == "Company Deep Dive":
    selected = st.sidebar.selectbox("Select Company", company_names)
    df = company_data[selected].copy()

    render_top_bar("COMPANY DEEP DIVE", company_names=company_names, selected=selected, data_source=data_source)
    st.markdown(f'''
    <div style="margin-bottom: 1.5rem;">
        <div style="display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.25rem;">
            <div style="width: 4px; height: 28px; background: linear-gradient(180deg, #4F9EFF, #1E3A5F); border-radius: 2px;"></div>
            <h1 style="color: #FFFFFF; font-family: monospace; font-size: 1.4rem; font-weight: 700; letter-spacing: 3px; margin: 0; border: none; padding: 0;">DEEP DIVE: {selected}</h1>
        </div>
        <div style="height: 1px; background: linear-gradient(90deg, #1E2D45, transparent); margin-left: 1rem;"></div>
    </div>
''', unsafe_allow_html=True)

    # Data freshness for this company
    freshness = analyze_data_freshness(company_data)
    fresh_info = freshness[selected]
    col_info1, col_info2, col_info3 = st.columns(3)
    with col_info1:
        render_info_badge("Latest Quarter", fresh_info['latest_quarter'])
    with col_info2:
        date_str = fresh_info["latest_date"].strftime("%Y-%m-%d") if hasattr(fresh_info["latest_date"], "strftime") else str(fresh_info["latest_date"])[:10]
        render_info_badge("As of", date_str)
    with col_info3:
        # Format latest FY quarter (e.g., "2025 FQ4" -> "FY2025 Q4")
        latest_fy_q = format_fy_quarter(fresh_info['latest_quarter'])
        render_info_badge("Latest FY Quarter", latest_fy_q)

    # Metric definitions expander
    with st.expander("Metric Definitions (Click to expand)"):
        st.markdown("### Valuation Metrics")
        for metric in ["Market Cap", "EV", "EV/Revenue", "P/FCF", "FCF Yield"]:
            if metric in METRIC_DEFINITIONS:
                st.markdown(f"**{metric}**: {METRIC_DEFINITIONS[metric]}")
        st.markdown("### Profitability Metrics")
        for metric in ["Gross Margin", "Operating Margin", "TTM Gross Margin", "TTM Operating Margin", "Margin Trend"]:
            if metric in METRIC_DEFINITIONS:
                st.markdown(f"**{metric}**: {METRIC_DEFINITIONS[metric]}")
        st.markdown("### SaaS-Specific Metrics")
        for metric in ["Rule of 40", "Deferred Revenue", "Def Rev Growth YoY", "Rev Recog Quality"]:
            if metric in METRIC_DEFINITIONS:
                st.markdown(f"**{metric}**: {METRIC_DEFINITIONS[metric]}")

    # --- Rule of 40 Metric Cards ---
    rule_of_40_val = valuation.get(selected, {}).get("Rule_of_40")
    if rule_of_40_val is not None:
        # Get the components
        rev_growth = df.iloc[-1].get("Revenue_Growth_YoY") if not df.empty else None
        cf_df = cashflow_data.get(selected)
        fcf_margin = cf_df.iloc[-1].get("FCF_Margin") if cf_df is not None and not cf_df.empty else None
        
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            delta_text = "✓ Meets Benchmark" if rule_of_40_val >= 0.40 else "✗ Below Benchmark"
            delta_color = "normal" if rule_of_40_val >= 0.40 else "inverse"
            st.metric(
                "Rule of 40", 
                f"{rule_of_40_val*100:.1f}%",
                delta=delta_text,
                delta_color=delta_color
            )
        with col_b:
            if rev_growth is not None:
                st.metric("Revenue Growth YoY", f"{rev_growth*100:.1f}%")
            else:
                st.metric("Revenue Growth YoY", "N/A")
        with col_c:
            if fcf_margin is not None:
                st.metric("FCF Margin", f"{fcf_margin*100:.1f}%")
            else:
                st.metric("FCF Margin", "N/A")
        
        st.markdown('<div style="height: 1px; background: linear-gradient(90deg, #1E2D45, transparent); margin: 1.5rem 0;"></div>', unsafe_allow_html=True)

    # --- Revenue bar chart ---
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Revenue")
        fig = px.bar(
            df,
            x="Quarter",
            y="Revenue",
            text=df["Revenue"].apply(lambda v: f"${v/1000:,.0f}M"),
        )
        fig.update_traces(textposition="outside", marker_color=TERMINAL_COLORS["neutral"])
        fig.update_layout(yaxis_title="Revenue ($K)", xaxis_title="", showlegend=False)
        fig = apply_terminal_chart_theme(fig)
        st.markdown('<div style="background: #111827; border: 1px solid #1E2D45; border-radius: 8px; padding: 1rem; margin-bottom: 0.5rem;">', unsafe_allow_html=True)
        st.plotly_chart(fig, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    # --- Revenue Growth YoY ---
    with col2:
        st.subheader("Revenue Growth YoY")
        growth_df = df.dropna(subset=["Revenue_Growth_YoY"])
        fig = px.line(
            growth_df,
            x="Quarter",
            y="Revenue_Growth_YoY",
            markers=True,
        )
        fig.update_traces(line_color=TERMINAL_COLORS["accent"])
        fig.update_layout(
            yaxis_title="Growth %",
            yaxis_tickformat=".0%",
            xaxis_title="",
        )
        fig = apply_terminal_chart_theme(fig)
        st.markdown('<div style="background: #111827; border: 1px solid #1E2D45; border-radius: 8px; padding: 1rem; margin-bottom: 0.5rem;">', unsafe_allow_html=True)
        st.plotly_chart(fig, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    col3, col4 = st.columns(2)

    # --- Gross Margin & Operating Margin ---
    with col3:
        st.subheader("Gross Margin & Operating Margin")
        fig = go.Figure()
        if df["Gross_Margin"].notna().any():
            fig.add_trace(
                go.Scatter(
                    x=df["Quarter"],
                    y=df["Gross_Margin"],
                    mode="lines+markers",
                    name="Gross Margin",
                    line=dict(color=TERMINAL_COLORS["positive"]),
                )
            )
        fig.add_trace(
            go.Scatter(
                x=df["Quarter"],
                y=df["Operating_Margin"],
                mode="lines+markers",
                name="Operating Margin",
                line=dict(color=TERMINAL_COLORS["neutral"]),
            )
        )
        fig.update_layout(
            yaxis_title="Margin",
            yaxis_tickformat=".0%",
            xaxis_title="",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        )
        fig = apply_terminal_chart_theme(fig)
        st.markdown('<div style="background: #111827; border: 1px solid #1E2D45; border-radius: 8px; padding: 1rem; margin-bottom: 0.5rem;">', unsafe_allow_html=True)
        st.plotly_chart(fig, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    # --- Operating Margin Delta YoY ---
    with col4:
        st.subheader("Operating Margin Delta YoY")
        delta_df = df.dropna(subset=["Operating_Margin_Delta_YoY"])
        fig = px.line(
            delta_df,
            x="Quarter",
            y="Operating_Margin_Delta_YoY",
            markers=True,
        )
        fig.update_traces(line_color=TERMINAL_COLORS["negative"])
        fig.update_layout(
            yaxis_title="Delta (pp)",
            yaxis_tickformat=".1%",
            xaxis_title="",
        )
        # Add a zero reference line
        fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
        fig = apply_terminal_chart_theme(fig)
        st.markdown('<div style="background: #111827; border: 1px solid #1E2D45; border-radius: 8px; padding: 1rem; margin-bottom: 0.5rem;">', unsafe_allow_html=True)
        st.plotly_chart(fig, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    # --- Margin Trend Analysis ---
    margin_trend_df = df[["Quarter", "Operating_Margin", "Operating_Margin_Delta_YoY"]].dropna(subset=["Operating_Margin_Delta_YoY"])
    if len(margin_trend_df) >= 4:
        # Calculate 4-quarter rolling average of margin delta
        margin_trend_df = margin_trend_df.copy()
        margin_trend_df["Rolling_Avg_Delta"] = margin_trend_df["Operating_Margin_Delta_YoY"].rolling(4).mean()
        
        # Classify trend based on last 4 quarters
        recent_deltas = margin_trend_df["Operating_Margin_Delta_YoY"].tail(4)
        avg_delta = recent_deltas.mean()
        expanding_qtrs = (recent_deltas > 0).sum()
        
        if avg_delta > 0.02:
            trend_label = "Expanding"
            trend_color = TERMINAL_COLORS["positive"]
        elif avg_delta < -0.02:
            trend_label = "Contracting"
            trend_color = TERMINAL_COLORS["negative"]
        else:
            trend_label = "Stable"
            trend_color = TERMINAL_COLORS["accent"]
        
        # Display summary
        st.markdown('<div style="height: 1px; background: linear-gradient(90deg, #1E2D45, transparent); margin: 1.5rem 0;"></div>', unsafe_allow_html=True)
        col_trend1, col_trend2, col_trend3 = st.columns(3)
        with col_trend1:
            st.metric("Margin Trend (4Q)", trend_label, f"{avg_delta*100:+.1f}pp avg")
        with col_trend2:
            st.metric("Expanding Quarters", f"{expanding_qtrs}/4")
        with col_trend3:
            st.metric("Contracting Quarters", f"{4-expanding_qtrs}/4")
        
        # Chart with rolling average
        st.subheader("Margin Trend Analysis (4-Quarter Rolling Average)")
        fig = go.Figure()
        
        # Add rolling average line
        fig.add_trace(
            go.Scatter(
                x=margin_trend_df["Quarter"],
                y=margin_trend_df["Rolling_Avg_Delta"],
                mode="lines+markers",
                name="4Q Avg Delta",
                line=dict(color=trend_color, width=3),
                marker=dict(size=8),
            )
        )
        
        # Add individual quarter deltas as bars
        fig.add_trace(
            go.Bar(
                x=margin_trend_df["Quarter"],
                y=margin_trend_df["Operating_Margin_Delta_YoY"],
                name="Quarterly Delta",
                marker_color=[TERMINAL_COLORS["positive"] if v > 0 else TERMINAL_COLORS["negative"] for v in margin_trend_df["Operating_Margin_Delta_YoY"]],
                opacity=0.3,
            )
        )
        
        fig.update_layout(
            yaxis_title="Operating Margin Delta (pp)",
            yaxis_tickformat=".1%",
            xaxis_title="",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        )
        fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
        fig = apply_terminal_chart_theme(fig)
        st.markdown('<div style="background: #111827; border: 1px solid #1E2D45; border-radius: 8px; padding: 1rem; margin-bottom: 0.5rem;">', unsafe_allow_html=True)
        st.plotly_chart(fig, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    # --- TTM Metrics (Smoothed Quarterly Volatility) ---
    if "TTM_Revenue" in df.columns:
        ttm_df = df.dropna(subset=["TTM_Revenue"])
        
        if not ttm_df.empty:
            st.markdown('<div style="height: 1px; background: linear-gradient(90deg, #1E2D45, transparent); margin: 1.5rem 0;"></div>', unsafe_allow_html=True)
            st.subheader("TTM Metrics (Smoothed Quarterly Volatility)")
            st.caption("TTM (Trailing Twelve Months) = sum of last 4 quarters. Smooths seasonal patterns and quarterly volatility.")
            
            col_ttm1, col_ttm2 = st.columns(2)
            
            with col_ttm1:
                st.subheader("Revenue: Quarterly vs TTM")
                fig = go.Figure()
                # Quarterly revenue (dotted line)
                fig.add_trace(go.Scatter(
                    x=df["Quarter"], 
                    y=df["Revenue"], 
                    mode="lines+markers", 
                    name="Quarterly",
                    line=dict(color=TERMINAL_COLORS["neutral"], dash="dot", width=2),
                    marker=dict(size=6),
                ))
                # TTM revenue (solid line)
                fig.add_trace(go.Scatter(
                    x=ttm_df["Quarter"], 
                    y=ttm_df["TTM_Revenue"],
                    mode="lines+markers", 
                    name="TTM (4Q Sum)",
                    line=dict(color=TERMINAL_COLORS["positive"], width=3),
                    marker=dict(size=8),
                ))
                fig.update_layout(
                    yaxis_title="Revenue ($K)", 
                    xaxis_title="",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                )
                fig = apply_terminal_chart_theme(fig)
                st.markdown('<div style="background: #111827; border: 1px solid #1E2D45; border-radius: 8px; padding: 1rem; margin-bottom: 0.5rem;">', unsafe_allow_html=True)
                st.plotly_chart(fig, use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
            
            with col_ttm2:
                st.subheader("Operating Margin: Quarterly vs TTM")
                fig = go.Figure()
                # Quarterly operating margin (dotted line)
                fig.add_trace(go.Scatter(
                    x=df["Quarter"], 
                    y=df["Operating_Margin"], 
                    mode="lines+markers", 
                    name="Quarterly",
                    line=dict(color=TERMINAL_COLORS["neutral"], dash="dot", width=2),
                    marker=dict(size=6),
                ))
                # TTM operating margin (solid line)
                if "TTM_Operating_Margin" in ttm_df.columns:
                    fig.add_trace(go.Scatter(
                        x=ttm_df["Quarter"], 
                        y=ttm_df["TTM_Operating_Margin"],
                        mode="lines+markers", 
                        name="TTM (4Q Avg)",
                        line=dict(color=TERMINAL_COLORS["accent"], width=3),
                        marker=dict(size=8),
                    ))
                fig.update_layout(
                    yaxis_title="Operating Margin", 
                    yaxis_tickformat=".0%",
                    xaxis_title="",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                )
                fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
                fig = apply_terminal_chart_theme(fig)
                st.markdown('<div style="background: #111827; border: 1px solid #1E2D45; border-radius: 8px; padding: 1rem; margin-bottom: 0.5rem;">', unsafe_allow_html=True)
                st.plotly_chart(fig, use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)

    # --- Net Debt & ROE charts ---
    has_bs = "Net_Debt" in df.columns and df["Net_Debt"].notna().any()

    if has_bs:
        col5, col6 = st.columns(2)

        with col5:
            st.subheader("Net Debt")
            nd_df = df.dropna(subset=["Net_Debt"])
            colors = [TERMINAL_COLORS["negative"] if v > 0 else TERMINAL_COLORS["positive"] for v in nd_df["Net_Debt"]]
            fig = go.Figure(
                go.Bar(
                    x=nd_df["Quarter"],
                    y=nd_df["Net_Debt"],
                    marker_color=colors,
                    text=nd_df["Net_Debt"].apply(lambda v: f"${v/1000:,.0f}M"),
                    textposition="outside",
                )
            )
            fig.update_layout(yaxis_title="Net Debt ($K)", xaxis_title="")
            fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
            fig = apply_terminal_chart_theme(fig)
            st.markdown('<div style="background: #111827; border: 1px solid #1E2D45; border-radius: 8px; padding: 1rem; margin-bottom: 0.5rem;">', unsafe_allow_html=True)
            st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

        with col6:
            st.subheader("Return on Equity (ROE)")
            roe_df = df.dropna(subset=["ROE"])
            if not roe_df.empty:
                fig = px.line(roe_df, x="Quarter", y="ROE", markers=True)
                fig.update_traces(line_color=TERMINAL_COLORS["neutral"])
                fig.update_layout(
                    yaxis_title="ROE",
                    yaxis_tickformat=".0%",
                    xaxis_title="",
                )
                fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
                fig = apply_terminal_chart_theme(fig)
                st.markdown('<div style="background: #111827; border: 1px solid #1E2D45; border-radius: 8px; padding: 1rem; margin-bottom: 0.5rem;">', unsafe_allow_html=True)
                st.plotly_chart(fig, use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
            else:
                st.info("No ROE data available (Net Income not found).")

    # --- Deferred Revenue charts ---
    has_dr = "Deferred_Revenue" in df.columns and df["Deferred_Revenue"].notna().any()

    if has_dr:
        col7, col8 = st.columns(2)

        with col7:
            st.subheader("Deferred Revenue")
            dr_df = df.dropna(subset=["Deferred_Revenue"]).copy()
            dr_df["Deferred_Revenue_M"] = dr_df["Deferred_Revenue"] / 1_000
            fig = px.bar(
                dr_df,
                x="Quarter",
                y="Deferred_Revenue_M",
                text=dr_df["Deferred_Revenue_M"].apply(lambda v: f"${v:,.0f}M"),
            )
            fig.update_traces(textposition="outside", marker_color=TERMINAL_COLORS["neutral"])
            fig.update_layout(yaxis_title="Deferred Revenue ($M)", xaxis_title="", showlegend=False)
            fig = apply_terminal_chart_theme(fig)
            st.markdown('<div style="background: #111827; border: 1px solid #1E2D45; border-radius: 8px; padding: 1rem; margin-bottom: 0.5rem;">', unsafe_allow_html=True)
            st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

        with col8:
            st.subheader("Deferred Revenue Growth YoY")
            dr_growth_df = df.dropna(subset=["Deferred_Revenue_Growth_YoY"])
            if not dr_growth_df.empty:
                fig = px.line(
                    dr_growth_df,
                    x="Quarter",
                    y="Deferred_Revenue_Growth_YoY",
                    markers=True,
                )
                fig.update_traces(line_color=TERMINAL_COLORS["accent"])
                fig.update_layout(
                    yaxis_title="Growth %",
                    yaxis_tickformat=".0%",
                    xaxis_title="",
                )
                fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
                fig = apply_terminal_chart_theme(fig)
                st.markdown('<div style="background: #111827; border: 1px solid #1E2D45; border-radius: 8px; padding: 1rem; margin-bottom: 0.5rem;">', unsafe_allow_html=True)
                st.plotly_chart(fig, use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
            else:
                st.info("Not enough historical data for Deferred Revenue Growth YoY.")

        # Revenue Recognition Quality chart
        rrq_df = df.dropna(subset=["Revenue_Recognition_Quality"])
        if not rrq_df.empty:
            st.subheader("Revenue Recognition Quality (Deferred Revenue / Revenue)")
            fig = px.line(
                rrq_df,
                x="Quarter",
                y="Revenue_Recognition_Quality",
                markers=True,
            )
            fig.update_traces(line_color=TERMINAL_COLORS["neutral"])
            fig.update_layout(
                yaxis_title="Deferred Rev / Revenue",
                yaxis_tickformat=".2f",
                xaxis_title="",
            )
            fig = apply_terminal_chart_theme(fig)
            st.markdown('<div style="background: #111827; border: 1px solid #1E2D45; border-radius: 8px; padding: 1rem; margin-bottom: 0.5rem;">', unsafe_allow_html=True)
            st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

    # --- Rule of 40 Chart ---
    cf_df = cashflow_data.get(selected)
    if cf_df is not None and not cf_df.empty and "FCF_Margin" in cf_df.columns:
        # Create a mapping of fiscal year to FCF margin
        # Extract fiscal year from Quarter column (e.g., "2025 FY" -> "2025")
        fcf_margin_map = {}
        for _, row in cf_df.iterrows():
            quarter_str = str(row["Quarter"])
            if "FY" in quarter_str:
                fiscal_year = quarter_str.split()[0]
                fcf_margin_map[fiscal_year] = row["FCF_Margin"]
        
        # Calculate Rule of 40 for each quarter
        rule_40_data = []
        for _, row in df.iterrows():
            quarter_str = str(row["Quarter"])
            rev_growth = row.get("Revenue_Growth_YoY")
            
            # Extract fiscal year from quarter (e.g., "2025 FQ4" -> "2025")
            if pd.notna(rev_growth) and "FQ" in quarter_str:
                fiscal_year = quarter_str.split()[0]
                fcf_margin = fcf_margin_map.get(fiscal_year)
                
                if fcf_margin is not None and pd.notna(fcf_margin):
                    rule_40 = rev_growth + fcf_margin
                    rule_40_data.append({
                        "Quarter": quarter_str,
                        "Rule_of_40": rule_40
                    })
        
        if rule_40_data:
            rule_40_df = pd.DataFrame(rule_40_data)
            st.subheader("Rule of 40 (Revenue Growth % + FCF Margin %)")
            
            # Determine line color based on whether it meets threshold
            avg_rule_40 = rule_40_df["Rule_of_40"].mean()
            line_color = TERMINAL_COLORS["positive"] if avg_rule_40 >= 0.40 else TERMINAL_COLORS["negative"]
            
            fig = px.line(
                rule_40_df,
                x="Quarter",
                y="Rule_of_40",
                markers=True,
            )
            fig.update_traces(line_color=line_color)
            fig.update_layout(
                yaxis_title="Rule of 40 (%)",
                yaxis_tickformat=".0%",
                xaxis_title="",
            )
            # Add 40% threshold reference line
            fig.add_hline(
                y=0.40, 
                line_dash="dash", 
                line_color="#2C3E50", 
                opacity=0.7,
                annotation_text="40% Benchmark",
                annotation_position="right"
            )
            fig = apply_terminal_chart_theme(fig)
            st.markdown('<div style="background: #111827; border: 1px solid #1E2D45; border-radius: 8px; padding: 1rem; margin-bottom: 0.5rem;">', unsafe_allow_html=True)
            st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

    # --- Full data table ---
    st.subheader("Quarterly Data")
    table_df = df.copy()
    # Ensure Date column is datetime before formatting (Quick Comp data may have non-datetime dates)
    if "Date" in table_df.columns:
        table_df["Date"] = pd.to_datetime(table_df["Date"], errors="coerce")
    table_fmt = {
        "Revenue": lambda v: fmt_revenue(v),
        "Gross_Profit": lambda v: fmt_revenue(v) if pd.notna(v) else "N/A",
        "Operating_Income": lambda v: fmt_revenue(v),
        "Net_Income": lambda v: fmt_revenue(v) if pd.notna(v) else "N/A",
        "Gross_Margin": lambda v: fmt_pct(v),
        "Operating_Margin": lambda v: fmt_pct(v),
        "Revenue_Growth_YoY": lambda v: fmt_pct(v),
        "Gross_Margin_Delta_YoY": lambda v: fmt_pct(v),
        "Operating_Margin_Delta_YoY": lambda v: fmt_pct(v),
        "Date": lambda v: v.strftime("%Y-%m-%d") if pd.notna(v) else "",
        "Cash": lambda v: fmt_millions(v),
        "Total_Debt": lambda v: fmt_millions(v),
        "Total_Equity": lambda v: fmt_millions(v),
        "Current_Assets": lambda v: fmt_millions(v),
        "Current_Liabilities": lambda v: fmt_millions(v),
        "Total_Assets": lambda v: fmt_millions(v),
        "Net_Debt": lambda v: fmt_millions(v),
        "Debt_to_Equity": lambda v: fmt_ratio(v),
        "Current_Ratio": lambda v: fmt_ratio(v),
        "ROE": lambda v: fmt_pct(v),
        "Asset_Turnover": lambda v: fmt_ratio(v),
        "Deferred_Revenue": lambda v: fmt_millions(v),
        "Deferred_Revenue_Growth_YoY": lambda v: fmt_pct(v),
        "Revenue_Recognition_Quality": lambda v: fmt_ratio(v),
    }
    # Only format columns that exist in the dataframe
    table_fmt = {k: v for k, v in table_fmt.items() if k in table_df.columns}
    st.dataframe(
        table_df.style.format(table_fmt).set_table_styles(get_terminal_table_styles()).hide(axis="index"),
        use_container_width=True,
        hide_index=True,
    )

    # --- Annual Cash Flow Metrics ---
    cf_df = cashflow_data.get(selected)
    if cf_df is not None and not cf_df.empty:
        st.subheader("Annual Cash Flow Metrics")

        # FCF bar chart
        fcf_plot = cf_df.dropna(subset=["Free_Cash_Flow"])
        if not fcf_plot.empty:
            colors = [TERMINAL_COLORS["positive"] if v >= 0 else TERMINAL_COLORS["negative"] for v in fcf_plot["Free_Cash_Flow"]]
            fig = go.Figure(
                go.Bar(
                    x=fcf_plot["Quarter"],
                    y=fcf_plot["Free_Cash_Flow"],
                    marker_color=colors,
                    text=fcf_plot["Free_Cash_Flow"].apply(lambda v: f"${v/1000:,.0f}M"),
                    textposition="outside",
                )
            )
            fig.update_layout(
                yaxis_title="Free Cash Flow ($K)",
                xaxis_title="",
                height=350,
            )
            fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
            fig = apply_terminal_chart_theme(fig)
            st.markdown('<div style="background: #111827; border: 1px solid #1E2D45; border-radius: 8px; padding: 1rem; margin-bottom: 0.5rem;">', unsafe_allow_html=True)
            st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

        # Cash flow data table
        cf_table = cf_df.copy()
        cf_table_fmt = {
            "Date": lambda v: v.strftime("%Y-%m-%d") if pd.notna(v) else "",
            "Operating_Cash_Flow": lambda v: fmt_millions(v),
            "CapEx": lambda v: fmt_millions(v),
            "Free_Cash_Flow": lambda v: fmt_millions(v),
            "Annual_Revenue": lambda v: fmt_millions(v),
            "FCF_Margin": lambda v: fmt_pct(v),
        }
        cf_table_fmt = {k: v for k, v in cf_table_fmt.items() if k in cf_table.columns}
        st.dataframe(
            cf_table.style.format(cf_table_fmt).set_table_styles(get_terminal_table_styles()).hide(axis="index"),
            use_container_width=True,
            hide_index=True,
        )

# ---------------------------------------------------------------------------
# PAGE: Peer Comparison
# ---------------------------------------------------------------------------
elif page == "Peer Comparison":
    render_top_bar("PEER COMPARISON", company_names=None, data_source=data_source)
    st.markdown('''
    <div style="margin-bottom: 1.5rem;">
        <div style="display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.25rem;">
            <div style="width: 4px; height: 28px; background: linear-gradient(180deg, #4F9EFF, #1E3A5F); border-radius: 2px;"></div>
            <h1 style="color: #FFFFFF; font-family: monospace; font-size: 1.4rem; font-weight: 700; letter-spacing: 3px; margin: 0; border: none; padding: 0;">PEER COMPARISON</h1>
        </div>
        <div style="height: 1px; background: linear-gradient(90deg, #1E2D45, transparent); margin-left: 1rem;"></div>
    </div>
''', unsafe_allow_html=True)

    # Metric definitions expander
    with st.expander("Metric Definitions (Click to expand)"):
        st.markdown("### Valuation Metrics")
        for metric in ["EV/Revenue", "P/FCF", "FCF Yield"]:
            if metric in METRIC_DEFINITIONS:
                st.markdown(f"**{metric}**: {METRIC_DEFINITIONS[metric]}")
        st.markdown("### Growth & Profitability")
        for metric in ["Revenue Growth YoY", "Gross Margin", "TTM Gross Margin", "Operating Margin", "TTM Operating Margin", "Margin Trend", "ROE"]:
            if metric in METRIC_DEFINITIONS:
                st.markdown(f"**{metric}**: {METRIC_DEFINITIONS[metric]}")
        st.markdown("### SaaS-Specific")
        for metric in ["Rule of 40", "Deferred Revenue", "Def Rev Growth YoY", "Rev Recog Quality"]:
            if metric in METRIC_DEFINITIONS:
                st.markdown(f"**{metric}**: {METRIC_DEFINITIONS[metric]}")
        st.markdown("### Balance Sheet")
        for metric in ["Current Ratio", "Debt/Equity", "Asset Turnover"]:
            if metric in METRIC_DEFINITIONS:
                st.markdown(f"**{metric}**: {METRIC_DEFINITIONS[metric]}")

    # metric label -> (column name, format type)
    metric_options = {
        "Rule of 40": ("Rule_of_40", "pct"),
        "Revenue Growth YoY": ("Revenue_Growth_YoY", "pct"),
        "Gross Margin": ("Gross_Margin", "pct"),
        "TTM Gross Margin": ("TTM_Gross_Margin", "pct"),
        "Operating Margin": ("Operating_Margin", "pct"),
        "TTM Operating Margin": ("TTM_Operating_Margin", "pct"),
        "Margin Trend (4Q Avg Delta)": ("Margin_Trend_4Q", "pct"),
        "ROE (Return on Equity)": ("ROE", "pct"),
        "FCF Yield": ("FCF_Yield", "pct"),
        "Deferred Revenue Growth YoY": ("Deferred_Revenue_Growth_YoY", "pct"),
        "Revenue Recognition Quality": ("Revenue_Recognition_Quality", "ratio"),
        "P/FCF Multiple": ("P_FCF", "ratio"),
        "EV / Revenue (TTM)": ("EV_Revenue", "ratio"),
        "Debt to Equity": ("Debt_to_Equity", "ratio"),
        "Current Ratio": ("Current_Ratio", "ratio"),
        "Asset Turnover": ("Asset_Turnover", "ratio"),
    }
    metric_label = st.sidebar.selectbox("Metric", list(metric_options.keys()))
    metric_col, metric_fmt = metric_options[metric_label]

    # Build mapping from company_data keys to cleaned company names (for Quick Comp mode)
    # In Quick Comp mode, company_data keys are tickers, but market_data uses cleaned names
    ticker_to_company = {}
    if st.session_state.quick_comp_active:
        for ticker in st.session_state.quick_comp_tickers:
            cleaned = _clean_company_name(ticker)
            ticker_to_company[ticker] = cleaned
    else:
        # In CapIQ mode, keys are already company names
        for name in company_data.keys():
            ticker_to_company[name] = name

    # Build most-recent-quarter comparison frame
    rows = []
    for name, df in company_data.items():
        last = df.iloc[-1]
        val = valuation.get(name, {})
        
        # Calculate 4-quarter average margin trend
        # Relax to 2+ quarters when data is limited
        _margin_deltas = df["Operating_Margin_Delta_YoY"].tail(4).dropna()
        _min_quarters = 2 if st.session_state.quick_comp_active else 3
        _margin_trend_4q = _margin_deltas.mean() if len(_margin_deltas) >= _min_quarters else None
        
        # Use cleaned company name for display (matches market_lookup keys)
        display_name = ticker_to_company.get(name, name)
        
        rows.append(
            {
                "Company": display_name,
                "Revenue_Growth_YoY": last.get("Revenue_Growth_YoY"),
                "Gross_Margin": last.get("Gross_Margin"),
                "TTM_Gross_Margin": last.get("TTM_Gross_Margin"),
                "Operating_Margin": last.get("Operating_Margin"),
                "TTM_Operating_Margin": last.get("TTM_Operating_Margin"),
                "Margin_Trend_4Q": _margin_trend_4q,
                "ROE": last.get("ROE"),
                "EV_Revenue": val.get("EV_Revenue"),
                "FCF_Yield": val.get("FCF_Yield"),
                "P_FCF": val.get("P_FCF"),
                "Debt_to_Equity": last.get("Debt_to_Equity"),
                "Current_Ratio": last.get("Current_Ratio"),
                "Asset_Turnover": last.get("Asset_Turnover"),
                "Deferred_Revenue_Growth_YoY": last.get("Deferred_Revenue_Growth_YoY"),
                "Revenue_Recognition_Quality": last.get("Revenue_Recognition_Quality"),
                "Rule_of_40": val.get("Rule_of_40"),
                "Quarter": last["Quarter"],
            }
        )
    comp = pd.DataFrame(rows)

    # --- Ranked bar chart ---
    st.subheader(f"Companies Ranked by {metric_label}")
    bar_df = comp.dropna(subset=[metric_col]).sort_values(metric_col, ascending=True)

    if metric_fmt == "pct":
        bar_text = bar_df[metric_col].apply(lambda v: f"{v:.1%}")
        axis_fmt = ".0%"
        color_scale = "Tealgrn"
    else:
        bar_text = bar_df[metric_col].apply(lambda v: f"{v:.2f}x")
        axis_fmt = ".1f"
        color_scale = "Blues"

    fig = px.bar(
        bar_df,
        x=metric_col,
        y="Company",
        orientation="h",
        text=bar_text,
        color=metric_col,
        color_continuous_scale=color_scale,
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(
        xaxis_title=metric_label,
        xaxis_tickformat=axis_fmt,
        yaxis_title="",
        coloraxis_showscale=False,
        height=350,
    )
    fig = apply_terminal_chart_theme(fig)
    st.markdown('<div style="background: #111827; border: 1px solid #1E2D45; border-radius: 8px; padding: 1rem; margin-bottom: 0.5rem;">', unsafe_allow_html=True)
    st.plotly_chart(fig, use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

    if comp[metric_col].isna().any():
        missing = comp.loc[comp[metric_col].isna(), "Company"].tolist()
        st.caption(f"Note: {', '.join(missing)} excluded (no {metric_label} data).")

    # --- Scatter: Revenue Growth vs Operating Margin ---
    st.subheader("Revenue Growth vs Operating Margin")
    scatter_df = comp.dropna(subset=["Revenue_Growth_YoY", "Operating_Margin"])
    fig = px.scatter(
        scatter_df,
        x="Revenue_Growth_YoY",
        y="Operating_Margin",
        text="Company",
        size_max=15,
    )
    fig.update_traces(
        textposition="top center",
        marker=dict(size=14, color=TERMINAL_COLORS["neutral"]),
    )
    fig.update_layout(
        xaxis_title="Revenue Growth YoY",
        yaxis_title="Operating Margin",
        xaxis_tickformat=".0%",
        yaxis_tickformat=".0%",
        height=450,
    )
    # Add quadrant reference lines at median values
    if len(scatter_df) > 1:
        fig.add_vline(
            x=scatter_df["Revenue_Growth_YoY"].median(),
            line_dash="dash",
            line_color="gray",
            opacity=0.4,
        )
        fig.add_hline(
            y=scatter_df["Operating_Margin"].median(),
            line_dash="dash",
            line_color="gray",
            opacity=0.4,
        )
    fig = apply_terminal_chart_theme(fig)
    st.markdown('<div style="background: #111827; border: 1px solid #1E2D45; border-radius: 8px; padding: 1rem; margin-bottom: 0.5rem;">', unsafe_allow_html=True)
    st.plotly_chart(fig, use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # --- Scatter: Revenue Growth vs Margin Trend (Efficiency Scaling Analysis) ---
    st.subheader("Efficiency Scaling Analysis: Revenue Growth vs Margin Trend")
    efficiency_df = comp.dropna(subset=["Revenue_Growth_YoY", "Margin_Trend_4Q"])
    
    if not efficiency_df.empty:
        # Classify companies into quadrants
        def classify_efficiency(row):
            growth = row["Revenue_Growth_YoY"]
            margin_trend = row["Margin_Trend_4Q"]
            
            if growth >= 0.15 and margin_trend > 0:
                return "Efficient Scaling"
            elif growth < 0.15 and margin_trend > 0:
                return "Margin Improvement"
            elif growth >= 0.15 and margin_trend <= 0:
                return "Growth at Cost"
            else:
                return "Deteriorating"
        
        efficiency_df["Efficiency_Class"] = efficiency_df.apply(classify_efficiency, axis=1)
        
        # Color mapping for quadrants
        color_map = {
            "Efficient Scaling": TERMINAL_COLORS["positive"],
            "Margin Improvement": TERMINAL_COLORS["accent"],
            "Growth at Cost": "#E67E22",  # Orange
            "Deteriorating": TERMINAL_COLORS["negative"],
        }
        
        fig = px.scatter(
            efficiency_df,
            x="Revenue_Growth_YoY",
            y="Margin_Trend_4Q",
            text="Company",
            color="Efficiency_Class",
            color_discrete_map=color_map,
            size_max=15,
        )
        fig.update_traces(
            textposition="top center",
            marker=dict(size=14),
        )
        fig.update_layout(
            xaxis_title="Revenue Growth YoY",
            yaxis_title="Margin Trend (4Q Avg Delta)",
            xaxis_tickformat=".0%",
            yaxis_tickformat=".1%",
            height=500,
            legend=dict(
                title="Efficiency Classification",
                orientation="v",
                yanchor="top",
                y=1,
                xanchor="left",
                x=1.02,
            ),
        )
        
        # Add reference lines at 15% growth and 0% margin delta
        fig.add_vline(
            x=0.15,
            line_dash="dash",
            line_color="gray",
            opacity=0.5,
            annotation_text="15% Growth",
            annotation_position="top",
        )
        fig.add_hline(
            y=0,
            line_dash="dash",
            line_color="gray",
            opacity=0.5,
            annotation_text="0% Margin Delta",
            annotation_position="right",
        )
        
        fig = apply_terminal_chart_theme(fig)
        st.markdown('<div style="background: #111827; border: 1px solid #1E2D45; border-radius: 8px; padding: 1rem; margin-bottom: 0.5rem;">', unsafe_allow_html=True)
        st.plotly_chart(fig, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
        
        st.caption(
            "Efficiency Scaling Analysis shows which companies are scaling efficiently vs burning more as they grow. "
            "**Efficient Scaling** (green): High growth + expanding margins. "
            "**Margin Improvement** (yellow): Lower growth but improving margins. "
            "**Growth at Cost** (orange): High growth but contracting margins. "
            "**Deteriorating** (red): Low growth + contracting margins."
        )
    else:
        # Check if we have some data but not enough for full analysis
        has_margin_deltas = False
        if st.session_state.quick_comp_active:
            # Check if any company has at least 2 quarters of margin delta data
            for name, df in company_data.items():
                margin_deltas = df["Operating_Margin_Delta_YoY"].dropna()
                if len(margin_deltas) >= 2:
                    has_margin_deltas = True
                    break
        
        if st.session_state.quick_comp_active and has_margin_deltas:
            st.markdown('<div style="background: #111827; border: 1px solid #1E2D45; border-radius: 8px; padding: 1rem; margin-bottom: 0.5rem;">', unsafe_allow_html=True)
            st.info("Insufficient history for trend analysis. Margin trend requires 4+ quarters of Operating_Margin_Delta_YoY data (which needs 8+ quarters total). Try increasing the 'Quarters of history' slider.")
            st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div style="background: #111827; border: 1px solid #1E2D45; border-radius: 8px; padding: 1rem; margin-bottom: 0.5rem;">', unsafe_allow_html=True)
            st.info("Insufficient data for Efficiency Scaling Analysis. Requires Revenue Growth YoY and Margin Trend (4Q Avg Delta) metrics.")
            st.markdown('</div>', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# PAGE: Screener
# ---------------------------------------------------------------------------
elif page == "Screener":
    render_top_bar("INVESTMENT SCREENER", company_names=None, data_source=data_source)
    st.markdown('''
    <div style="margin-bottom: 1.5rem;">
        <div style="display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.25rem;">
            <div style="width: 4px; height: 28px; background: linear-gradient(180deg, #4F9EFF, #1E3A5F); border-radius: 2px;"></div>
            <h1 style="color: #FFFFFF; font-family: monospace; font-size: 1.4rem; font-weight: 700; letter-spacing: 3px; margin: 0; border: none; padding: 0;">INVESTMENT SCREENER</h1>
        </div>
        <div style="height: 1px; background: linear-gradient(90deg, #1E2D45, transparent); margin-left: 1rem;"></div>
    </div>
''', unsafe_allow_html=True)
    st.markdown('<p style="color: #A0A0A0; font-size: 0.9rem; margin-top: -0.5rem;">Filter companies by investment criteria</p>', unsafe_allow_html=True)
    
    # Sidebar filters
    st.sidebar.markdown("### Growth & Efficiency")
    rule_of_40_min = st.sidebar.number_input("Rule of 40 (min)", min_value=0, max_value=100, value=40, step=5, key="screener_rule_of_40")
    revenue_growth_min = st.sidebar.number_input("Revenue Growth YoY (min %)", min_value=0, max_value=100, value=15, step=5, key="screener_revenue_growth")
    
    st.sidebar.markdown("### Valuation")
    p_fcf_max = st.sidebar.number_input("P/FCF (max)", min_value=0, max_value=100, value=25, step=5, key="screener_p_fcf")
    fcf_yield_min = st.sidebar.number_input("FCF Yield (min %)", min_value=0, max_value=50, value=4, step=1, key="screener_fcf_yield")
    
    st.sidebar.markdown("### Quality")
    margin_trend_filter = st.sidebar.selectbox("Margin Trend", ["Any", "Expanding", "Stable or Expanding"], key="screener_margin_trend")
    
    # Display current filter values
    st.markdown("### Current Filter Values")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**Growth & Efficiency:**")
        st.text(f"Rule of 40 (min): {rule_of_40_min}")
        st.text(f"Revenue Growth YoY (min): {revenue_growth_min}%")
    with col2:
        st.markdown("**Valuation:**")
        st.text(f"P/FCF (max): {p_fcf_max}")
        st.text(f"FCF Yield (min): {fcf_yield_min}%")
    with col3:
        st.markdown("**Quality:**")
        st.text(f"Margin Trend: {margin_trend_filter}")
    
    # Build screening DataFrame with latest quarter data
    screening_rows = []
    for name, df in company_data.items():
        last = df.iloc[-1]
        val = valuation.get(name, {})
        
        # Calculate Margin_Trend_4Q (same logic as Peer Comparison page)
        # Relax to 2+ quarters when data is limited
        _margin_deltas = df["Operating_Margin_Delta_YoY"].tail(4).dropna()
        _min_quarters = 2 if st.session_state.quick_comp_active else 3
        _margin_trend_4q = _margin_deltas.mean() if len(_margin_deltas) >= _min_quarters else None
        
        screening_rows.append({
            "Company": name,
            "Ticker": val.get("Ticker"),
            "Rule_of_40": val.get("Rule_of_40"),
            "Revenue_Growth_YoY": last.get("Revenue_Growth_YoY"),
            "P_FCF": val.get("P_FCF"),
            "FCF_Yield": val.get("FCF_Yield"),
            "Margin_Trend_4Q": _margin_trend_4q,
        })
    
    screening_df = pd.DataFrame(screening_rows)
    
    # Convert percentage inputs to decimals for comparison
    rule_of_40_min_decimal = rule_of_40_min / 100
    revenue_growth_min_decimal = revenue_growth_min / 100
    fcf_yield_min_decimal = fcf_yield_min / 100
    
    # Apply filters (handle NaN values - treat as not passing)
    screening_df["passes_rule_of_40"] = (
        screening_df["Rule_of_40"].notna() & 
        (screening_df["Rule_of_40"] >= rule_of_40_min_decimal)
    )
    
    screening_df["passes_revenue_growth"] = (
        screening_df["Revenue_Growth_YoY"].notna() & 
        (screening_df["Revenue_Growth_YoY"] >= revenue_growth_min_decimal)
    )
    
    screening_df["passes_p_fcf"] = (
        screening_df["P_FCF"].notna() & 
        (screening_df["P_FCF"] <= p_fcf_max)
    )
    
    screening_df["passes_fcf_yield"] = (
        screening_df["FCF_Yield"].notna() & 
        (screening_df["FCF_Yield"] >= fcf_yield_min_decimal)
    )
    
    # Margin Trend filter (handle NaN - treat as not passing unless "Any")
    if margin_trend_filter == "Any":
        screening_df["passes_margin_trend"] = True
    elif margin_trend_filter == "Expanding":
        screening_df["passes_margin_trend"] = (
            screening_df["Margin_Trend_4Q"].notna() & 
            (screening_df["Margin_Trend_4Q"] > 0)
        )
    elif margin_trend_filter == "Stable or Expanding":
        screening_df["passes_margin_trend"] = (
            screening_df["Margin_Trend_4Q"].notna() & 
            (screening_df["Margin_Trend_4Q"] >= 0)
        )
    
    # Count filters passed (sum of boolean columns)
    filter_cols = [
        "passes_rule_of_40",
        "passes_revenue_growth", 
        "passes_p_fcf",
        "passes_fcf_yield",
        "passes_margin_trend"
    ]
    screening_df["filters_passed"] = screening_df[filter_cols].sum(axis=1)
    screening_df["passes_all"] = screening_df["filters_passed"] == len(filter_cols)
    
    # Table 1: Companies Meeting All Criteria
    st.markdown("### Companies Meeting All Criteria")
    meets_all = screening_df[screening_df["passes_all"]].copy()
    if not meets_all.empty:
        # Select columns to display
        display_cols = ["Company", "Ticker", "Rule_of_40", "Revenue_Growth_YoY", 
                        "P_FCF", "FCF_Yield", "Margin_Trend_4Q", "filters_passed"]
        meets_all_display = meets_all[display_cols].copy()
        
        # Format percentages for display
        meets_all_display["Rule_of_40"] = meets_all_display["Rule_of_40"].apply(
            lambda x: f"{x*100:.1f}%" if pd.notna(x) else "N/A"
        )
        meets_all_display["Revenue_Growth_YoY"] = meets_all_display["Revenue_Growth_YoY"].apply(
            lambda x: f"{x*100:.1f}%" if pd.notna(x) else "N/A"
        )
        meets_all_display["FCF_Yield"] = meets_all_display["FCF_Yield"].apply(
            lambda x: f"{x*100:.1f}%" if pd.notna(x) else "N/A"
        )
        meets_all_display["Margin_Trend_4Q"] = meets_all_display["Margin_Trend_4Q"].apply(
            lambda x: f"{x*100:.2f}%" if pd.notna(x) else "N/A"
        )
        meets_all_display["P_FCF"] = meets_all_display["P_FCF"].apply(
            lambda x: f"{x:.1f}x" if pd.notna(x) else "N/A"
        )
        
        # Rename columns for display
        meets_all_display.columns = ["Company", "Ticker", "Rule of 40", "Revenue Growth YoY",
                                    "P/FCF", "FCF Yield", "Margin Trend (4Q)", "Filters Passed"]
        
        st.dataframe(meets_all_display, use_container_width=True, hide_index=True)
    else:
        st.info("No companies meet all criteria. Adjust filters to see results.")
    
    # Table 2: All Companies Ranked by Filters Passed
    st.markdown("### All Companies Ranked by Filters Passed")
    all_ranked = screening_df.sort_values("filters_passed", ascending=False).copy()
    
    # Create "Failed Filters" column with actual values
    def get_failed_filters(row):
        """Generate text showing which filters failed and their actual values."""
        failed = []
        
        if not row["passes_rule_of_40"]:
            actual_val = row["Rule_of_40"]
            if pd.notna(actual_val):
                failed.append(f"Rule of 40 (actual: {actual_val*100:.1f}%)")
            else:
                failed.append("Rule of 40 (N/A)")
        
        if not row["passes_revenue_growth"]:
            actual_val = row["Revenue_Growth_YoY"]
            if pd.notna(actual_val):
                failed.append(f"Revenue Growth YoY (actual: {actual_val*100:.1f}%)")
            else:
                failed.append("Revenue Growth YoY (N/A)")
        
        if not row["passes_p_fcf"]:
            actual_val = row["P_FCF"]
            if pd.notna(actual_val):
                failed.append(f"P/FCF (actual: {actual_val:.1f}x)")
            else:
                failed.append("P/FCF (N/A)")
        
        if not row["passes_fcf_yield"]:
            actual_val = row["FCF_Yield"]
            if pd.notna(actual_val):
                failed.append(f"FCF Yield (actual: {actual_val*100:.1f}%)")
            else:
                failed.append("FCF Yield (N/A)")
        
        if not row["passes_margin_trend"]:
            actual_val = row["Margin_Trend_4Q"]
            if pd.notna(actual_val):
                failed.append(f"Margin Trend (actual: {actual_val*100:.2f}%)")
            else:
                failed.append("Margin Trend (N/A)")
        
        if failed:
            return "Failed: " + ", ".join(failed)
        else:
            return "All filters passed"
    
    all_ranked["Failed_Filters"] = all_ranked.apply(get_failed_filters, axis=1)
    
    # Same formatting as above
    display_cols = ["Company", "Ticker", "Rule_of_40", "Revenue_Growth_YoY",
                    "P_FCF", "FCF_Yield", "Margin_Trend_4Q", "filters_passed", "passes_all", "Failed_Filters"]
    all_ranked_display = all_ranked[display_cols].copy()
    
    # Apply same formatting
    all_ranked_display["Rule_of_40"] = all_ranked_display["Rule_of_40"].apply(
        lambda x: f"{x*100:.1f}%" if pd.notna(x) else "N/A"
    )
    all_ranked_display["Revenue_Growth_YoY"] = all_ranked_display["Revenue_Growth_YoY"].apply(
        lambda x: f"{x*100:.1f}%" if pd.notna(x) else "N/A"
    )
    all_ranked_display["FCF_Yield"] = all_ranked_display["FCF_Yield"].apply(
        lambda x: f"{x*100:.1f}%" if pd.notna(x) else "N/A"
    )
    all_ranked_display["Margin_Trend_4Q"] = all_ranked_display["Margin_Trend_4Q"].apply(
        lambda x: f"{x*100:.2f}%" if pd.notna(x) else "N/A"
    )
    all_ranked_display["P_FCF"] = all_ranked_display["P_FCF"].apply(
        lambda x: f"{x:.1f}x" if pd.notna(x) else "N/A"
    )
    all_ranked_display["passes_all"] = all_ranked_display["passes_all"].apply(
        lambda x: "Yes" if x else "No"
    )
    
    # Rename columns
    all_ranked_display.columns = ["Company", "Ticker", "Rule of 40", "Revenue Growth YoY",
                                  "P/FCF", "FCF Yield", "Margin Trend (4Q)", "Filters Passed", "Meets All", "Failed Filters"]
    
    # Apply row-level color coding based on filters_passed percentage
    total_filters = len(filter_cols)  # Should be 5
    def color_row_by_percentage(row):
        """Apply background color based on filters passed percentage."""
        filters_passed = row["Filters Passed"]
        percentage = filters_passed / total_filters
        
        if percentage == 1.0:  # Passes all (100%)
            return ['background-color: #1a4d1a'] * len(row)  # Dark green
        elif percentage >= 0.7:  # Passes 70%+ (3.5+ filters, so 4 or 5 filters)
            return ['background-color: #4d4d1a'] * len(row)  # Dark yellow/olive
        elif percentage < 0.5:  # Passes <50% (<2.5 filters, so 0, 1, or 2 filters)
            return ['background-color: #4d1a1a'] * len(row)  # Dark red
        else:  # 50% to <70% (3 filters = 60%) - no special color
            return [''] * len(row)
    
    styled_all_ranked = (
        all_ranked_display.style
        .apply(color_row_by_percentage, axis=1)
        .set_table_styles(get_terminal_table_styles())
    )
    
    st.dataframe(styled_all_ranked, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# PAGE: Notes
# ---------------------------------------------------------------------------
elif page == "Notes":
    render_top_bar("NOTES", company_names=None, data_source=data_source)
    st.markdown('''
    <div style="margin-bottom: 1.5rem;">
        <div style="display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.25rem;">
            <div style="width: 4px; height: 28px; background: linear-gradient(180deg, #4F9EFF, #1E3A5F); border-radius: 2px;"></div>
            <h1 style="color: #FFFFFF; font-family: monospace; font-size: 1.4rem; font-weight: 700; letter-spacing: 3px; margin: 0; border: none; padding: 0;">NOTES</h1>
        </div>
        <div style="height: 1px; background: linear-gradient(90deg, #1E2D45, transparent); margin-left: 1rem;"></div>
    </div>
''', unsafe_allow_html=True)
    st.markdown('<p style="color: #A0A0A0; font-size: 0.9rem; margin-top: -0.5rem;">Save and manage notes for different comp sets</p>', unsafe_allow_html=True)
    
    # Compute current comp set key
    current_key = _get_comp_set_key(company_data, valuation)
    
    # Load all notes
    all_notes = _load_notes()
    
    # Determine which key we're viewing/editing
    if "notes_viewing_key" not in st.session_state:
        st.session_state.notes_viewing_key = None
    
    viewing_key = st.session_state.notes_viewing_key if st.session_state.notes_viewing_key else current_key
    
    # Load notes for the viewing key
    viewing_notes_data = all_notes.get(viewing_key, {})
    current_label = viewing_notes_data.get("label", "")
    current_notes = viewing_notes_data.get("notes", "")
    updated_at = viewing_notes_data.get("updated_at", None)
    
    # Show current comp set badge
    st.markdown(f'''
    <div style="background: #111827; border: 1px solid #1E2D45; border-left: 3px solid #4F9EFF; border-radius: 6px; padding: 0.6rem 0.75rem; margin-bottom: 1rem;">
        <span style="color: #4F9EFF; font-size: 0.65rem; font-family: monospace; font-weight: 600;">CURRENT COMP SET</span>
        <br/>
        <span style="color: #FFFFFF; font-size: 0.75rem; font-family: monospace;">{current_key}</span>
    </div>
''', unsafe_allow_html=True)
    
    # If viewing a different set, show indicator
    if st.session_state.notes_viewing_key and st.session_state.notes_viewing_key != current_key:
        st.markdown(f'''
        <div style="background: #111827; border: 1px solid #4d4d1a; border-left: 3px solid #FCD34D; border-radius: 6px; padding: 0.6rem 0.75rem; margin-bottom: 1rem;">
            <span style="color: #FCD34D; font-size: 0.65rem; font-family: monospace; font-weight: 600;">VIEWING SAVED SET</span>
            <br/>
            <span style="color: #FFFFFF; font-size: 0.75rem; font-family: monospace;">{viewing_key}</span>
        </div>
    ''', unsafe_allow_html=True)
        
        if st.button("← Back to Current Comp Set", type="secondary"):
            st.session_state.notes_viewing_key = None
            st.rerun()
    
    # Label input
    label_input = st.text_input(
        "Set name (optional)",
        value=current_label,
        placeholder="e.g., 'NTNX Cloud Peers' or 'High-Growth SaaS'",
        key="notes_label_input",
        help="Give this comp set a memorable name"
    )
    
    # Notes text area
    notes_input = st.text_area(
        "Notes",
        value=current_notes,
        height=300,
        key="notes_text_input",
        placeholder="Add your notes here...\n\nIdeas:\n• Investment thesis\n• Key concerns or catalysts\n• Comparison insights\n• Follow-up items",
        help="Freeform notes for this comp set"
    )
    
    # Save button
    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button("Save Notes", type="primary", use_container_width=True):
            # Save to the viewing key (current or selected saved set)
            all_notes[viewing_key] = {
                "notes": notes_input,
                "label": label_input,
                "updated_at": datetime.now().isoformat()
            }
            _save_notes(all_notes)
            st.success("Notes saved!")
            st.rerun()
    
    with col2:
        if updated_at:
            try:
                dt = datetime.fromisoformat(updated_at)
                formatted_time = dt.strftime("%b %d, %Y at %I:%M %p")
                st.markdown(f'<p style="color: #6B8CAE; font-size: 0.85rem; margin-top: 0.5rem;">Last saved: {formatted_time}</p>', unsafe_allow_html=True)
            except:
                pass
    
    # Saved sets browser
    st.markdown("---")
    st.markdown('''
    <div style="margin-bottom: 1rem; margin-top: 1.5rem;">
        <div style="display: flex; align-items: center; gap: 0.5rem;">
            <div style="width: 3px; height: 20px; background: #4F9EFF; border-radius: 2px;"></div>
            <h3 style="color: #FFFFFF; font-family: monospace; font-size: 1rem; font-weight: 700; letter-spacing: 1px; margin: 0;">SAVED SETS</h3>
        </div>
    </div>
''', unsafe_allow_html=True)
    
    if not all_notes:
        st.markdown('<p style="color: #6B8CAE; font-size: 0.9rem;">No saved notes yet. Save your first set above!</p>', unsafe_allow_html=True)
    else:
        # Sort by updated_at (most recent first)
        sorted_notes = sorted(
            all_notes.items(),
            key=lambda x: x[1].get("updated_at", ""),
            reverse=True
        )
        
        for note_key, note_data in sorted_notes:
            label = note_data.get("label", "")
            updated = note_data.get("updated_at", "")
            notes_preview = note_data.get("notes", "")
            
            # Format timestamp
            time_str = ""
            if updated:
                try:
                    dt = datetime.fromisoformat(updated)
                    time_str = dt.strftime("%b %d, %Y")
                except:
                    time_str = "Unknown date"
            
            # Create preview (first 80 chars)
            preview = notes_preview[:80] + "..." if len(notes_preview) > 80 else notes_preview
            preview = preview.replace("\n", " ")
            
            # Display label or key
            display_title = label if label else note_key
            
            # Highlight if this is the current viewing set
            is_viewing = (note_key == viewing_key)
            border_color = "#4F9EFF" if is_viewing else "#1E2D45"
            bg_color = "#0A1628" if is_viewing else "#111827"
            
            st.markdown(f'''
            <div style="background: {bg_color}; border: 1px solid {border_color}; border-radius: 6px; padding: 0.75rem; margin-bottom: 0.75rem;">
                <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 0.5rem;">
                    <span style="color: #FFFFFF; font-size: 0.9rem; font-weight: 600;">{display_title}</span>
                    <span style="color: #6B8CAE; font-size: 0.75rem; font-family: monospace;">{time_str}</span>
                </div>
                <div style="color: #6B8CAE; font-size: 0.75rem; font-family: monospace; margin-bottom: 0.5rem;">{note_key}</div>
                <div style="color: #9CA3AF; font-size: 0.8rem; font-style: italic;">{preview if preview else "(empty)"}</div>
            </div>
        ''', unsafe_allow_html=True)
            
            # Button to load this set
            if not is_viewing:
                if st.button(f"View", key=f"view_{note_key}", type="secondary"):
                    st.session_state.notes_viewing_key = note_key
                    st.rerun()

