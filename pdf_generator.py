"""
PDF Report Generator — Multi-section equity research reports with ReportLab PLATYPUS.

Usage:
    from pdf_generator import PDFReport
    
    report = PDFReport(
        company_data=company_data,
        cashflow_data=cashflow_data,
        valuation=valuation,
        selected_companies=["Company A", "Company B"],
        sections=["overview", "screener", "deep_dive"]
    )
    report.build("output_report.pdf")
"""

from datetime import datetime
from typing import Dict, List, Callable
import io
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image, Table, TableStyle, KeepTogether
from reportlab.platypus.flowables import Flowable
from reportlab.lib.colors import Color, black
from reportlab.lib import colors


# ---------------------------------------------------------------------------
# Color Constants (matching dashboard.py lines 141-148)
# ---------------------------------------------------------------------------
COLORS = {
    "bg_primary": "#0B0B0B",
    "bg_panel": "#111111",
    "text_primary": "#EAEAEA",
    "text_muted": "#A0A0A0",
    "accent": "#FFB000",
    "positive": "#00FF00",
    "negative": "#FF0000",
}


def hex_to_rgb(hex_color: str) -> Color:
    """Convert hex color string to ReportLab Color object."""
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0
    return Color(r, g, b)


def _fmt_company_name(name):
    """Format company name by adding spaces before capital letters."""
    import re
    # Add space between lowercase and uppercase
    name = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
    # Add space before sequences of caps followed by caps+lowercase (e.g. TDSYNNEXCorp)
    name = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', name)
    # Fix "Inc." "Ltd." "Corp." spacing
    name = re.sub(r'([a-zA-Z])(Inc\.|Ltd\.|Corp\.)', r'\1 \2', name)
    return name.strip()


# ---------------------------------------------------------------------------
# Format Functions (matching dashboard.py lines 470-558)
# ---------------------------------------------------------------------------
def fmt_pct(v):
    """Format value as percentage."""
    if pd.isna(v):
        return "N/A"
    return f"{v:.1%}"


def fmt_revenue(v):
    """Format revenue value (in thousands) as millions."""
    if pd.isna(v):
        return "N/A"
    return f"${v / 1_000:,.1f}M"


def fmt_ratio(v):
    """Format value as ratio with 'x' suffix."""
    if pd.isna(v):
        return "N/A"
    return f"{v:.1f}x"


def fmt_millions(v):
    """Format CapIQ values (in thousands) as millions."""
    if pd.isna(v):
        return "N/A"
    return f"${v / 1_000:,.1f}M"


def fmt_price(v):
    """Format price as currency."""
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


# ---------------------------------------------------------------------------
# Color Threshold Functions (matching dashboard.py lines 482-632)
# ---------------------------------------------------------------------------
def _get_color_for_revenue_growth(v):
    """Return ReportLab Color for revenue growth value. >20% green, <5% red."""
    if pd.isna(v):
        return hex_to_rgb(COLORS["text_primary"])
    if v > 0.20:
        return hex_to_rgb(COLORS["positive"])
    if v < 0.05:
        return hex_to_rgb(COLORS["negative"])
    return hex_to_rgb(COLORS["text_primary"])


def _get_color_for_margin(v):
    """Gross margin: >70% green, <40% red."""
    if pd.isna(v):
        return hex_to_rgb(COLORS["text_primary"])
    if v > 0.70:
        return hex_to_rgb(COLORS["positive"])
    if v < 0.40:
        return hex_to_rgb(COLORS["negative"])
    return hex_to_rgb(COLORS["text_primary"])


def _get_color_for_op_margin(v):
    """Operating margin: >20% green, <0% red."""
    if pd.isna(v):
        return hex_to_rgb(COLORS["text_primary"])
    if v > 0.20:
        return hex_to_rgb(COLORS["positive"])
    if v < 0.0:
        return hex_to_rgb(COLORS["negative"])
    return hex_to_rgb(COLORS["text_primary"])


def _get_color_for_delta(v):
    """Margin delta: >2% green, <-2% red."""
    if pd.isna(v):
        return hex_to_rgb(COLORS["text_primary"])
    if v > 0.02:
        return hex_to_rgb(COLORS["positive"])
    if v < -0.02:
        return hex_to_rgb(COLORS["negative"])
    return hex_to_rgb(COLORS["text_primary"])


def _get_color_for_margin_trend(v):
    """Margin trend: Expanding green, Contracting red."""
    if pd.isna(v) or v == "" or v == "N/A":
        return hex_to_rgb(COLORS["text_primary"])
    if v == "Expanding":
        return hex_to_rgb(COLORS["positive"])
    if v == "Contracting":
        return hex_to_rgb(COLORS["negative"])
    return hex_to_rgb(COLORS["text_primary"])


def _get_color_for_fcf_yield(v):
    """FCF Yield: >5% green, <2% red."""
    if pd.isna(v):
        return hex_to_rgb(COLORS["text_primary"])
    if v > 0.05:
        return hex_to_rgb(COLORS["positive"])
    if v < 0.02:
        return hex_to_rgb(COLORS["negative"])
    return hex_to_rgb(COLORS["text_primary"])


def _get_color_for_p_fcf(v):
    """P/FCF: <15 green, >30 red, <0 red."""
    if pd.isna(v):
        return hex_to_rgb(COLORS["text_primary"])
    if v < 0:
        return hex_to_rgb(COLORS["negative"])
    if v < 15:
        return hex_to_rgb(COLORS["positive"])
    if v > 30:
        return hex_to_rgb(COLORS["negative"])
    return hex_to_rgb(COLORS["text_primary"])


def _get_color_for_current_ratio(v):
    """Current Ratio: >=2.0 green, <1.0 red."""
    if pd.isna(v):
        return hex_to_rgb(COLORS["text_primary"])
    if v >= 2.0:
        return hex_to_rgb(COLORS["positive"])
    if v < 1.0:
        return hex_to_rgb(COLORS["negative"])
    return hex_to_rgb(COLORS["text_primary"])


def _get_color_for_roe(v):
    """ROE: >10% green, <0% red."""
    if pd.isna(v):
        return hex_to_rgb(COLORS["text_primary"])
    if v > 0.10:
        return hex_to_rgb(COLORS["positive"])
    if v < 0:
        return hex_to_rgb(COLORS["negative"])
    return hex_to_rgb(COLORS["text_primary"])


def _get_color_for_debt_to_equity(v):
    """Debt/Equity: <=0.5 green, >2.0 red, <0 red."""
    if pd.isna(v):
        return hex_to_rgb(COLORS["text_primary"])
    if v < 0:
        return hex_to_rgb(COLORS["negative"])
    if v > 2.0:
        return hex_to_rgb(COLORS["negative"])
    if v <= 0.5:
        return hex_to_rgb(COLORS["positive"])
    return hex_to_rgb(COLORS["text_primary"])


def _get_color_for_deferred_rev_growth(v):
    """Deferred Revenue Growth: >20% green, <5% red."""
    if pd.isna(v):
        return hex_to_rgb(COLORS["text_primary"])
    if v > 0.20:
        return hex_to_rgb(COLORS["positive"])
    if v < 0.05:
        return hex_to_rgb(COLORS["negative"])
    return hex_to_rgb(COLORS["text_primary"])


def _get_color_for_rule_of_40(v):
    """Rule of 40: >=40% green, <20% red."""
    if pd.isna(v):
        return hex_to_rgb(COLORS["text_primary"])
    if v >= 0.40:
        return hex_to_rgb(COLORS["positive"])
    if v < 0.20:
        return hex_to_rgb(COLORS["negative"])
    return hex_to_rgb(COLORS["text_primary"])


def apply_terminal_chart_theme(fig):
    """Apply Bloomberg Terminal theme to Plotly chart."""
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Courier New, monospace", size=10, color="#EAEAEA"),
        xaxis=dict(
            gridcolor="#333333",
            gridwidth=1,
            showgrid=True,
            zeroline=False,
        ),
        yaxis=dict(
            gridcolor="#333333",
            gridwidth=1,
            showgrid=True,
            zeroline=False,
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            bordercolor="#333333",
            borderwidth=1,
            font=dict(size=9),
        ),
        margin=dict(l=40, r=20, t=20, b=40),
    )
    return fig


class DarkBackground(Flowable):
    """Custom flowable to draw a dark background rectangle."""
    
    def __init__(self, width, height, color):
        Flowable.__init__(self)
        self.width = width
        self.height = height
        self.color = color
    
    def draw(self):
        self.canv.setFillColor(self.color)
        self.canv.rect(0, 0, self.width, self.height, fill=1, stroke=0)


class PDFReport:
    """Generate multi-section equity research PDF with dark terminal styling."""
    
    def __init__(
        self,
        company_data: Dict[str, pd.DataFrame],
        cashflow_data: Dict[str, pd.DataFrame],
        valuation: Dict[str, Dict],
        selected_companies: List[str],
        sections: List[str],
        # Screener filter parameters (optional)
        rule_of_40_min: float = 40.0,
        revenue_growth_min: float = 15.0,
        p_fcf_max: float = 30.0,
        fcf_yield_min: float = 3.0,
        margin_trend_filter: str = "Expanding"
    ):
        """
        Initialize PDF report generator.
        
        Args:
            company_data: Dict mapping company name → DataFrame (quarterly metrics)
            cashflow_data: Dict mapping company name → DataFrame (annual cashflow)
            valuation: Dict mapping company name → Dict (valuation metrics)
            selected_companies: List of company names to include
            sections: List of section names from ["overview", "screener", "deep_dive"]
            rule_of_40_min: Minimum Rule of 40 threshold (default: 40%)
            revenue_growth_min: Minimum revenue growth YoY (default: 15%)
            p_fcf_max: Maximum P/FCF ratio (default: 30x)
            fcf_yield_min: Minimum FCF yield (default: 3%)
            margin_trend_filter: Margin trend filter ("Any", "Expanding", "Stable or Expanding")
        """
        self.company_data = company_data
        self.cashflow_data = cashflow_data
        self.valuation = valuation
        self.selected_companies = selected_companies
        self.sections = sections
        
        # Screener filter parameters
        self.rule_of_40_min = rule_of_40_min
        self.revenue_growth_min = revenue_growth_min
        self.p_fcf_max = p_fcf_max
        self.fcf_yield_min = fcf_yield_min
        self.margin_trend_filter = margin_trend_filter
        
        # Define paragraph styles
        self._define_styles()
    
    def _define_styles(self):
        """Define custom paragraph styles for dark theme."""
        # Title style: Amber, Courier Bold, 24pt
        self.title_style = ParagraphStyle(
            "CustomTitle",
            fontName="Courier-Bold",
            fontSize=24,
            textColor=hex_to_rgb(COLORS["accent"]),
            alignment=TA_CENTER,
            spaceAfter=12,
        )
        
        # Heading style: Amber, Courier Bold, 14pt
        self.heading_style = ParagraphStyle(
            "CustomHeading",
            fontName="Courier-Bold",
            fontSize=14,
            textColor=hex_to_rgb(COLORS["accent"]),
            alignment=TA_LEFT,
            spaceAfter=8,
            spaceBefore=12,
        )
        
        # Body style: Light gray, Courier, 10pt
        self.body_style = ParagraphStyle(
            "CustomBody",
            fontName="Courier",
            fontSize=10,
            textColor=hex_to_rgb(COLORS["text_primary"]),
            alignment=TA_LEFT,
            spaceAfter=6,
        )
        
        # Muted style: Gray, Courier, 9pt
        self.muted_style = ParagraphStyle(
            "CustomMuted",
            fontName="Courier",
            fontSize=9,
            textColor=hex_to_rgb(COLORS["text_muted"]),
            alignment=TA_LEFT,
            spaceAfter=4,
        )
    
    def _cover_page(self) -> List[Flowable]:
        """
        Generate cover page flowables.
        
        Returns:
            List of PLATYPUS flowables for the cover page
        """
        flowables = []
        
        # Add vertical spacing to center content
        flowables.append(Spacer(1, 2.5 * inch))
        
        # Report title
        title = Paragraph("ATLAS 1.1 — EQUITY RESEARCH", self.title_style)
        flowables.append(title)
        flowables.append(Spacer(1, 0.5 * inch))
        
        # Generation timestamp
        now = datetime.now()
        timestamp = now.strftime("Generated: %B %d, %Y at %I:%M %p")
        timestamp_para = Paragraph(timestamp, self.muted_style)
        timestamp_para.alignment = TA_CENTER
        flowables.append(timestamp_para)
        flowables.append(Spacer(1, 1 * inch))
        
        # Peer set section
        peer_set_heading = Paragraph("Peer Set:", self.heading_style)
        flowables.append(peer_set_heading)
        flowables.append(Spacer(1, 0.2 * inch))
        
        # List of selected companies
        for company in self.selected_companies:
            formatted_company = _fmt_company_name(company)
            company_item = Paragraph(f"• {formatted_company}", self.body_style)
            flowables.append(company_item)
        
        # Page break after cover page
        flowables.append(PageBreak())
        
        return flowables
    
    def _fig_to_image(self, fig, width_pts, height_pts):
        from reportlab.platypus import Image
        import io
        apply_terminal_chart_theme(fig)
        # Render at 2x resolution for sharp display at smaller size
        img_bytes = fig.to_image(format="png", width=int(width_pts*2), height=int(height_pts*2), scale=2)
        return Image(io.BytesIO(img_bytes), width=width_pts, height=height_pts)
    
    def _make_table(self, df: pd.DataFrame, col_formats: Dict[str, Callable], 
                    color_map: Dict[str, Callable] = None, col_widths: List[float] = None) -> Table:
        """
        Convert pandas DataFrame to ReportLab Table with terminal styling.
        
        Args:
            df: DataFrame to convert
            col_formats: Dict mapping column name → format function
                         (e.g., {"Revenue": lambda v: f"${v/1000:.1f}M"})
            color_map: Optional dict mapping column name → color function
                       (e.g., {"Revenue Growth YoY": _get_color_for_revenue_growth})
            col_widths: Optional list of column widths in points
        
        Returns:
            ReportLab Table with dark theme styling and optional per-cell colors
            
        Example:
            col_formats = {
                "Revenue": lambda v: f"${v/1000:.1f}M" if pd.notna(v) else "N/A",
                "Gross Margin": lambda v: f"{v:.1%}" if pd.notna(v) else "N/A",
            }
            color_map = {
                "Gross Margin": _get_color_for_margin,
            }
            col_widths = [90, 40, 55, 55, 55]  # widths in points
            table = report._make_table(df, col_formats, color_map, col_widths)
        """
        # Keep original DataFrame for color lookups
        df_original = df.copy()
        
        # Create formatted copy
        df_formatted = df.copy()
        
        # Apply format functions to specified columns
        for col_name, fmt_func in col_formats.items():
            if col_name in df_formatted.columns:
                df_formatted[col_name] = df_formatted[col_name].apply(fmt_func)
        
        # Create cell paragraph style for wrapping text
        cell_style = ParagraphStyle(
            "CellStyle",
            fontName="Courier",
            fontSize=7,
            textColor=hex_to_rgb(COLORS["text_primary"]),
            leading=8,
            alignment=TA_LEFT,
        )
        
        # Convert to list of lists with Paragraph objects for wrapping
        # Header row first
        table_data = [[Paragraph(str(col), cell_style) for col in df_formatted.columns]]
        
        # Data rows - wrap in Paragraph objects
        for idx, row in df_formatted.iterrows():
            table_data.append([Paragraph(str(val), cell_style) for val in row])
        
        # Create table with optional column widths
        if col_widths:
            table = Table(table_data, colWidths=col_widths)
        else:
            table = Table(table_data)
        
        # Define table style with terminal theme
        table_style = TableStyle([
            # Header row styling: Amber background, black text
            ('BACKGROUND', (0, 0), (-1, 0), hex_to_rgb(COLORS["accent"])),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('FONTNAME', (0, 0), (-1, 0), 'Courier-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 7),
            ('ALIGN', (0, 0), (-1, 0), 'LEFT'),
            
            # Alternating row backgrounds
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [
                hex_to_rgb(COLORS["bg_panel"]),
                hex_to_rgb("#141414")
            ]),
            
            # Data cell styling: Light gray text, monospace font
            ('TEXTCOLOR', (0, 1), (-1, -1), hex_to_rgb(COLORS["text_primary"])),
            ('FONTNAME', (0, 1), (-1, -1), 'Courier'),
            ('FONTSIZE', (0, 1), (-1, -1), 7),
            
            # Tight padding for dense layout
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            
            # Grid lines: Subtle dark gray
            ('GRID', (0, 0), (-1, -1), 0.5, hex_to_rgb("#333333")),
            
            # Allow text to wrap
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ])
        
        # Right-align numeric columns (those in col_formats)
        for col_idx, col_name in enumerate(df.columns):
            if col_name in col_formats and col_name != "Company" and col_name != "Ticker" and col_name != "Margin Trend":
                table_style.add('ALIGN', (col_idx, 1), (col_idx, -1), 'RIGHT')
        
        # Apply per-cell colors if color_map is provided
        if color_map:
            for col_idx, col_name in enumerate(df_original.columns):
                if col_name in color_map:
                    color_func = color_map[col_name]
                    # Apply color to each data row (skip header row 0)
                    for row_idx in range(len(df_original)):
                        original_value = df_original.iloc[row_idx][col_name]
                        cell_color = color_func(original_value)
                        # row_idx + 1 because row 0 is header
                        table_style.add('TEXTCOLOR', (col_idx, row_idx + 1), (col_idx, row_idx + 1), cell_color)
        
        table.setStyle(table_style)
        
        return table
    
    def _section_overview(self) -> List[Flowable]:
        """
        Generate Overview section flowables with two peer comparison tables.
        
        Splits into two tables to fit within page width:
        1. VALUATION & GROWTH table
        2. PROFITABILITY & BALANCE SHEET table
        
        Returns:
            List of PLATYPUS flowables for the overview section
        """
        flowables = []
        
        # Build overview data rows
        rows = []
        for name in self.selected_companies:
            if name not in self.company_data:
                continue
            
            df = self.company_data[name]
            last = df.iloc[-1]
            val = self.valuation.get(name, {})
            
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
            
            # Apply company name formatting
            formatted_name = _fmt_company_name(name)
            
            rows.append({
                "Company": formatted_name,
                "Ticker": val.get("Ticker"),
                "Price": val.get("Price"),
                "Market Cap": val.get("Market_Cap"),
                "EV": val.get("EV"),
                "EV/Revenue": val.get("EV_Revenue"),
                "FCF Yield": val.get("FCF_Yield"),
                "P/FCF": val.get("P_FCF"),
                "Revenue Growth YoY": last.get("Revenue_Growth_YoY"),
                "TTM Revenue": last.get("TTM_Revenue"),
                "Rule of 40": val.get("Rule_of_40"),
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
                "Def Rev Growth YoY": last.get("Deferred_Revenue_Growth_YoY"),
            })
        
        # Create DataFrame and sort by Revenue Growth YoY
        overview_df = pd.DataFrame(rows)
        overview_df = overview_df.sort_values("Revenue Growth YoY", ascending=False, na_position="last")
        overview_df = overview_df.reset_index(drop=True)
        
        # ===== TABLE 1: VALUATION & GROWTH =====
        table1_cols = [
            "Company", "Ticker", "Price", "Market Cap", "EV", "EV/Revenue",
            "P/FCF", "FCF Yield", "Rule of 40", "Revenue Growth YoY", "TTM Revenue"
        ]
        table1_df = overview_df[table1_cols].copy()
        
        # Rename columns for shorter headers (prevents word-wrap issues)
        table1_df = table1_df.rename(columns={
            "EV/Revenue": "EV/Rev",
            "Revenue Growth YoY": "Rev Growth",
            "TTM Revenue": "TTM Rev",
        })
        
        # Format functions for Table 1 (use renamed column names)
        table1_formats = {
            "Price": fmt_price,
            "Market Cap": fmt_market_val,
            "EV": fmt_market_val,
            "EV/Rev": fmt_ratio,
            "FCF Yield": fmt_pct,
            "P/FCF": fmt_ratio,
            "Rev Growth": fmt_pct,
            "TTM Rev": fmt_revenue,
            "Rule of 40": fmt_pct,
        }
        
        # Color map for Table 1 (use renamed column names)
        table1_colors = {
            "FCF Yield": _get_color_for_fcf_yield,
            "P/FCF": _get_color_for_p_fcf,
            "Rev Growth": _get_color_for_revenue_growth,
            "Rule of 40": _get_color_for_rule_of_40,
        }
        
        # Column widths for Table 1 (total: 504pts for 7" printable width)
        # Adjusted to fit within 504pts
        table1_widths = [82, 32, 36, 46, 46, 40, 36, 40, 40, 46, 46]  # Total: 490pts
        
        # ===== TABLE 2: PROFITABILITY & BALANCE SHEET =====
        table2_cols = [
            "Company", "Ticker", "Gross Margin", "TTM Gross Margin", "Operating Margin",
            "TTM Operating Margin", "Op Margin Delta YoY", "Margin Trend",
            "Current Ratio", "Debt/Equity", "ROE", "Net Debt", "Def Rev Growth YoY"
        ]
        table2_df = overview_df[table2_cols].copy()
        
        # Rename columns for shorter headers (prevents word-wrap issues)
        table2_df = table2_df.rename(columns={
            "TTM Gross Margin": "TTM Gross Mgn",
            "Operating Margin": "Op Margin",
            "TTM Operating Margin": "TTM Op Margin",
            "Op Margin Delta YoY": "Δ Margin YoY",
            "Def Rev Growth YoY": "Def Rev Gr%",
        })
        
        # Format functions for Table 2 (use renamed column names)
        table2_formats = {
            "Gross Margin": fmt_pct,
            "TTM Gross Mgn": fmt_pct,
            "Op Margin": fmt_pct,
            "TTM Op Margin": fmt_pct,
            "Δ Margin YoY": fmt_pct,
            "Margin Trend": lambda v: v if pd.notna(v) else "N/A",
            "Current Ratio": fmt_ratio,
            "Debt/Equity": fmt_ratio,
            "ROE": fmt_pct,
            "Net Debt": fmt_millions,
            "Def Rev Gr%": fmt_pct,
        }
        
        # Color map for Table 2 (use renamed column names)
        table2_colors = {
            "Gross Margin": _get_color_for_margin,
            "TTM Gross Mgn": _get_color_for_margin,
            "Op Margin": _get_color_for_op_margin,
            "TTM Op Margin": _get_color_for_op_margin,
            "Δ Margin YoY": _get_color_for_delta,
            "Margin Trend": _get_color_for_margin_trend,
            "Current Ratio": _get_color_for_current_ratio,
            "Debt/Equity": _get_color_for_debt_to_equity,
            "ROE": _get_color_for_roe,
            "Def Rev Gr%": _get_color_for_deferred_rev_growth,
        }
        
        # Column widths for Table 2 (total: 504pts for 7" printable width)
        # Adjusted to fit within 504pts
        table2_widths = [82, 32, 34, 34, 34, 34, 38, 40, 33, 33, 30, 36, 40]  # Total: 500pts
        
        # Build flowables
        # Section header
        header = Paragraph("OVERVIEW — PEER COMPARISON", self.heading_style)
        flowables.append(header)
        flowables.append(Spacer(1, 0.2 * inch))
        
        # Table 1: Valuation & Growth
        table1_title = Paragraph("VALUATION & GROWTH", self.heading_style)
        flowables.append(table1_title)
        flowables.append(Spacer(1, 0.15 * inch))
        
        table1 = self._make_table(table1_df, table1_formats, table1_colors, table1_widths)
        flowables.append(table1)
        flowables.append(Spacer(1, 0.3 * inch))
        
        # Table 2: Profitability & Balance Sheet
        table2_title = Paragraph("PROFITABILITY & BALANCE SHEET", self.heading_style)
        flowables.append(table2_title)
        flowables.append(Spacer(1, 0.15 * inch))
        
        table2 = self._make_table(table2_df, table2_formats, table2_colors, table2_widths)
        flowables.append(table2)
        
        return flowables
    
    def _section_screener(self) -> List[Flowable]:
        """
        Generate Investment Screener section flowables.
        
        Replicates dashboard.py screener logic (lines 1638-1847):
        - Applies filter criteria (Rule of 40, Revenue Growth, P/FCF, FCF Yield, Margin Trend)
        - Table 1: Companies passing all criteria
        - Table 2: All companies ranked by filters passed with color-coded rows
        
        Returns:
            List of PLATYPUS flowables for the screener section
        """
        flowables = []
        
        # Section header
        header = Paragraph("INVESTMENT SCREENER", self.heading_style)
        flowables.append(header)
        flowables.append(Spacer(1, 0.3 * inch))
        
        # Build screening DataFrame (dashboard.py lines 1638-1658)
        screening_rows = []
        for name in self.company_data.keys():
            df = self.company_data[name]
            if df.empty:
                continue
            
            last = df.iloc[-1]
            val = self.valuation.get(name, {})
            
            # Calculate Margin_Trend_4Q (same logic as overview)
            _margin_deltas = df["Operating_Margin_Delta_YoY"].tail(4).dropna()
            _margin_trend_4q = _margin_deltas.mean() if len(_margin_deltas) >= 3 else None
            
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
        
        # Convert percentage inputs to decimals (dashboard.py lines 1661-1663)
        rule_of_40_min_decimal = self.rule_of_40_min / 100
        revenue_growth_min_decimal = self.revenue_growth_min / 100
        fcf_yield_min_decimal = self.fcf_yield_min / 100
        
        # Apply filters (dashboard.py lines 1665-1698)
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
            (screening_df["P_FCF"] <= self.p_fcf_max)
        )
        
        screening_df["passes_fcf_yield"] = (
            screening_df["FCF_Yield"].notna() & 
            (screening_df["FCF_Yield"] >= fcf_yield_min_decimal)
        )
        
        # Margin Trend filter
        if self.margin_trend_filter == "Any":
            screening_df["passes_margin_trend"] = True
        elif self.margin_trend_filter == "Expanding":
            screening_df["passes_margin_trend"] = (
                screening_df["Margin_Trend_4Q"].notna() & 
                (screening_df["Margin_Trend_4Q"] > 0)
            )
        elif self.margin_trend_filter == "Stable or Expanding":
            screening_df["passes_margin_trend"] = (
                screening_df["Margin_Trend_4Q"].notna() & 
                (screening_df["Margin_Trend_4Q"] >= 0)
            )
        
        # Count filters passed (dashboard.py lines 1700-1709)
        filter_cols = [
            "passes_rule_of_40",
            "passes_revenue_growth", 
            "passes_p_fcf",
            "passes_fcf_yield",
            "passes_margin_trend"
        ]
        screening_df["filters_passed"] = screening_df[filter_cols].sum(axis=1)
        screening_df["passes_all"] = screening_df["filters_passed"] == len(filter_cols)
        
        # ===== TABLE 1: Companies Meeting All Criteria =====
        table1_title = Paragraph("Companies Meeting All Criteria", self.body_style)
        flowables.append(table1_title)
        flowables.append(Spacer(1, 0.1 * inch))
        
        meets_all = screening_df[screening_df["passes_all"]].copy()
        
        if not meets_all.empty:
            # Format for display
            table1_df = meets_all[["Company", "Ticker", "Rule_of_40", "Revenue_Growth_YoY",
                                    "P_FCF", "FCF_Yield", "Margin_Trend_4Q", "filters_passed"]].copy()
            
            table1_df["Company"] = table1_df["Company"].apply(_fmt_company_name)
            
            # Rename columns
            table1_df.columns = ["Company", "Ticker", "Rule of 40", "Rev Growth",
                                 "P/FCF", "FCF Yield", "Margin Trend", "Filters"]
            
            # Define formats
            table1_formats = {
                "Company": lambda v: str(v),
                "Ticker": lambda v: str(v) if pd.notna(v) else "N/A",
                "Rule of 40": fmt_pct,
                "Rev Growth": fmt_pct,
                "P/FCF": fmt_ratio,
                "FCF Yield": fmt_pct,
                "Margin Trend": fmt_pct,
                "Filters": lambda v: f"{int(v)}/5" if pd.notna(v) else "0/5"
            }
            
            # Column widths (total ~500pts)
            table1_widths = [120, 40, 50, 50, 40, 50, 60, 40]
            
            table1 = self._make_table(table1_df, table1_formats, col_widths=table1_widths)
            flowables.append(table1)
        else:
            no_results = Paragraph("No companies meet all criteria.", self.muted_style)
            flowables.append(no_results)
        
        flowables.append(Spacer(1, 0.3 * inch))
        
        # ===== TABLE 2: All Companies Ranked by Filters Passed =====
        table2_title = Paragraph("All Companies Ranked by Filters Passed", self.body_style)
        flowables.append(table2_title)
        flowables.append(Spacer(1, 0.1 * inch))
        
        # Sort by filters_passed (dashboard.py line 1747)
        all_ranked = screening_df.sort_values("filters_passed", ascending=False).copy()
        
        # Format for display
        table2_df = all_ranked[["Company", "Ticker", "Rule_of_40", "Revenue_Growth_YoY",
                                "P_FCF", "FCF_Yield", "Margin_Trend_4Q", "filters_passed"]].copy()
        
        table2_df["Company"] = table2_df["Company"].apply(_fmt_company_name)
        
        # Rename columns
        table2_df.columns = ["Company", "Ticker", "Rule of 40", "Rev Growth",
                             "P/FCF", "FCF Yield", "Margin Trend", "Filters"]
        
        # Define formats
        table2_formats = {
            "Company": lambda v: str(v),
            "Ticker": lambda v: str(v) if pd.notna(v) else "N/A",
            "Rule of 40": fmt_pct,
            "Rev Growth": fmt_pct,
            "P/FCF": fmt_ratio,
            "FCF Yield": fmt_pct,
            "Margin Trend": fmt_pct,
            "Filters": lambda v: f"{int(v)}/5" if pd.notna(v) else "0/5"
        }
        
        # Column widths
        table2_widths = [120, 40, 50, 50, 40, 50, 60, 40]
        
        # Create base table
        table2 = self._make_table(table2_df, table2_formats, col_widths=table2_widths)
        
        # Apply row-level color coding (dashboard.py lines 1825-1839)
        total_filters = len(filter_cols)  # 5
        row_colors = []
        
        for idx, (_, row) in enumerate(all_ranked.iterrows()):
            filters_passed = row["filters_passed"]
            percentage = filters_passed / total_filters
            
            # Skip header row (row 0)
            row_idx = idx + 1
            
            if percentage == 1.0:  # 100% - dark green
                bg_color = hex_to_rgb("#1a4d1a")
            elif percentage >= 0.7:  # 70%+ - dark olive
                bg_color = hex_to_rgb("#4d4d1a")
            elif percentage < 0.5:  # <50% - dark red
                bg_color = hex_to_rgb("#4d1a1a")
            else:  # 50-70% - no special color, use default
                bg_color = None
            
            if bg_color:
                row_colors.append(('BACKGROUND', (0, row_idx), (-1, row_idx), bg_color))
        
        # Apply row colors to table style
        if row_colors:
            existing_style = table2._cellStyles
            for cmd in row_colors:
                existing_style.append(cmd)
        
        flowables.append(table2)
        
        return flowables
    
    def _section_deep_dive(self, company_name: str) -> List[Flowable]:
        """
        Generate Deep Dive section flowables for one company.
        
        Creates a detailed analysis page with:
        - KPI summary cards
        - 6 charts in 2-column grid layout
        
        Args:
            company_name: Name of company to analyze
            
        Returns:
            List of PLATYPUS flowables for the deep dive section
        """
        flowables = []
        
        # Page break before each company's deep dive
        flowables.append(PageBreak())
        
        # Get company data
        if company_name not in self.company_data:
            return flowables
        
        df = self.company_data[company_name].copy()
        val = self.valuation.get(company_name, {})
        cf_df = self.cashflow_data.get(company_name)
        
        # Section header
        formatted_name = _fmt_company_name(company_name)
        header = Paragraph(f"DEEP DIVE: {formatted_name}", self.heading_style)
        flowables.append(header)
        flowables.append(Spacer(1, 0.2 * inch))
        
        # ===== KPI SUMMARY CARDS =====
        last = df.iloc[-1]
        
        kpi_labels = ["Rule of 40", "Rev Growth", "FCF Margin", "P/FCF", "FCF Yield"]
        kpi_values = [
            fmt_pct(val.get("Rule_of_40")),
            fmt_pct(last.get("Revenue_Growth_YoY")),
            fmt_pct(cf_df.iloc[-1].get("FCF_Margin")) if cf_df is not None and not cf_df.empty else "N/A",
            fmt_ratio(val.get("P_FCF")),
            fmt_pct(val.get("FCF_Yield")),
        ]
        
        # Create KPI table
        kpi_data = [kpi_labels, kpi_values]
        kpi_table = Table(kpi_data, colWidths=[100, 100, 100, 100, 100])
        kpi_table.setStyle(TableStyle([
            # Header row
            ('BACKGROUND', (0, 0), (-1, 0), hex_to_rgb(COLORS["accent"])),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('FONTNAME', (0, 0), (-1, 0), 'Courier-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            # Value row (amber values, larger font)
            ('BACKGROUND', (0, 1), (-1, 1), hex_to_rgb(COLORS["bg_panel"])),
            ('TEXTCOLOR', (0, 1), (-1, 1), hex_to_rgb(COLORS["accent"])),
            ('FONTNAME', (0, 1), (-1, 1), 'Courier-Bold'),
            ('FONTSIZE', (0, 1), (-1, 1), 12),
            ('ALIGN', (0, 1), (-1, 1), 'CENTER'),
            # Grid
            ('GRID', (0, 0), (-1, -1), 0.5, hex_to_rgb("#333333")),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        
        flowables.append(kpi_table)
        flowables.append(Spacer(1, 0.3 * inch))
        
        # ===== CHARTS =====
        chart_width = 240
        chart_height = 150  # Reduced from 180 to fit all 6 charts + KPI cards on one page
        
        # Prepare color references
        neutral_color = COLORS.get("neutral", "#00FFFF")
        
        # Chart 1: Revenue Bar Chart
        fig1 = px.bar(
            df,
            x="Quarter",
            y="Revenue",
            text=df["Revenue"].apply(lambda v: f"${v/1000:,.0f}M" if pd.notna(v) else "")
        )
        fig1.update_traces(textposition="outside", marker_color=neutral_color)
        fig1.update_layout(yaxis_title="Revenue ($K)", xaxis_title="", showlegend=False, title="Revenue")
        
        # Chart 2: Revenue Growth YoY
        growth_df = df.dropna(subset=["Revenue_Growth_YoY"])
        fig2 = px.line(
            growth_df,
            x="Quarter",
            y="Revenue_Growth_YoY",
            markers=True
        )
        fig2.update_traces(line_color=COLORS["accent"])
        fig2.update_layout(yaxis_title="Growth %", yaxis_tickformat=".0%", xaxis_title="", title="Revenue Growth YoY")
        
        # Chart 3: Gross Margin & Operating Margin
        fig3 = go.Figure()
        if df["Gross_Margin"].notna().any():
            fig3.add_trace(
                go.Scatter(
                    x=df["Quarter"],
                    y=df["Gross_Margin"],
                    mode="lines+markers",
                    name="Gross Margin",
                    line=dict(color=COLORS["positive"]),
                )
            )
        fig3.add_trace(
            go.Scatter(
                x=df["Quarter"],
                y=df["Operating_Margin"],
                mode="lines+markers",
                name="Operating Margin",
                line=dict(color=neutral_color),
            )
        )
        fig3.update_layout(
            yaxis_title="Margin",
            yaxis_tickformat=".0%",
            xaxis_title="",
            title="Margins",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        )
        
        # Chart 4: Operating Margin Delta YoY
        delta_df = df.dropna(subset=["Operating_Margin_Delta_YoY"])
        fig4 = px.line(
            delta_df,
            x="Quarter",
            y="Operating_Margin_Delta_YoY",
            markers=True
        )
        fig4.update_traces(line_color=COLORS["negative"])
        fig4.update_layout(yaxis_title="Delta (pp)", yaxis_tickformat=".1%", xaxis_title="", title="Op Margin Δ YoY")
        fig4.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
        
        # Chart 5: Annual FCF Bar Chart
        if cf_df is not None and not cf_df.empty:
            fcf_plot = cf_df.dropna(subset=["Free_Cash_Flow"])
            if not fcf_plot.empty:
                fcf_colors = [COLORS["positive"] if v >= 0 else COLORS["negative"] for v in fcf_plot["Free_Cash_Flow"]]
                fig5 = go.Figure(
                    go.Bar(
                        x=fcf_plot["Quarter"],
                        y=fcf_plot["Free_Cash_Flow"],
                        marker_color=fcf_colors,
                        text=fcf_plot["Free_Cash_Flow"].apply(lambda v: f"${v/1000:,.0f}M" if pd.notna(v) else ""),
                        textposition="outside",
                    )
                )
                fig5.update_layout(yaxis_title="Free Cash Flow ($K)", xaxis_title="", title="Annual FCF")
                fig5.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
            else:
                fig5 = None
        else:
            fig5 = None
        
        # Chart 6: Rule of 40
        # Calculate Rule of 40 per quarter using annual FCF margin mapped to quarters
        if cf_df is not None and not cf_df.empty and "FCF_Margin" in cf_df.columns:
            # Create a mapping of year to FCF margin
            fcf_margin_map = {}
            for idx, row in cf_df.iterrows():
                if pd.notna(row.get("Quarter")):
                    year = str(row["Quarter"])[:4]  # Extract year from "2024 FY" or similar
                    fcf_margin_map[year] = row.get("FCF_Margin")
            
            # Calculate Rule of 40 for each quarter
            rule_40_list = []
            for idx, row in df.iterrows():
                quarter = row.get("Quarter")
                rev_growth = row.get("Revenue_Growth_YoY")
                if pd.notna(quarter) and pd.notna(rev_growth):
                    year = str(quarter)[:4]  # Extract year
                    fcf_margin = fcf_margin_map.get(year)
                    if fcf_margin is not None:
                        rule_40_val = rev_growth + fcf_margin
                        rule_40_list.append({"Quarter": quarter, "Rule_of_40": rule_40_val})
            
            if rule_40_list:
                rule_40_df = pd.DataFrame(rule_40_list)
                avg_rule_40 = rule_40_df["Rule_of_40"].mean()
                line_color = COLORS["positive"] if avg_rule_40 >= 0.40 else COLORS["negative"]
                
                fig6 = px.line(
                    rule_40_df,
                    x="Quarter",
                    y="Rule_of_40",
                    markers=True
                )
                fig6.update_traces(line_color=line_color)
                fig6.update_layout(yaxis_title="Rule of 40 (%)", yaxis_tickformat=".0%", xaxis_title="", title="Rule of 40")
                fig6.add_hline(
                    y=0.40,
                    line_dash="dash",
                    line_color="#2C3E50",
                    opacity=0.7,
                    annotation_text="40% Benchmark",
                    annotation_position="right"
                )
            else:
                fig6 = None
        else:
            fig6 = None
        
        # Convert charts to images
        img1 = self._fig_to_image(fig1, chart_width, chart_height)
        img2 = self._fig_to_image(fig2, chart_width, chart_height)
        img3 = self._fig_to_image(fig3, chart_width, chart_height)
        img4 = self._fig_to_image(fig4, chart_width, chart_height)
        img5 = self._fig_to_image(fig5, chart_width, chart_height) if fig5 else Paragraph("FCF: N/A", self.body_style)
        img6 = self._fig_to_image(fig6, chart_width, chart_height) if fig6 else Paragraph("Rule 40: N/A", self.body_style)
        
        # Create 2-column chart rows, each wrapped in KeepTogether to prevent page splits
        # Row 1: Revenue + Revenue Growth
        row1_table = Table([[img1, img2]], colWidths=[250, 250])
        row1_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        flowables.append(KeepTogether([row1_table]))
        
        # Row 2: Margins + Op Margin Delta
        row2_table = Table([[img3, img4]], colWidths=[250, 250])
        row2_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        flowables.append(KeepTogether([row2_table]))
        
        # Row 3: FCF + Rule of 40
        row3_table = Table([[img5, img6]], colWidths=[250, 250])
        row3_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        flowables.append(KeepTogether([row3_table]))
        
        return flowables
    
    def build(self, output_path: str):
        """
        Build and save the PDF report.
        
        Args:
            output_path: File path where the PDF will be saved
        """
        # Create document with letter size and 0.75" margins
        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            leftMargin=0.75 * inch,
            rightMargin=0.75 * inch,
            topMargin=0.75 * inch,
            bottomMargin=0.75 * inch,
        )
        
        # Build story (list of flowables)
        story = []
        
        # Add cover page
        story.extend(self._cover_page())
        
        # Add sections
        if "overview" in self.sections:
            story.extend(self._section_overview())
        
        if "screener" in self.sections:
            story.append(PageBreak())
            story.extend(self._section_screener())
        
        if "deep_dive" in self.sections:
            for company in self.selected_companies:
                story.extend(self._section_deep_dive(company))
        
        # Custom page template function for dark background
        def add_dark_background(canvas, doc):
            """Add dark background to each page."""
            canvas.saveState()
            canvas.setFillColor(hex_to_rgb(COLORS["bg_primary"]))
            canvas.rect(0, 0, letter[0], letter[1], fill=1, stroke=0)
            canvas.restoreState()
        
        # Build the PDF with dark background on all pages
        doc.build(story, onFirstPage=add_dark_background, onLaterPages=add_dark_background)
        
        print(f"PDF report generated: {output_path}")
