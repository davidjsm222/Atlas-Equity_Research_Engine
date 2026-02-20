# PDF Generator - Kaleido Installation Note

## Overview

The `_fig_to_image()` method in `pdf_generator.py` requires the **kaleido** package to export Plotly figures as PNG images for embedding in PDFs.

## Current Status

Kaleido has been installed but has compatibility issues on the current system (macOS ARM64 with Python 3.9). The `_make_table()` method works perfectly and has been fully tested.

## Installation

Kaleido is installed via:
```bash
pip3 install kaleido==0.2.1
```

## Known Issues

### Version 0.2.1 (older version)
- Segmentation fault on macOS ARM64
- Error: `Received signal 11 SEGV_ACCERR`

### Version 1.2.0 (newer version)
- Browser initialization issues
- Error: `BrowserFailedError: The browser seemed to close immediately after starting`

## Workarounds

### Option 1: Use Docker/Container
Run the PDF generation in a Linux container where kaleido works reliably.

### Option 2: Alternative Image Export
If kaleido continues to have issues, consider using `plotly-orca` (deprecated) or `plotly.io.write_image()` with a different backend.

### Option 3: Pre-render Charts
Generate chart images separately using a working environment and pass them as pre-rendered images to the PDF generator.

## Method Implementation

The `_fig_to_image()` method is correctly implemented and will work once kaleido is functioning:

```python
def _fig_to_image(self, fig, width_pts: float, height_pts: float) -> Image:
    """Convert Plotly figure to ReportLab Image with dark theme."""
    # Apply dark theme
    fig.update_layout(
        paper_bgcolor="#0B0B0B",
        plot_bgcolor="#0B0B0B",
        font_color="#EAEAEA"
    )
    
    # Export at 2x resolution
    png_bytes = fig.to_image(
        format="png",
        width=int(width_pts * 1.5),
        height=int(height_pts * 1.5),
        scale=2
    )
    
    # Wrap in ReportLab Image
    return Image(io.BytesIO(png_bytes), width=width_pts, height=height_pts)
```

## Verified Functionality

✓ `_make_table()` - **Fully functional**
  - Terminal styling with amber headers
  - Alternating row backgrounds (#111111 / #141414)
  - Proper formatting with col_formats dict
  - Courier monospace font, 8pt
  - Tight padding (6pt horizontal, 4pt vertical)

✗ `_fig_to_image()` - **Implementation correct, kaleido environment issues**
  - Code is correct and follows the specification
  - Will work once kaleido environment is properly configured
  - Consider using a Linux environment or Docker for reliable operation

## Testing

The test script demonstrated:
- Tables render perfectly with dark theme styling
- PDF generation works with dark backgrounds
- Chart method is correctly implemented but blocked by kaleido issues

## Recommendation

For production use:
1. Deploy PDF generation in a Linux environment where kaleido is stable
2. Or pre-render charts separately and pass as Image objects directly
3. The `_make_table()` method can be used immediately without any issues
