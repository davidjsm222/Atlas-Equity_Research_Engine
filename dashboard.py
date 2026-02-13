"""
Quarterly Metrics Dashboard — Streamlit app for visualizing processed CapIQ data.

Usage:
    streamlit run dashboard.py
"""

import os
import re
import glob
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from fetch_market_data import fetch_market_data

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Quarterly Metrics Dashboard", layout="wide")

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "processed_data")

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
    """Normalize CapIQ company names for consistent matching."""
    name = raw.replace(",", ", ")
    name = re.sub(r"(?<=[a-z])Inc\.", " Inc.", name)
    return name


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


company_data = load_all_data()
cashflow_data = load_cashflow_data()

if not company_data:
    st.error("No CSV files found in processed_data/. Run parse_capiq_data.py first.")
    st.stop()

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


# ---------------------------------------------------------------------------
# Market data & valuation metrics
# ---------------------------------------------------------------------------
market_data = load_market_data()
market_lookup = market_data.set_index("Company").to_dict("index")

# Pre-compute valuation metrics per company (current market data + latest quarter financials)
valuation = {}
for _name, _df in company_data.items():
    _mkt = market_lookup.get(_name, {})
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
            _fcf_dollars = _latest_fcf * 1_000  # convert from thousands to dollars
            _fcf_yield = _fcf_dollars / _mcap    # as decimal
            _p_fcf = _mcap / _fcf_dollars        # as multiple
        # Get FCF Margin for Rule of 40
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

# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------
st.sidebar.title("Navigation")
page = st.sidebar.radio("View", ["Overview", "Company Deep Dive", "Peer Comparison"])

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
        return "color: #0a7c42"
    if v < 0.05:
        return "color: #c0392b"
    return ""


def color_margin(v):
    if pd.isna(v):
        return ""
    if v > 0.70:
        return "color: #0a7c42"
    if v < 0.40:
        return "color: #c0392b"
    return ""


def color_op_margin(v):
    if pd.isna(v):
        return ""
    if v > 0.20:
        return "color: #0a7c42"
    if v < 0.0:
        return "color: #c0392b"
    return ""


def color_delta(v):
    if pd.isna(v):
        return ""
    if v > 0.02:
        return "color: #0a7c42"
    if v < -0.02:
        return "color: #c0392b"
    return ""


def color_margin_trend(v):
    """Color code margin trend classification."""
    if pd.isna(v) or v == "":
        return ""
    if v == "Expanding":
        return "color: #0a7c42"
    if v == "Contracting":
        return "color: #c0392b"
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
        return "color: #0a7c42"
    if v < 1.0:
        return "color: #c0392b"
    return ""


def color_roe(v):
    if pd.isna(v):
        return ""
    if v > 0.10:
        return "color: #0a7c42"
    if v < 0:
        return "color: #c0392b"
    return ""


def color_debt_to_equity(v):
    if pd.isna(v):
        return ""
    if v < 0:
        return "color: #c0392b"
    if v > 2.0:
        return "color: #c0392b"
    if v <= 0.5:
        return "color: #0a7c42"
    return ""


def color_fcf_yield(v):
    if pd.isna(v):
        return ""
    if v > 0.05:
        return "color: #0a7c42"
    if v < 0.02:
        return "color: #c0392b"
    return ""


def color_p_fcf(v):
    if pd.isna(v):
        return ""
    if v < 0:
        return "color: #c0392b"
    if v < 15:
        return "color: #0a7c42"
    if v > 30:
        return "color: #c0392b"
    return ""


def color_deferred_rev_growth(v):
    if pd.isna(v):
        return ""
    if v > 0.20:
        return "color: #0a7c42"
    if v < 0.05:
        return "color: #c0392b"
    return ""


def color_rule_of_40(v):
    if pd.isna(v):
        return ""
    if v >= 0.40:
        return "color: #0a7c42"
    if v < 0.20:
        return "color: #c0392b"
    return ""


def color_data_age(v):
    """Color code data age: green <30 days, yellow 30-90, red >90."""
    if pd.isna(v):
        return ""
    if v < 30:
        return "color: #0a7c42"  # Green - fresh
    if v < 90:
        return "color: #F39C12"  # Yellow - aging
    return "color: #c0392b"  # Red - stale


# ---------------------------------------------------------------------------
# PAGE: Overview
# ---------------------------------------------------------------------------
if page == "Overview":
    st.title("Overview — Most Recent Quarter")

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
        st.warning(f"Stale data detected for {len(stale_companies)} companies: {', '.join(stale_companies)}")

    col_fresh1, col_fresh2, col_fresh3 = st.columns(3)
    with col_fresh1:
        avg_days = sum(f["days_old"] for f in freshness.values()) / len(freshness)
        st.metric("Avg Data Age", f"{avg_days:.0f} days")
    with col_fresh2:
        oldest = max(freshness.values(), key=lambda x: x["days_old"])
        st.metric("Oldest Data", f"{oldest['days_old']} days", delta=oldest["latest_quarter"])
    with col_fresh3:
        newest = min(freshness.values(), key=lambda x: x["days_old"])
        st.metric("Newest Data", f"{newest['days_old']} days", delta=newest["latest_quarter"])

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
                "Data Age (days)": freshness[name]["days_old"],
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
                "Data Age (days)": lambda v: f"{v:.0f}" if pd.notna(v) else "N/A",
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
        .map(color_data_age, subset=["Data Age (days)"])
        .hide(axis="index")
    )

    st.dataframe(styled, use_container_width=True, hide_index=True)

    st.caption(
        "EV/Revenue uses trailing-twelve-months revenue. "
        "FCF Yield and P/FCF use most recent annual free cash flow. "
        "Rev Recog Quality = Deferred Revenue / Revenue. "
        "Rule of 40 = Revenue Growth % + FCF Margin % (SaaS health benchmark). "
        "Margin Trend = 4-quarter average operating margin delta (Expanding >+2pp, Contracting <-2pp, Stable otherwise). "
        "TTM metrics = sum of last 4 quarters (smooths seasonal volatility).  \n"
        "Green: Revenue Growth >20%, Margins >70% (gross) / >20% (operating), "
        "Delta >+2pp, Margin Trend Expanding, Current Ratio >=2x, D/E <=0.5x, ROE >10%, "
        "FCF Yield >5%, P/FCF <15x, Def Rev Growth >20%, Rule of 40 >=40%.  "
        "Red: Growth <5%, Gross Margin <40%, Operating Margin <0%, "
        "Delta <-2pp, Margin Trend Contracting, Current Ratio <1x, D/E >2x or negative, ROE <0%, "
        "FCF Yield <2%, P/FCF >30x or negative, Def Rev Growth <5%, Rule of 40 <20%."
    )

# ---------------------------------------------------------------------------
# PAGE: Company Deep Dive
# ---------------------------------------------------------------------------
elif page == "Company Deep Dive":
    selected = st.sidebar.selectbox("Select Company", company_names)
    df = company_data[selected].copy()

    st.title(f"Company Deep Dive — {selected}")

    # Data freshness for this company
    freshness = analyze_data_freshness(company_data)
    fresh_info = freshness[selected]
    col_info1, col_info2, col_info3 = st.columns(3)
    with col_info1:
        st.info(f"Latest Quarter: **{fresh_info['latest_quarter']}**")
    with col_info2:
        date_str = fresh_info["latest_date"].strftime("%Y-%m-%d") if hasattr(fresh_info["latest_date"], "strftime") else str(fresh_info["latest_date"])[:10]
        st.info(f"As of: **{date_str}**")
    with col_info3:
        age_color = "Fresh" if fresh_info["days_old"] < 30 else ("Aging" if fresh_info["days_old"] < 90 else "Stale")
        st.info(f"Data Age: **{fresh_info['days_old']} days** ({age_color})")

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
        
        st.markdown("---")
    
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
        fig.update_traces(textposition="outside", marker_color="#4A90D9")
        fig.update_layout(yaxis_title="Revenue ($K)", xaxis_title="", showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

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
        fig.update_traces(line_color="#E67E22")
        fig.update_layout(
            yaxis_title="Growth %",
            yaxis_tickformat=".0%",
            xaxis_title="",
        )
        st.plotly_chart(fig, use_container_width=True)

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
                    line=dict(color="#2ECC71"),
                )
            )
        fig.add_trace(
            go.Scatter(
                x=df["Quarter"],
                y=df["Operating_Margin"],
                mode="lines+markers",
                name="Operating Margin",
                line=dict(color="#9B59B6"),
            )
        )
        fig.update_layout(
            yaxis_title="Margin",
            yaxis_tickformat=".0%",
            xaxis_title="",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        )
        st.plotly_chart(fig, use_container_width=True)

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
        fig.update_traces(line_color="#E74C3C")
        fig.update_layout(
            yaxis_title="Delta (pp)",
            yaxis_tickformat=".1%",
            xaxis_title="",
        )
        # Add a zero reference line
        fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
        st.plotly_chart(fig, use_container_width=True)

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
            trend_color = "#0a7c42"
        elif avg_delta < -0.02:
            trend_label = "Contracting"
            trend_color = "#c0392b"
        else:
            trend_label = "Stable"
            trend_color = "#F39C12"
        
        # Display summary
        st.markdown("---")
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
                marker_color=["#0a7c42" if v > 0 else "#c0392b" for v in margin_trend_df["Operating_Margin_Delta_YoY"]],
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
        st.plotly_chart(fig, use_container_width=True)

    # --- TTM Metrics (Smoothed Quarterly Volatility) ---
    if "TTM_Revenue" in df.columns:
        ttm_df = df.dropna(subset=["TTM_Revenue"])
        
        if not ttm_df.empty:
            st.markdown("---")
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
                    line=dict(color="#4A90D9", dash="dot", width=2),
                    marker=dict(size=6),
                ))
                # TTM revenue (solid line)
                fig.add_trace(go.Scatter(
                    x=ttm_df["Quarter"], 
                    y=ttm_df["TTM_Revenue"],
                    mode="lines+markers", 
                    name="TTM (4Q Sum)",
                    line=dict(color="#2ECC71", width=3),
                    marker=dict(size=8),
                ))
                fig.update_layout(
                    yaxis_title="Revenue ($K)", 
                    xaxis_title="",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                )
                st.plotly_chart(fig, use_container_width=True)
            
            with col_ttm2:
                st.subheader("Operating Margin: Quarterly vs TTM")
                fig = go.Figure()
                # Quarterly operating margin (dotted line)
                fig.add_trace(go.Scatter(
                    x=df["Quarter"], 
                    y=df["Operating_Margin"], 
                    mode="lines+markers", 
                    name="Quarterly",
                    line=dict(color="#9B59B6", dash="dot", width=2),
                    marker=dict(size=6),
                ))
                # TTM operating margin (solid line)
                if "TTM_Operating_Margin" in ttm_df.columns:
                    fig.add_trace(go.Scatter(
                        x=ttm_df["Quarter"], 
                        y=ttm_df["TTM_Operating_Margin"],
                        mode="lines+markers", 
                        name="TTM (4Q Avg)",
                        line=dict(color="#E67E22", width=3),
                        marker=dict(size=8),
                    ))
                fig.update_layout(
                    yaxis_title="Operating Margin", 
                    yaxis_tickformat=".0%",
                    xaxis_title="",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                )
                fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
                st.plotly_chart(fig, use_container_width=True)

    # --- Net Debt & ROE charts ---
    has_bs = "Net_Debt" in df.columns and df["Net_Debt"].notna().any()

    if has_bs:
        col5, col6 = st.columns(2)

        with col5:
            st.subheader("Net Debt")
            nd_df = df.dropna(subset=["Net_Debt"])
            colors = ["#c0392b" if v > 0 else "#0a7c42" for v in nd_df["Net_Debt"]]
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
            st.plotly_chart(fig, use_container_width=True)

        with col6:
            st.subheader("Return on Equity (ROE)")
            roe_df = df.dropna(subset=["ROE"])
            if not roe_df.empty:
                fig = px.line(roe_df, x="Quarter", y="ROE", markers=True)
                fig.update_traces(line_color="#8E44AD")
                fig.update_layout(
                    yaxis_title="ROE",
                    yaxis_tickformat=".0%",
                    xaxis_title="",
                )
                fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
                st.plotly_chart(fig, use_container_width=True)
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
            fig.update_traces(textposition="outside", marker_color="#1ABC9C")
            fig.update_layout(yaxis_title="Deferred Revenue ($M)", xaxis_title="", showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

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
                fig.update_traces(line_color="#F39C12")
                fig.update_layout(
                    yaxis_title="Growth %",
                    yaxis_tickformat=".0%",
                    xaxis_title="",
                )
                fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
                st.plotly_chart(fig, use_container_width=True)
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
            fig.update_traces(line_color="#3498DB")
            fig.update_layout(
                yaxis_title="Deferred Rev / Revenue",
                yaxis_tickformat=".2f",
                xaxis_title="",
            )
            st.plotly_chart(fig, use_container_width=True)

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
            line_color = "#27AE60" if avg_rule_40 >= 0.40 else "#E74C3C"
            
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
            st.plotly_chart(fig, use_container_width=True)

    # --- Full data table ---
    st.subheader("Quarterly Data")
    table_df = df.copy()
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
        table_df.style.format(table_fmt).hide(axis="index"),
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
            colors = ["#0a7c42" if v >= 0 else "#c0392b" for v in fcf_plot["Free_Cash_Flow"]]
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
            st.plotly_chart(fig, use_container_width=True)

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
            cf_table.style.format(cf_table_fmt).hide(axis="index"),
            use_container_width=True,
            hide_index=True,
        )

# ---------------------------------------------------------------------------
# PAGE: Peer Comparison
# ---------------------------------------------------------------------------
elif page == "Peer Comparison":
    st.title("Peer Comparison — Most Recent Quarter")

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

    # Build most-recent-quarter comparison frame
    rows = []
    for name, df in company_data.items():
        last = df.iloc[-1]
        val = valuation.get(name, {})
        
        # Calculate 4-quarter average margin trend
        _margin_deltas = df["Operating_Margin_Delta_YoY"].tail(4).dropna()
        _margin_trend_4q = _margin_deltas.mean() if len(_margin_deltas) >= 3 else None
        
        rows.append(
            {
                "Company": name,
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
    st.plotly_chart(fig, use_container_width=True)

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
        marker=dict(size=14, color="#4A90D9"),
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
    st.plotly_chart(fig, use_container_width=True)

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
            "Efficient Scaling": "#0a7c42",      # Green
            "Margin Improvement": "#F39C12",     # Yellow/Orange
            "Growth at Cost": "#E67E22",         # Orange
            "Deteriorating": "#c0392b",          # Red
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
        
        st.plotly_chart(fig, use_container_width=True)
        
        st.caption(
            "Efficiency Scaling Analysis shows which companies are scaling efficiently vs burning more as they grow. "
            "**Efficient Scaling** (green): High growth + expanding margins. "
            "**Margin Improvement** (yellow): Lower growth but improving margins. "
            "**Growth at Cost** (orange): High growth but contracting margins. "
            "**Deteriorating** (red): Low growth + contracting margins."
        )
    else:
        st.info("Not enough data for efficiency scaling analysis (requires both Revenue Growth and Margin Trend data).")
