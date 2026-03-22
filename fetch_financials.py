"""
Fetch financial statement data from SEC EDGAR for any ticker.

Uses the EDGAR Company Facts XBRL API to pull 20+ quarters of history.
Produces DataFrames in the dashboard quarterly-metrics schema (thousands USD,
`YYYY FQn` quarter labels).

Public API:
    fetch_company_financials(ticker) -> (quarterly_df, cashflow_df)
    fetch_peer_set(tickers)          -> (company_data, cashflow_data)
"""

from datetime import datetime
import logging
import os

import numpy as np
import pandas as pd
import requests


# ---------------------------------------------------------------------------
# SEC EDGAR helpers
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# SEC requires an identifiable User-Agent (see https://www.sec.gov/os/webmaster-faq#developers).
# SEC returns 403 unless User-Agent includes a contact (typically an email). Read env on each
# request so Streamlit reruns pick up Secrets without restarting the server.
_DEFAULT_SEC_USER_AGENT = "AtlasEquityResearch/1.0 (atlas-dashboard@example.com)"
_CIK_CACHE: dict = {}


def _sec_user_agent() -> str:
    return os.environ.get("ATLAS_SEC_USER_AGENT", _DEFAULT_SEC_USER_AGENT)


def _sec_headers() -> dict:
    """Required User-Agent header for SEC fair-access policy."""
    return {"User-Agent": _sec_user_agent(), "Accept-Encoding": "gzip, deflate"}


def _ticker_to_cik(ticker: str) -> str:
    """Resolve ticker symbol to zero-padded CIK via SEC's company_tickers.json.

    Result is cached in a module-level dict after first call.
    """
    global _CIK_CACHE
    ticker_upper = ticker.upper()

    if ticker_upper in _CIK_CACHE:
        return _CIK_CACHE[ticker_upper]

    if not _CIK_CACHE:
        r = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=_sec_headers(),
            timeout=15,
        )
        r.raise_for_status()
        for val in r.json().values():
            _CIK_CACHE[val["ticker"].upper()] = str(val["cik_str"]).zfill(10)

    if ticker_upper not in _CIK_CACHE:
        raise ValueError(f"Ticker '{ticker}' not found in SEC database")
    return _CIK_CACHE[ticker_upper]


def _fetch_company_facts(cik: str) -> dict:
    """Fetch the full Company Facts JSON from EDGAR."""
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    r = requests.get(url, headers=_sec_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def _extract_quarterly_values(
    facts: dict,
    concept_names: list,
    instant: bool = False,
) -> dict:
    """Extract deduplicated single-quarter values from EDGAR facts.

    For duration-based items (IS/CF): pulls Q1-Q3 single-quarter values from
    10-Q filings, then derives Q4 = (10-K annual) - (Q1+Q2+Q3).
    For instant items (BS): takes point-in-time values from both 10-Q and 10-K.
    Deduplicates by end-date, keeping the most recently filed entry.

    Returns dict keyed by end-date string -> value (in actual USD).
    """
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    for concept in concept_names:
        if concept not in us_gaap:
            continue
        all_entries = us_gaap[concept].get("units", {}).get("USD", [])
        if not all_entries:
            continue

        if instant:
            # BS items: grab from both 10-Q and 10-K (FY-end balance sheet)
            relevant = [e for e in all_entries if e.get("form") in ("10-Q", "10-K")]
            if not relevant:
                continue
            by_end: dict = {}
            for e in relevant:
                end = e["end"]
                if end not in by_end or e["filed"] > by_end[end]["filed"]:
                    by_end[end] = e
            return {end: e["val"] for end, e in by_end.items()}
        else:
            # Duration items: Q1-Q3 from 10-Q (75-100 day), plus Q4 derived
            q_entries = [e for e in all_entries if e.get("form") == "10-Q"]
            k_entries = [e for e in all_entries if e.get("form") == "10-K"]

            # Extract single-quarter 10-Q values
            q_filtered = []
            for e in q_entries:
                start, end = e.get("start"), e.get("end")
                if start and end:
                    days = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days
                    if 75 <= days <= 100:
                        q_filtered.append(e)

            by_end_q: dict = {}
            for e in q_filtered:
                end = e["end"]
                if end not in by_end_q or e["filed"] > by_end_q[end]["filed"]:
                    by_end_q[end] = e
            result = {end: e["val"] for end, e in by_end_q.items()}

            # Extract annual 10-K values (340-380 day duration)
            k_annual: dict = {}
            for e in k_entries:
                start, end = e.get("start"), e.get("end")
                if start and end:
                    days = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days
                    if 340 <= days <= 380:
                        if end not in k_annual or e["filed"] > k_annual[end]["filed"]:
                            k_annual[end] = e

            # Derive Q4 = Annual - (Q1 + Q2 + Q3)
            for end_str, entry in k_annual.items():
                if end_str in result:
                    continue  # already have this date from 10-Q
                annual_val = entry["val"]
                fy_end = datetime.strptime(end_str, "%Y-%m-%d")
                fy_start = datetime.strptime(entry["start"], "%Y-%m-%d")

                # Find Q1-Q3 values whose end dates fall within this fiscal year
                q123_sum = 0.0
                q123_count = 0
                for q_end_str, q_val in result.items():
                    q_end = datetime.strptime(q_end_str, "%Y-%m-%d")
                    if fy_start < q_end < fy_end:
                        q123_sum += q_val
                        q123_count += 1

                if q123_count >= 2:
                    result[end_str] = annual_val - q123_sum

            if result:
                return result

    return {}


def _extract_annual_values(facts: dict, concept_names: list) -> dict:
    """Extract deduplicated annual (10-K) values from EDGAR facts.

    Filters for full-year duration (340-380 days).
    Returns dict keyed by end-date string -> value (in actual USD).
    """
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    for concept in concept_names:
        if concept not in us_gaap:
            continue
        entries = us_gaap[concept].get("units", {}).get("USD", [])
        k_entries = [e for e in entries if e.get("form") == "10-K"]
        if not k_entries:
            continue

        filtered = []
        for e in k_entries:
            start = e.get("start")
            end = e.get("end")
            if start and end:
                d1 = datetime.strptime(start, "%Y-%m-%d")
                d2 = datetime.strptime(end, "%Y-%m-%d")
                days = (d2 - d1).days
                if 340 <= days <= 380:
                    filtered.append(e)

        if not filtered:
            continue

        by_end: dict = {}
        for e in filtered:
            end = e["end"]
            if end not in by_end or e["filed"] > by_end[end]["filed"]:
                by_end[end] = e

        return {end: e["val"] for end, e in by_end.items()}

    return {}


def _fy_end_month_from_facts(facts: dict) -> int:
    """Derive fiscal-year-end month from the most recent 10-K end date."""
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    for concept in ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                     "Assets", "NetIncomeLoss"]:
        if concept not in us_gaap:
            continue
        entries = us_gaap[concept].get("units", {}).get("USD", [])
        k_entries = [e for e in entries if e.get("form") == "10-K" and e.get("end")]
        if k_entries:
            latest = max(k_entries, key=lambda e: e["end"])
            return datetime.strptime(latest["end"], "%Y-%m-%d").month
    return 12


# ---------------------------------------------------------------------------
# Shared helpers (unchanged from original)
# ---------------------------------------------------------------------------

def _to_thousands(val):
    """Divide by 1000 to convert raw USD from EDGAR into thousands (dashboard convention)."""
    if val is None:
        return None
    return val / 1000.0


def _make_quarter_label(date: pd.Timestamp, fy_end_month: int) -> str:
    """Convert a quarter-end date to fiscal quarter label 'YYYY FQn'.

    FQ4 ends in the fiscal-year-end month.  FQ1 is the first quarter
    *after* the prior FY end.

    Examples (FY end = July, month 7):
        2026-01-31 -> '2026 FQ2'
        2025-07-31 -> '2025 FQ4'
    Calendar year (FY end = December, month 12):
        2025-12-31 -> '2025 FQ4'
        2025-03-31 -> '2025 FQ1'
    """
    month = date.month
    diff = (month - fy_end_month) % 12

    if diff == 0:
        quarter_num = 4
    else:
        quarter_num = ((diff - 1) // 3) + 1

    if month <= fy_end_month:
        fiscal_year = date.year
    else:
        fiscal_year = date.year + 1

    return f"{fiscal_year} FQ{quarter_num}"


def _make_fy_label(date: pd.Timestamp, fy_end_month: int) -> str:
    """Convert an annual period-end date to 'YYYY FY' label."""
    if date.month <= fy_end_month:
        return f"{date.year} FY"
    return f"{date.year + 1} FY"


# ---------------------------------------------------------------------------
# XBRL concept name lists
# ---------------------------------------------------------------------------

_REVENUE_CONCEPTS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
]
_GROSS_PROFIT_CONCEPTS = ["GrossProfit"]
_OPERATING_INCOME_CONCEPTS = ["OperatingIncomeLoss"]
_NET_INCOME_CONCEPTS = ["NetIncomeLoss", "ProfitLoss"]
_CASH_CONCEPTS = [
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsAndShortTermInvestments",
]
_TOTAL_DEBT_CONCEPTS = [
    "LongTermDebt",
    "LongTermDebtAndCapitalLeaseObligations",
]
_TOTAL_DEBT_FALLBACK_CONCEPTS = [
    ("LongTermDebtNoncurrent", "LongTermDebtCurrent", "ConvertibleLongTermNotesPayable"),
]
_EQUITY_CONCEPTS = [
    "StockholdersEquity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
]
_CURRENT_ASSETS_CONCEPTS = ["AssetsCurrent"]
_CURRENT_LIABILITIES_CONCEPTS = ["LiabilitiesCurrent"]
_TOTAL_ASSETS_CONCEPTS = ["Assets"]
_DEFERRED_REV_CURRENT_CONCEPTS = [
    "ContractWithCustomerLiabilityCurrent",
    "DeferredRevenueCurrent",
]
_DEFERRED_REV_NONCURRENT_CONCEPTS = [
    "ContractWithCustomerLiabilityNoncurrent",
    "DeferredRevenueNoncurrent",
]
_OCF_CONCEPTS = ["NetCashProvidedByUsedInOperatingActivities"]
_CAPEX_CONCEPTS = [
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
]


# ---------------------------------------------------------------------------
# Core: fetch_company_financials
# ---------------------------------------------------------------------------

def fetch_company_financials(ticker: str, max_quarters: int = 12):
    """Fetch quarterly metrics and annual cashflow for one ticker via EDGAR.

    Args:
        ticker: Stock ticker symbol
        max_quarters: Maximum number of quarterly periods to keep (default: 12).

    Returns:
        (quarterly_df, cashflow_df) in the dashboard metrics schema,
        or (None, None) on failure.
    """
    try:
        cik = _ticker_to_cik(ticker)
        facts = _fetch_company_facts(cik)
        fy_month = _fy_end_month_from_facts(facts)
    except Exception as e:
        logger.warning("[%s] Failed to fetch EDGAR data: %s", ticker, e)
        return None, None

    # ------------------------------------------------------------------
    # 1. Extract quarterly values from EDGAR XBRL
    # ------------------------------------------------------------------
    revenue_q = _extract_quarterly_values(facts, _REVENUE_CONCEPTS)
    if not revenue_q:
        print(f"  [{ticker}] No quarterly revenue data in EDGAR.")
        return None, None

    gross_profit_q = _extract_quarterly_values(facts, _GROSS_PROFIT_CONCEPTS)
    operating_income_q = _extract_quarterly_values(facts, _OPERATING_INCOME_CONCEPTS)
    net_income_q = _extract_quarterly_values(facts, _NET_INCOME_CONCEPTS)

    cash_q = _extract_quarterly_values(facts, _CASH_CONCEPTS, instant=True)
    equity_q = _extract_quarterly_values(facts, _EQUITY_CONCEPTS, instant=True)
    current_assets_q = _extract_quarterly_values(facts, _CURRENT_ASSETS_CONCEPTS, instant=True)
    current_liabilities_q = _extract_quarterly_values(facts, _CURRENT_LIABILITIES_CONCEPTS, instant=True)
    total_assets_q = _extract_quarterly_values(facts, _TOTAL_ASSETS_CONCEPTS, instant=True)

    # Total debt: try single-concept first, fall back to summing components
    total_debt_q = _extract_quarterly_values(facts, _TOTAL_DEBT_CONCEPTS, instant=True)
    if not total_debt_q:
        for component_tuple in _TOTAL_DEBT_FALLBACK_CONCEPTS:
            component_vals = {}
            for comp_name in component_tuple:
                comp_data = _extract_quarterly_values(facts, [comp_name], instant=True)
                for end_date, val in comp_data.items():
                    component_vals[end_date] = component_vals.get(end_date, 0) + val
            if component_vals:
                total_debt_q = component_vals
                break

    dr_current_q = _extract_quarterly_values(facts, _DEFERRED_REV_CURRENT_CONCEPTS, instant=True)
    dr_noncurrent_q = _extract_quarterly_values(facts, _DEFERRED_REV_NONCURRENT_CONCEPTS, instant=True)

    # ------------------------------------------------------------------
    # 2. Build quarterly DataFrame keyed by revenue dates
    # ------------------------------------------------------------------
    all_dates = sorted(revenue_q.keys())
    if len(all_dates) > max_quarters:
        all_dates = all_dates[-max_quarters:]

    rows = []
    for end_date_str in all_dates:
        dt = pd.Timestamp(end_date_str)
        rev_val = revenue_q[end_date_str]

        row = {}
        row["Date"] = dt
        row["Quarter"] = _make_quarter_label(dt, fy_month)
        row["Revenue"] = _to_thousands(rev_val)
        row["Gross_Profit"] = _to_thousands(gross_profit_q.get(end_date_str)) if end_date_str in gross_profit_q else np.nan
        row["Operating_Income"] = _to_thousands(operating_income_q.get(end_date_str)) if end_date_str in operating_income_q else np.nan
        row["Net_Income"] = _to_thousands(net_income_q.get(end_date_str)) if end_date_str in net_income_q else np.nan

        row["Cash"] = _to_thousands(cash_q.get(end_date_str)) if end_date_str in cash_q else np.nan
        row["Total_Debt"] = _to_thousands(total_debt_q.get(end_date_str)) if end_date_str in total_debt_q else np.nan
        row["Total_Equity"] = _to_thousands(equity_q.get(end_date_str)) if end_date_str in equity_q else np.nan
        row["Current_Assets"] = _to_thousands(current_assets_q.get(end_date_str)) if end_date_str in current_assets_q else np.nan
        row["Current_Liabilities"] = _to_thousands(current_liabilities_q.get(end_date_str)) if end_date_str in current_liabilities_q else np.nan
        row["Total_Assets"] = _to_thousands(total_assets_q.get(end_date_str)) if end_date_str in total_assets_q else np.nan

        dr_curr = _to_thousands(dr_current_q.get(end_date_str)) if end_date_str in dr_current_q else 0.0
        dr_nc = _to_thousands(dr_noncurrent_q.get(end_date_str)) if end_date_str in dr_noncurrent_q else 0.0
        dr_total = (dr_curr or 0.0) + (dr_nc or 0.0)
        row["Deferred_Revenue"] = dr_total if dr_total > 0 else np.nan

        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        print(f"  [{ticker}] No rows produced.")
        return None, None

    # ------------------------------------------------------------------
    # 3. Derived margins, YoY deltas, and ratios
    # ------------------------------------------------------------------
    df["Gross_Margin"] = df["Gross_Profit"] / df["Revenue"].replace(0, np.nan)
    df["Operating_Margin"] = df["Operating_Income"] / df["Revenue"].replace(0, np.nan)

    df["Revenue_Growth_YoY"] = np.nan
    df["Gross_Margin_Delta_YoY"] = np.nan
    df["Operating_Margin_Delta_YoY"] = np.nan

    for i in range(4, len(df)):
        prev = i - 4
        prev_rev = df.loc[df.index[prev], "Revenue"]
        if pd.notna(prev_rev) and prev_rev != 0:
            df.loc[df.index[i], "Revenue_Growth_YoY"] = (
                (df.loc[df.index[i], "Revenue"] - prev_rev) / abs(prev_rev)
            )
        prev_gm = df.loc[df.index[prev], "Gross_Margin"]
        if pd.notna(prev_gm):
            df.loc[df.index[i], "Gross_Margin_Delta_YoY"] = (
                df.loc[df.index[i], "Gross_Margin"] - prev_gm
            )
        prev_om = df.loc[df.index[prev], "Operating_Margin"]
        if pd.notna(prev_om):
            df.loc[df.index[i], "Operating_Margin_Delta_YoY"] = (
                df.loc[df.index[i], "Operating_Margin"] - prev_om
            )

    df["Net_Debt"] = df["Total_Debt"] - df["Cash"]
    df["Debt_to_Equity"] = df["Total_Debt"] / df["Total_Equity"].replace(0, np.nan)
    df["Current_Ratio"] = df["Current_Assets"] / df["Current_Liabilities"].replace(0, np.nan)
    df["ROE"] = df["Net_Income"] / df["Total_Equity"].replace(0, np.nan)
    df["Asset_Turnover"] = df["Revenue"] / df["Total_Assets"].replace(0, np.nan)
    df["Revenue_Recognition_Quality"] = df["Deferred_Revenue"] / df["Revenue"].replace(0, np.nan)

    df["Deferred_Revenue_Growth_YoY"] = np.nan
    for i in range(4, len(df)):
        prev_dr = df.loc[df.index[i - 4], "Deferred_Revenue"]
        curr_dr = df.loc[df.index[i], "Deferred_Revenue"]
        if pd.notna(prev_dr) and pd.notna(curr_dr) and prev_dr != 0:
            df.loc[df.index[i], "Deferred_Revenue_Growth_YoY"] = (
                (curr_dr - prev_dr) / abs(prev_dr)
            )

    ratio_cols = [
        "Net_Debt", "Debt_to_Equity", "Current_Ratio", "ROE", "Asset_Turnover",
        "Revenue_Recognition_Quality", "Deferred_Revenue_Growth_YoY",
    ]
    df[ratio_cols] = df[ratio_cols].replace([np.inf, -np.inf], np.nan)

    # ------------------------------------------------------------------
    # 4. TTM metrics (4-quarter rolling sums)
    # ------------------------------------------------------------------
    df["TTM_Revenue"] = df["Revenue"].rolling(window=4, min_periods=4).sum()
    df["TTM_Gross_Profit"] = df["Gross_Profit"].rolling(window=4, min_periods=4).sum()
    df["TTM_Operating_Income"] = df["Operating_Income"].rolling(window=4, min_periods=4).sum()
    df["TTM_Gross_Margin"] = df["TTM_Gross_Profit"] / df["TTM_Revenue"].replace(0, np.nan)
    df["TTM_Operating_Margin"] = df["TTM_Operating_Income"] / df["TTM_Revenue"].replace(0, np.nan)
    if "Net_Income" in df.columns:
        df["TTM_Net_Income"] = df["Net_Income"].rolling(window=4, min_periods=4).sum()

    # Format Date to string
    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")

    # Stable column order for the dashboard and PDF export
    col_order = [
        "Quarter", "Date", "Revenue", "Gross_Profit", "Operating_Income", "Net_Income",
        "Gross_Margin", "Operating_Margin", "Revenue_Growth_YoY",
        "Gross_Margin_Delta_YoY", "Operating_Margin_Delta_YoY",
        "Cash", "Total_Debt", "Total_Equity", "Current_Assets",
        "Current_Liabilities", "Total_Assets", "Deferred_Revenue",
        "Net_Debt", "Debt_to_Equity", "Current_Ratio", "ROE", "Asset_Turnover",
        "Revenue_Recognition_Quality", "Deferred_Revenue_Growth_YoY",
        "TTM_Revenue", "TTM_Gross_Profit", "TTM_Operating_Income",
        "TTM_Gross_Margin", "TTM_Operating_Margin", "TTM_Net_Income",
    ]
    for c in col_order:
        if c not in df.columns:
            df[c] = np.nan
    df = df[col_order].reset_index(drop=True)

    # ------------------------------------------------------------------
    # 5. Annual cashflow DataFrame
    # ------------------------------------------------------------------
    cashflow_df = _build_cashflow_df(facts, df, fy_month)

    return df, cashflow_df


# ---------------------------------------------------------------------------
# Cashflow builder
# ---------------------------------------------------------------------------

def _build_cashflow_df(facts: dict, quarterly_df: pd.DataFrame, fy_end_month: int):
    """Build the annual cashflow DataFrame from EDGAR 10-K data."""
    ocf_annual = _extract_annual_values(facts, _OCF_CONCEPTS)
    capex_annual = _extract_annual_values(facts, _CAPEX_CONCEPTS)

    if not ocf_annual:
        return None

    all_dates = sorted(set(ocf_annual.keys()) | set(capex_annual.keys()))
    rows = []
    for end_date_str in all_dates:
        dt = pd.Timestamp(end_date_str)
        row = {}
        row["Quarter"] = _make_fy_label(dt, fy_end_month)
        row["Date"] = end_date_str

        ocf_val = _to_thousands(ocf_annual.get(end_date_str))
        row["Operating_Cash_Flow"] = ocf_val if ocf_val is not None else np.nan

        capex_val = _to_thousands(capex_annual.get(end_date_str))
        if capex_val is not None and capex_val > 0:
            capex_val = -capex_val
        row["CapEx"] = capex_val if capex_val is not None else np.nan

        if pd.notna(row["Operating_Cash_Flow"]) and pd.notna(row["CapEx"]):
            row["Free_Cash_Flow"] = row["Operating_Cash_Flow"] + row["CapEx"]
        else:
            row["Free_Cash_Flow"] = np.nan

        fy_label = row["Quarter"]
        year_prefix = fy_label.split()[0]
        q_mask = quarterly_df["Quarter"].str.startswith(year_prefix + " FQ")
        matching_rev = quarterly_df.loc[q_mask, "Revenue"]
        if len(matching_rev) == 4 and matching_rev.notna().all():
            row["Annual_Revenue"] = matching_rev.sum()
        else:
            fq4_label = f"{year_prefix} FQ4"
            fq4_mask = quarterly_df["Quarter"] == fq4_label
            fq4_rows = quarterly_df.loc[fq4_mask, "TTM_Revenue"]
            if not fq4_rows.empty and pd.notna(fq4_rows.iloc[0]):
                row["Annual_Revenue"] = fq4_rows.iloc[0]
            else:
                row["Annual_Revenue"] = np.nan

        if pd.notna(row["Free_Cash_Flow"]) and pd.notna(row["Annual_Revenue"]) and row["Annual_Revenue"] != 0:
            row["FCF_Margin"] = row["Free_Cash_Flow"] / row["Annual_Revenue"]
        else:
            row["FCF_Margin"] = np.nan

        rows.append(row)

    if not rows:
        return None

    cf_df = pd.DataFrame(rows)
    col_order = ["Quarter", "Date", "Operating_Cash_Flow", "CapEx",
                 "Free_Cash_Flow", "Annual_Revenue", "FCF_Margin"]
    for c in col_order:
        if c not in cf_df.columns:
            cf_df[c] = np.nan
    return cf_df[col_order]


# ---------------------------------------------------------------------------
# fetch_peer_set
# ---------------------------------------------------------------------------

def fetch_peer_set(tickers: list, max_quarters: int = 12):
    """Fetch financials for multiple tickers.

    Args:
        tickers: List of ticker symbols
        max_quarters: Maximum number of quarterly periods to keep (default: 12)

    Returns:
        (company_data, cashflow_data) — dicts keyed by ticker symbol, suitable for
        the dashboard’s `company_data` / `cashflow_data` session state.
    """
    company_data = {}
    cashflow_data = {}
    for ticker in tickers:
        print(f"\nFetching {ticker}...")
        q_df, cf_df = fetch_company_financials(ticker, max_quarters=max_quarters)
        if q_df is not None:
            company_data[ticker] = q_df
        if cf_df is not None:
            cashflow_data[ticker] = cf_df
    return company_data, cashflow_data


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

def main():
    test_tickers = ["NTNX", "NET", "CRWD"]

    pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 220)

    for ticker in test_tickers:
        print(f"\n{'='*80}")
        print(f"  {ticker}")
        print(f"{'='*80}")

        q_df, cf_df = fetch_company_financials(ticker)

        if q_df is None:
            print("  FAILED — no data returned")
            continue

        last = q_df.iloc[-1]
        print(f"\n  Latest Quarter:     {last['Quarter']}")
        print(f"  Date:               {last['Date']}")
        print(f"  Revenue ($K):       {last['Revenue']:>12,.0f}   (${last['Revenue']/1000:,.1f}M)")
        print(f"  Gross Margin:       {last['Gross_Margin']:.2%}" if pd.notna(last["Gross_Margin"]) else "  Gross Margin:       N/A")
        print(f"  Operating Margin:   {last['Operating_Margin']:.2%}" if pd.notna(last["Operating_Margin"]) else "  Operating Margin:   N/A")
        print(f"  Rev Growth YoY:     {last['Revenue_Growth_YoY']:.2%}" if pd.notna(last["Revenue_Growth_YoY"]) else "  Rev Growth YoY:     N/A")

        # Unit sanity check
        rev_k = last["Revenue"]
        if pd.notna(rev_k):
            if rev_k > 1_000_000_000:
                print(f"  *** WARNING: Revenue {rev_k:,.0f} looks like actual USD, not thousands! ***")
            elif rev_k < 1_000:
                print(f"  *** WARNING: Revenue {rev_k:,.0f} looks like millions, not thousands! ***")
            else:
                print(f"  Unit check:         OK (value in thousands)")

        print(f"\n  Total quarters:     {len(q_df)}")
        print(f"  Columns ({len(q_df.columns)}): {list(q_df.columns)}")
        print(f"\n  Quarterly data ({len(q_df)} rows):")
        print(q_df[["Quarter", "Date", "Revenue", "Gross_Margin",
                     "Operating_Margin", "Revenue_Growth_YoY"]].to_string(index=False))

        if cf_df is not None and not cf_df.empty:
            print(f"\n  Annual Cash Flow ({len(cf_df)} rows):")
            print(cf_df.to_string(index=False))
        else:
            print("\n  No annual cash flow data.")

    print(f"\n{'='*80}")
    print("  Validation complete.")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
