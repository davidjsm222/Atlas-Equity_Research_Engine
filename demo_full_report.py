#!/usr/bin/env python3
"""
Demo: Generate Complete PDF Report with All Sections

This script demonstrates how to use the PDFReport class to generate
a complete equity research PDF with:
- Cover page
- Overview section (peer comparison tables)
- Deep Dive sections (KPI cards + 6 charts per company)

Usage:
    python3 demo_full_report.py
"""

import glob
import os
import pandas as pd
from pdf_generator import PDFReport


def load_data():
    """Load all company data from processed_data directory."""
    DATA_DIR = "processed_data"
    
    # Load quarterly metrics
    files = sorted(glob.glob(os.path.join(DATA_DIR, "*_quarterly_metrics.csv")))
    company_data = {}
    for f in files:
        basename = os.path.basename(f)
        company_name = basename.replace("_quarterly_metrics.csv", "")
        df = pd.read_csv(f)
        company_data[company_name] = df
    
    # Load cashflow data
    cf_files = sorted(glob.glob(os.path.join(DATA_DIR, "*_annual_cashflow.csv")))
    cashflow_data = {}
    for f in cf_files:
        basename = os.path.basename(f)
        company_name = basename.replace("_annual_cashflow.csv", "")
        df = pd.read_csv(f)
        cashflow_data[company_name] = df
    
    return company_data, cashflow_data


def compute_valuation(company_data, cashflow_data):
    """Compute valuation metrics for each company."""
    valuation = {}
    
    for company, df in company_data.items():
        if df.empty:
            continue
        
        cf_df = cashflow_data.get(company)
        last = df.iloc[-1]
        
        # Basic valuation metrics
        price = last.get("Stock_Price", 0)
        shares = last.get("Diluted_Shares_Outstanding", 0)
        market_cap = price * shares if price and shares else 0
        revenue_ttm = last.get("Revenue")
        
        # FCF metrics
        fcf_margin = None
        fcf_ttm = None
        if cf_df is not None and not cf_df.empty:
            fcf_margin = cf_df.iloc[-1].get("FCF_Margin")
            fcf_ttm = cf_df.iloc[-1].get("Free_Cash_Flow")
        
        # Revenue growth
        rev_growth = last.get("Revenue_Growth_YoY")
        
        # Rule of 40
        rule_of_40 = None
        if rev_growth is not None and fcf_margin is not None:
            rule_of_40 = rev_growth + fcf_margin
        
        # EV/Revenue
        ev_revenue = None
        if revenue_ttm and revenue_ttm > 0:
            # Simplified: assume EV ≈ market cap (no net debt adjustment)
            ev_revenue = market_cap / revenue_ttm
        
        # P/FCF
        p_fcf = None
        if fcf_ttm and fcf_ttm > 0:
            p_fcf = market_cap / fcf_ttm
        
        # FCF Yield
        fcf_yield = None
        if market_cap and fcf_ttm and market_cap > 0:
            fcf_yield = fcf_ttm / market_cap
        
        valuation[company] = {
            "Market_Cap": market_cap,
            "EV_Revenue": ev_revenue,
            "Rule_of_40": rule_of_40,
            "P_FCF": p_fcf,
            "FCF_Yield": fcf_yield,
        }
    
    return valuation


def main():
    print("=" * 70)
    print("ATLAS 1.1 — PDF Report Generator Demo")
    print("=" * 70)
    
    # Load data
    print("\n[1/4] Loading company data...")
    company_data, cashflow_data = load_data()
    print(f"      Loaded {len(company_data)} companies")
    
    # Compute valuation
    print("[2/4] Computing valuation metrics...")
    valuation = compute_valuation(company_data, cashflow_data)
    
    # Select companies for report
    all_companies = list(company_data.keys())
    selected_companies = all_companies[:3]  # First 3 companies
    print(f"[3/4] Selected {len(selected_companies)} companies:")
    for i, company in enumerate(selected_companies, 1):
        print(f"      {i}. {company}")
    
    # Generate PDF
    print("[4/4] Generating PDF report...")
    report = PDFReport(
        company_data=company_data,
        cashflow_data=cashflow_data,
        valuation=valuation,
        selected_companies=selected_companies,
        sections=["overview", "deep_dive"]  # Include both sections
    )
    
    output_file = "atlas_full_report.pdf"
    report.build(output_file)
    
    print("\n" + "=" * 70)
    print(f"✓ Report generated: {output_file}")
    
    # Show file info
    if os.path.exists(output_file):
        file_size = os.path.getsize(output_file)
        print(f"  File size: {file_size:,} bytes")
        print(f"\nReport Contents:")
        print(f"  • Cover page with peer set")
        print(f"  • Overview section (2 comparison tables)")
        print(f"  • {len(selected_companies)} Deep Dive sections (KPI cards + 6 charts each)")
    
    print("\n" + "=" * 70)
    print("\nNote: If charts appear as fallback messages, this is due to kaleido")
    print("      environment issues (see KALEIDO_NOTE.md for details).")
    print("=" * 70)


if __name__ == "__main__":
    main()
