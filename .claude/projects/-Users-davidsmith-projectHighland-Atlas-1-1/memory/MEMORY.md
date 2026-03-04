# Atlas 1.1 — Project Memory

## Project Overview
Financial data parser for CapIQ/SNL Financial exports. Parses income statements, balance sheets, and cash flow statements from Excel files into CSV datasets in `processed_data/`.

## Key Files
- [parse_capiq_data.py](parse_capiq_data.py) — main parser (income statement, balance sheet, cash flow)
- [CapIQ Exports/](CapIQ%20Exports/) — raw Excel exports from S&P Global CapIQ / SNL Financial
- [processed_data/](processed_data/) — output CSVs and metadata JSONs
- [ticker_mapping.csv](ticker_mapping.csv) — ticker/company name mapping

## Parser Architecture
- `detect_capiq_units(ws)` — detects "Thousands"/"Millions" from header
- `parse_capiq_income_statement()` — revenue, gross profit, operating income, net income + YoY metrics
- `parse_capiq_balance_sheet()` — cash, debt, equity, assets; current assets/liabilities are **optional**
- `parse_capiq_cashflow()` — OCF, CapEx (sums multiple rows, first-occurrence dedup)
- `main()` — orchestrates all three parsers, merges, calculates ratios, saves CSVs

## Two CapIQ Export Formats
1. **Standard CapIQ format**: Uses "Units"/"Thousands" row; date row label = "Period Ended"
2. **SNL Financial format**: Uses "(in thousands)" inline in col A; date row label = "As Of Date"; period header starts with "Recommended:"

Both formats are now supported.

## REIT-Specific Handling
- REITs (Americold, DigitalRealty, PublicStorage) do not have current assets/liabilities or gross profit sections
- `current_assets` and `current_liabilities` are **optional** in balance sheet parser (fallback to NaN)
- `Current_Ratio` in main() uses `pd.to_numeric(errors='coerce')` to handle NaN columns
- "Income before income taxes" added as low-priority fallback for operating_income (used by PublicStorage)

## Debugging Tips
- Run with `--debug` flag to print all row labels found in column A
- Pass specific file paths as arguments to test a single company
- Use `python3 parse_capiq_data.py --debug "CapIQ Exports/SPGlobal_Company_IncomeStatement..."`

## Datasets Processed (as of Feb 2026)
- **Screener1 branch**: REITs — Americold, DigitalRealty, IronMountain, PublicStorage
- Previous datasets (now deleted from branch): Celestica, Flex, Jabil, TD SYNNEX, Intuitive Surgical, Medtronic, Stryker, ZimmerBiomet

## Common Label Variations (parser supports these)
See `parse_capiq_data.py` for full lists. Notable additions for REITs:
- Cash: "Cash, cash equivalents, and restricted cash"
- Equity: "Total (Deficit) Equity", "Total equity"
- Debt: "Notes payable", "Senior unsecured notes and term loans - net of deferred financing costs", "Unsecured senior notes, net of discount", etc.
- OCF: "Net cash provided by operating activities", "Net cash flows from operating activities"
- CapEx: "Additions to property, buildings, and equipment", "Capital expenditures", "Improvements to investments in real estate", PublicStorage split CapEx labels
