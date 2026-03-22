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
# Color Palette (clean blue aesthetic, matches dashboard)
# ---------------------------------------------------------------------------
COLORS = {
    "page_bg": "#FFFFFF",
    "dark_navy": "#0A1628",
    "accent": "#4F9EFF",
    "section_header": "#1E2D45",
    "body_text": "#1A1A2E",
    "muted": "#6B8CAE",
    "light_gray": "#9CA3AF",
    "card_bg": "#F8FAFC",
    "card_bg_tint": "#E8F0FE",
    "border": "#E2E8F0",
    "positive": "#22C55E",
    "negative": "#EF4444",
    "neutral": "#4F9EFF",
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
# Format Functions (aligned with dashboard format helpers)
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
    """Format statement values stored in thousands USD as millions."""
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
# Color threshold functions (aligned with dashboard table styling)
# ---------------------------------------------------------------------------
def _get_color_for_revenue_growth(v):
    """Return ReportLab Color for revenue growth value. >20% green, <5% red."""
    if pd.isna(v):
        return hex_to_rgb(COLORS["body_text"])
    if v > 0.20:
        return hex_to_rgb(COLORS["positive"])
    if v < 0.05:
        return hex_to_rgb(COLORS["negative"])
    return hex_to_rgb(COLORS["body_text"])


def _get_color_for_margin(v):
    """Gross margin: >70% green, <40% red."""
    if pd.isna(v):
        return hex_to_rgb(COLORS["body_text"])
    if v > 0.70:
        return hex_to_rgb(COLORS["positive"])
    if v < 0.40:
        return hex_to_rgb(COLORS["negative"])
    return hex_to_rgb(COLORS["body_text"])


def _get_color_for_op_margin(v):
    """Operating margin: >20% green, <0% red."""
    if pd.isna(v):
        return hex_to_rgb(COLORS["body_text"])
    if v > 0.20:
        return hex_to_rgb(COLORS["positive"])
    if v < 0.0:
        return hex_to_rgb(COLORS["negative"])
    return hex_to_rgb(COLORS["body_text"])


def _get_color_for_delta(v):
    """Margin delta: >2% green, <-2% red."""
    if pd.isna(v):
        return hex_to_rgb(COLORS["body_text"])
    if v > 0.02:
        return hex_to_rgb(COLORS["positive"])
    if v < -0.02:
        return hex_to_rgb(COLORS["negative"])
    return hex_to_rgb(COLORS["body_text"])


def _get_color_for_margin_trend(v):
    """Margin trend: Expanding green, Contracting red."""
    if pd.isna(v) or v == "" or v == "N/A":
        return hex_to_rgb(COLORS["body_text"])
    if v == "Expanding":
        return hex_to_rgb(COLORS["positive"])
    if v == "Contracting":
        return hex_to_rgb(COLORS["negative"])
    return hex_to_rgb(COLORS["body_text"])


def _get_color_for_fcf_yield(v):
    """FCF Yield: >5% green, <2% red."""
    if pd.isna(v):
        return hex_to_rgb(COLORS["body_text"])
    if v > 0.05:
        return hex_to_rgb(COLORS["positive"])
    if v < 0.02:
        return hex_to_rgb(COLORS["negative"])
    return hex_to_rgb(COLORS["body_text"])


def _get_color_for_p_fcf(v):
    """P/FCF: <15 green, >30 red, <0 red."""
    if pd.isna(v):
        return hex_to_rgb(COLORS["body_text"])
    if v < 0:
        return hex_to_rgb(COLORS["negative"])
    if v < 15:
        return hex_to_rgb(COLORS["positive"])
    if v > 30:
        return hex_to_rgb(COLORS["negative"])
    return hex_to_rgb(COLORS["body_text"])


def _get_color_for_current_ratio(v):
    """Current Ratio: >=2.0 green, <1.0 red."""
    if pd.isna(v):
        return hex_to_rgb(COLORS["body_text"])
    if v >= 2.0:
        return hex_to_rgb(COLORS["positive"])
    if v < 1.0:
        return hex_to_rgb(COLORS["negative"])
    return hex_to_rgb(COLORS["body_text"])


def _get_color_for_roe(v):
    """ROE: >10% green, <0% red."""
    if pd.isna(v):
        return hex_to_rgb(COLORS["body_text"])
    if v > 0.10:
        return hex_to_rgb(COLORS["positive"])
    if v < 0:
        return hex_to_rgb(COLORS["negative"])
    return hex_to_rgb(COLORS["body_text"])


def _get_color_for_debt_to_equity(v):
    """Debt/Equity: <=0.5 green, >2.0 red, <0 red."""
    if pd.isna(v):
        return hex_to_rgb(COLORS["body_text"])
    if v < 0:
        return hex_to_rgb(COLORS["negative"])
    if v > 2.0:
        return hex_to_rgb(COLORS["negative"])
    if v <= 0.5:
        return hex_to_rgb(COLORS["positive"])
    return hex_to_rgb(COLORS["body_text"])


def _get_color_for_deferred_rev_growth(v):
    """Deferred Revenue Growth: >20% green, <5% red."""
    if pd.isna(v):
        return hex_to_rgb(COLORS["body_text"])
    if v > 0.20:
        return hex_to_rgb(COLORS["positive"])
    if v < 0.05:
        return hex_to_rgb(COLORS["negative"])
    return hex_to_rgb(COLORS["body_text"])


def _get_color_for_rule_of_40(v):
    """Rule of 40: >=40% green, <20% red."""
    if pd.isna(v):
        return hex_to_rgb(COLORS["body_text"])
    if v >= 0.40:
        return hex_to_rgb(COLORS["positive"])
    if v < 0.20:
        return hex_to_rgb(COLORS["negative"])
    return hex_to_rgb(COLORS["body_text"])


def apply_chart_theme(fig):
    """Apply clean blue theme: #F8FAFC chart background, #4F9EFF primary, #E2E8F0 gridlines."""
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="#F8FAFC",
        plot_bgcolor="#F8FAFC",
        font=dict(family="Helvetica, sans-serif", size=9, color="#6B8CAE"),
        xaxis=dict(
            gridcolor="#E2E8F0",
            gridwidth=1,
            showgrid=True,
            zeroline=False,
            tickfont=dict(color="#6B8CAE", size=8),
        ),
        yaxis=dict(
            gridcolor="#E2E8F0",
            gridwidth=1,
            showgrid=True,
            zeroline=False,
            tickfont=dict(color="#6B8CAE", size=8),
        ),
        legend=dict(
            bgcolor="rgba(255,255,255,0)",
            bordercolor="#E2E8F0",
            borderwidth=1,
            font=dict(size=8, color="#6B8CAE"),
        ),
        margin=dict(l=40, r=20, t=30, b=40),
    )
    return fig


class _HorizontalAccentLine(Flowable):
    """Horizontal accent line for cover page."""

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        self.height = 4
        return (self.width, self.height)

    def draw(self):
        self.canv.saveState()
        self.canv.setStrokeColor(hex_to_rgb(COLORS["accent"]))
        self.canv.setLineWidth(2)
        self.canv.line(0, 2, self.width, 2)
        self.canv.restoreState()


class AccentBar(Flowable):
    """Thin full-width accent bar (e.g. 6pt) for Deep Dive page headers."""

    def __init__(self, height_pt: float = 6):
        Flowable.__init__(self)
        self.height_pt = height_pt

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        return (self.width, self.height_pt)

    def draw(self):
        self.canv.saveState()
        self.canv.setFillColor(hex_to_rgb(COLORS["accent"]))
        self.canv.rect(0, 0, self.width, self.height_pt, fill=1, stroke=0)
        self.canv.restoreState()


class SectionHeader(Flowable):
    """Filled #0A1628 background, white text, #4F9EFF left border bar, padding."""

    def __init__(self, text: str):
        Flowable.__init__(self)
        self.text = text

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        self.height = 36
        return (self.width, self.height)

    def draw(self):
        self.canv.saveState()
        # Dark navy background
        self.canv.setFillColor(hex_to_rgb(COLORS["dark_navy"]))
        self.canv.rect(0, 0, self.width, self.height, fill=1, stroke=0)
        # Left blue accent bar (4pt wide)
        self.canv.setFillColor(hex_to_rgb(COLORS["accent"]))
        self.canv.rect(0, 6, 4, self.height - 12, fill=1, stroke=0)
        # White text
        self.canv.setFillColor(hex_to_rgb("#FFFFFF"))
        self.canv.setFont("Helvetica-Bold", 12)
        self.canv.drawString(14, 14, self.text)
        self.canv.restoreState()


class PDFReport:
    """Generate multi-section equity research PDF with clean blue aesthetic."""
    
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
        """Define paragraph styles for clean blue aesthetic."""
        # Title: large, dark, sans-serif
        self.title_style = ParagraphStyle(
            "CustomTitle",
            fontName="Helvetica-Bold",
            fontSize=28,
            textColor=hex_to_rgb(COLORS["section_header"]),
            alignment=TA_CENTER,
            spaceAfter=12,
        )
        # Heading: bold dark, sans-serif
        self.heading_style = ParagraphStyle(
            "CustomHeading",
            fontName="Helvetica-Bold",
            fontSize=12,
            textColor=hex_to_rgb(COLORS["section_header"]),
            alignment=TA_LEFT,
            spaceAfter=8,
            spaceBefore=12,
        )
        # Body: dark text, Helvetica
        self.body_style = ParagraphStyle(
            "CustomBody",
            fontName="Helvetica",
            fontSize=10,
            textColor=hex_to_rgb(COLORS["body_text"]),
            alignment=TA_LEFT,
            spaceAfter=6,
        )
        # Muted: gray labels
        self.muted_style = ParagraphStyle(
            "CustomMuted",
            fontName="Helvetica",
            fontSize=9,
            textColor=hex_to_rgb(COLORS["muted"]),
            alignment=TA_LEFT,
            spaceAfter=4,
        )
    
    def _cover_page(self) -> List[Flowable]:
        """
        Generate cover page: dark navy background, ATLAS wordmark in white,
        horizontal accent line, date/peer set in light gray, bottom strip in blue.
        """
        flowables = []

        flowables.append(Spacer(1, 2.2 * inch))

        # Large ATLAS wordmark in white
        atlas_style = ParagraphStyle(
            "AtlasWordmark",
            fontName="Helvetica-Bold",
            fontSize=48,
            textColor=hex_to_rgb("#FFFFFF"),
            alignment=TA_CENTER,
            spaceAfter=4,
        )
        flowables.append(Paragraph("ATLAS", atlas_style))

        # Horizontal accent line (custom flowable)
        flowables.append(Spacer(1, 0.5 * inch))
        flowables.append(_HorizontalAccentLine())
        flowables.append(Spacer(1, 0.5 * inch))

        # Generation date in light gray
        now = datetime.now()
        timestamp = now.strftime("Generated %B %d, %Y at %I:%M %p")
        ts_style = ParagraphStyle(
            "Timestamp",
            fontName="Helvetica",
            fontSize=9,
            textColor=hex_to_rgb(COLORS["light_gray"]),
            alignment=TA_CENTER,
            spaceAfter=12,
        )
        flowables.append(Paragraph(timestamp, ts_style))
        flowables.append(Spacer(1, 0.6 * inch))

        # Peer set in light gray
        peer_label = ParagraphStyle(
            "PeerLabel",
            fontName="Helvetica",
            fontSize=8,
            textColor=hex_to_rgb(COLORS["light_gray"]),
            alignment=TA_LEFT,
            spaceAfter=6,
        )
        flowables.append(Paragraph("PEER SET", peer_label))
        flowables.append(Spacer(1, 0.15 * inch))

        peer_item_style = ParagraphStyle(
            "PeerItem",
            fontName="Helvetica",
            fontSize=10,
            textColor=hex_to_rgb(COLORS["light_gray"]),
            alignment=TA_LEFT,
            spaceAfter=6,
        )
        for company in self.selected_companies:
            formatted_company = _fmt_company_name(company)
            flowables.append(Paragraph(f"• {formatted_company}", peer_item_style))

        flowables.append(PageBreak())
        return flowables
    
    def _fig_to_image(self, fig, width_pts, height_pts):
        from reportlab.platypus import Image
        import io
        apply_chart_theme(fig)
        # Render at 2x resolution for sharp display at smaller size
        img_bytes = fig.to_image(format="png", width=int(width_pts*2), height=int(height_pts*2), scale=2)
        return Image(io.BytesIO(img_bytes), width=width_pts, height=height_pts)
    
    def _make_table(self, df: pd.DataFrame, col_formats: Dict[str, Callable], 
                    color_map: Dict[str, Callable] = None, col_widths: List[float] = None,
                    row_text_colors: Dict[int, Color] = None) -> Table:
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
        
        # Header style: uppercase, muted, no word wrap (splitLongWords=0 prevents mid-word breaks)
        header_style = ParagraphStyle(
            "TableHeader",
            fontName="Helvetica-Bold",
            fontSize=7,
            textColor=hex_to_rgb(COLORS["muted"]),
            leading=8,
            alignment=TA_LEFT,
            splitLongWords=0,
        )
        # Data style: body text, monospace for numbers (applied via table style)
        cell_style = ParagraphStyle(
            "CellStyle",
            fontName="Courier",
            fontSize=7,
            textColor=hex_to_rgb(COLORS["body_text"]),
            leading=8,
            alignment=TA_LEFT,
        )
        cell_style_helvetica = ParagraphStyle(
            "CellStyleHelvetica",
            fontName="Helvetica",
            fontSize=7,
            textColor=hex_to_rgb(COLORS["body_text"]),
            leading=8,
            alignment=TA_LEFT,
        )

        # Header row: uppercase labels
        table_data = [[Paragraph(str(col).upper(), header_style) for col in df_formatted.columns]]

        # Data rows: monospace for numeric columns, Helvetica for text (Company, Ticker, Margin Trend)
        # row_text_colors: optional dict mapping 0-based row index -> Color for that row (e.g. white on dark bg)
        text_cols = {"Company", "Ticker", "Margin Trend"}
        for row_pos, (idx, row) in enumerate(df_formatted.iterrows()):
            use_override = row_text_colors and row_pos in row_text_colors
            if use_override:
                override_color = row_text_colors[row_pos]
                override_style = ParagraphStyle(f"CellOverride_{row_pos}", parent=cell_style, textColor=override_color)
                override_style_h = ParagraphStyle(f"CellOverrideH_{row_pos}", parent=cell_style_helvetica, textColor=override_color)
            row_paras = []
            for col_name, val in zip(df_formatted.columns, row):
                style = (override_style_h if col_name in text_cols else override_style) if use_override else (cell_style_helvetica if col_name in text_cols else cell_style)
                row_paras.append(Paragraph(str(val), style))
            table_data.append(row_paras)
        
        # Create table with optional column widths
        if col_widths:
            table = Table(table_data, colWidths=col_widths)
        else:
            table = Table(table_data)
        
        # Define table style: white background, #F8FAFC header, #E2E8F0 dividers
        table_style = TableStyle([
            # Header row: #F8FAFC background, muted uppercase labels
            ('BACKGROUND', (0, 0), (-1, 0), hex_to_rgb(COLORS["card_bg"])),
            ('TEXTCOLOR', (0, 0), (-1, 0), hex_to_rgb(COLORS["muted"])),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 7),
            ('ALIGN', (0, 0), (-1, 0), 'LEFT'),
            # Bottom border on header
            ('LINEBELOW', (0, 0), (-1, 0), 1, hex_to_rgb(COLORS["border"])),

            # Data rows: white background
            ('BACKGROUND', (0, 1), (-1, -1), hex_to_rgb(COLORS["page_bg"])),
            ('TEXTCOLOR', (0, 1), (-1, -1), hex_to_rgb(COLORS["body_text"])),
            ('FONTSIZE', (0, 1), (-1, -1), 7),
            # Row dividers (#E2E8F0)
            ('LINEBELOW', (0, 1), (-1, -1), 0.5, hex_to_rgb(COLORS["border"])),
            ('BOX', (0, 0), (-1, -1), 0.5, hex_to_rgb(COLORS["border"])),

            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
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
        
        # Short column headers to prevent wrapping
        table1_df = table1_df.rename(columns={
            "EV/Revenue": "EV/Rev",
            "Revenue Growth YoY": "Rev Gr",
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
            "Rev Gr": fmt_pct,
            "TTM Rev": fmt_revenue,
            "Rule of 40": fmt_pct,
        }
        
        # Color map for Table 1 (use renamed column names)
        table1_colors = {
            "FCF Yield": _get_color_for_fcf_yield,
            "P/FCF": _get_color_for_p_fcf,
            "Rev Gr": _get_color_for_revenue_growth,
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
        
        # Short column headers to prevent wrapping
        table2_df = table2_df.rename(columns={
            "TTM Gross Margin": "TTM GM",
            "Operating Margin": "Op Mgn",
            "TTM Operating Margin": "TTM OM",
            "Op Margin Delta YoY": "Δ Mgn",
            "Def Rev Growth YoY": "Def Rev%",
        })
        
        # Format functions for Table 2 (use renamed column names)
        table2_formats = {
            "Gross Margin": fmt_pct,
            "TTM GM": fmt_pct,
            "Op Mgn": fmt_pct,
            "TTM OM": fmt_pct,
            "Δ Mgn": fmt_pct,
            "Margin Trend": lambda v: v if pd.notna(v) else "N/A",
            "Current Ratio": fmt_ratio,
            "Debt/Equity": fmt_ratio,
            "ROE": fmt_pct,
            "Net Debt": fmt_millions,
            "Def Rev%": fmt_pct,
        }
        
        # Color map for Table 2 (use renamed column names)
        table2_colors = {
            "Gross Margin": _get_color_for_margin,
            "TTM GM": _get_color_for_margin,
            "Op Mgn": _get_color_for_op_margin,
            "TTM OM": _get_color_for_op_margin,
            "Δ Mgn": _get_color_for_delta,
            "Margin Trend": _get_color_for_margin_trend,
            "Current Ratio": _get_color_for_current_ratio,
            "Debt/Equity": _get_color_for_debt_to_equity,
            "ROE": _get_color_for_roe,
            "Def Rev%": _get_color_for_deferred_rev_growth,
        }
        
        # Column widths for Table 2 (total: 504pts for 7" printable width)
        # Adjusted to fit within 504pts
        table2_widths = [82, 32, 34, 34, 34, 34, 38, 40, 33, 33, 30, 36, 40]  # Total: 500pts
        
        # Build flowables — section header with left blue bar
        flowables.append(SectionHeader("OVERVIEW — PEER COMPARISON"))
        flowables.append(Spacer(1, 0.25 * inch))

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
        
        Replicates the dashboard Investment Screener filters and tables:
        - Applies filter criteria (Rule of 40, Revenue Growth, P/FCF, FCF Yield, Margin Trend)
        - Table 1: Companies passing all criteria
        - Table 2: All companies ranked by filters passed with color-coded rows
        
        Returns:
            List of PLATYPUS flowables for the screener section
        """
        flowables = []
        
        # Section header with left blue bar
        flowables.append(SectionHeader("INVESTMENT SCREENER"))
        flowables.append(Spacer(1, 0.25 * inch))
        
        # Build screening DataFrame (same inputs as dashboard screener)
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
        
        # Convert percentage inputs to decimals
        rule_of_40_min_decimal = self.rule_of_40_min / 100
        revenue_growth_min_decimal = self.revenue_growth_min / 100
        fcf_yield_min_decimal = self.fcf_yield_min / 100
        
        # Apply filters
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
        
        # Count filters passed
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
        
        # Row-level colors: dark green / yellow / red with white text
        total_filters = len(filter_cols)  # 5
        row_bg_commands = []
        row_text_colors = {}
        white_text = hex_to_rgb("#FFFFFF")
        for idx, (_, row) in enumerate(all_ranked.iterrows()):
            filters_passed = row["filters_passed"]
            percentage = filters_passed / total_filters
            row_idx = idx + 1  # table row (0=header, 1+=data)
            data_row_pos = idx  # 0-based data row index for row_text_colors
            
            if percentage == 1.0:  # 100% - dark green
                row_bg_commands.append(('BACKGROUND', (0, row_idx), (-1, row_idx), hex_to_rgb("#1a4d1a")))
                row_text_colors[data_row_pos] = white_text
            elif percentage >= 0.7:  # 70%+ - dark yellow
                row_bg_commands.append(('BACKGROUND', (0, row_idx), (-1, row_idx), hex_to_rgb("#4d4d1a")))
                row_text_colors[data_row_pos] = white_text
            elif percentage < 0.5:  # <50% - dark red
                row_bg_commands.append(('BACKGROUND', (0, row_idx), (-1, row_idx), hex_to_rgb("#4d1a1a")))
                row_text_colors[data_row_pos] = white_text
        
        # Create table with white text for colored rows
        table2 = self._make_table(table2_df, table2_formats, col_widths=table2_widths, row_text_colors=row_text_colors)

        # Apply row background colors by merging with the existing table style in one call,
        # so the base formatting from _make_table() is not replaced.
        if row_bg_commands:
            existing_cmds = list(table2._tblStyle._cmds)
            table2.setStyle(TableStyle(existing_cmds + row_bg_commands))
        
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
        
        # 6pt accent bar at top of deep dive page, then section header
        formatted_name = _fmt_company_name(company_name)
        flowables.append(AccentBar(height_pt=6))
        flowables.append(SectionHeader(f"DEEP DIVE: {formatted_name}"))
        flowables.append(Spacer(1, 0.25 * inch))
        
        # ===== KPI SUMMARY CARDS =====
        last = df.iloc[-1]

        kpi_labels = ["RULE OF 40", "REV GROWTH", "FCF MARGIN", "P/FCF", "FCF YIELD"]
        kpi_values = [
            fmt_pct(val.get("Rule_of_40")),
            fmt_pct(last.get("Revenue_Growth_YoY")),
            fmt_pct(cf_df.iloc[-1].get("FCF_Margin")) if cf_df is not None and not cf_df.empty else "N/A",
            fmt_ratio(val.get("P_FCF")),
            fmt_pct(val.get("FCF_Yield")),
        ]

        # KPI cards: #E8F0FE background, #4F9EFF top border (2pt), value bold #1E2D45, label small #6B8CAE uppercase
        kpi_label_style = ParagraphStyle("KpiLabel", fontName="Helvetica", fontSize=6, textColor=hex_to_rgb(COLORS["muted"]))
        kpi_value_style = ParagraphStyle("KpiValue", fontName="Helvetica-Bold", fontSize=14, textColor=hex_to_rgb(COLORS["section_header"]))

        kpi_row = []
        for label, value in zip(kpi_labels, kpi_values):
            inner = Table([
                [Paragraph(label, kpi_label_style)],
                [Paragraph(value, kpi_value_style)],
            ], colWidths=[90])
            inner.setStyle(TableStyle([
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            kpi_row.append(inner)

        kpi_table = Table([kpi_row], colWidths=[90, 90, 90, 90, 90])
        kpi_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), hex_to_rgb(COLORS["card_bg_tint"])),
            ('BOX', (0, 0), (-1, -1), 1, hex_to_rgb(COLORS["border"])),
            ('LINEABOVE', (0, 0), (-1, 0), 2, hex_to_rgb(COLORS["accent"])),
            ('LINEBEFORE', (0, 0), (0, -1), 1, hex_to_rgb(COLORS["border"])),
            ('LINEBEFORE', (1, 0), (1, -1), 1, hex_to_rgb(COLORS["border"])),
            ('LINEBEFORE', (2, 0), (2, -1), 1, hex_to_rgb(COLORS["border"])),
            ('LINEBEFORE', (3, 0), (3, -1), 1, hex_to_rgb(COLORS["border"])),
            ('LINEBEFORE', (4, 0), (4, -1), 1, hex_to_rgb(COLORS["border"])),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        flowables.append(kpi_table)
        flowables.append(Spacer(1, 0.3 * inch))
        
        # ===== CHARTS =====
        chart_width = 240
        chart_height = 150  # Reduced from 180 to fit all 6 charts + KPI cards on one page
        
        # Chart 1: Revenue Bar Chart
        fig1 = px.bar(
            df,
            x="Quarter",
            y="Revenue",
            text=df["Revenue"].apply(lambda v: f"${v/1000:,.0f}M" if pd.notna(v) else "")
        )
        fig1.update_traces(textposition="outside", marker_color=COLORS["accent"])
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
                line=dict(color=COLORS["accent"]),
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
        fig4.update_traces(line_color=COLORS["accent"])
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
                    line_color=COLORS["border"],
                    opacity=0.8,
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
        
        # Cover page: dark navy background, bottom strip, no page number
        def add_cover_decor(canvas, doc):
            canvas.saveState()
            canvas.setFillColor(hex_to_rgb(COLORS["dark_navy"]))
            canvas.rect(0, 0, letter[0], letter[1], fill=1, stroke=0)
            # Bottom strip in #4F9EFF
            canvas.setFillColor(hex_to_rgb(COLORS["accent"]))
            canvas.rect(0, 0, letter[0], 18, fill=1, stroke=0)
            canvas.restoreState()

        # Later pages: white background, blue bar at top (4pt), page number bottom right only
        def add_page_decor(canvas, doc):
            canvas.saveState()
            canvas.setFillColor(hex_to_rgb(COLORS["page_bg"]))
            canvas.rect(0, 0, letter[0], letter[1], fill=1, stroke=0)
            canvas.setFillColor(hex_to_rgb(COLORS["accent"]))
            canvas.rect(0, letter[1] - 4, letter[0], 4, fill=1, stroke=0)
            canvas.setFillColor(hex_to_rgb(COLORS["muted"]))
            canvas.setFont("Helvetica", 8)
            canvas.drawRightString(letter[0] - 0.75 * inch, 0.5 * inch, f"Page {canvas.getPageNumber()}")
            canvas.restoreState()

        doc.build(story, onFirstPage=add_cover_decor, onLaterPages=add_page_decor)
        
        print(f"PDF report generated: {output_path}")
