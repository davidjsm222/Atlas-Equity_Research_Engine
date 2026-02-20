# Layout Issues Fixed ✓

## Summary

Fixed two layout issues in `pdf_generator.py` that were causing charts to split across pages and creating blank pages between sections.

## Issue 1: Charts Splitting Across Pages — FIXED ✓

**Problem:**
Chart pairs could split across pages because all 6 charts were in a single 3-row Table.

**Solution:**
Separated the single 3-row table into three separate 1-row tables, each wrapped in `KeepTogether` flowable.

**Location:** Lines 927-968 in `pdf_generator.py`

**Before:**
```python
# Create 2-column grid
chart_grid_data = [
    [img1, img2],
    [img3, img4],
    [img5, img6],
]

chart_grid = Table(chart_grid_data, colWidths=[250, 250])
chart_grid.setStyle(TableStyle([...]))
flowables.append(chart_grid)
```

**After:**
```python
# Create 2-column chart rows, each wrapped in KeepTogether to prevent page splits
# Row 1: Revenue + Revenue Growth
row1_table = Table([[img1, img2]], colWidths=[250, 250])
row1_table.setStyle(TableStyle([...]))
flowables.append(KeepTogether([row1_table]))

# Row 2: Margins + Op Margin Delta
row2_table = Table([[img3, img4]], colWidths=[250, 250])
row2_table.setStyle(TableStyle([...]))
flowables.append(KeepTogether([row2_table]))

# Row 3: FCF + Rule of 40
row3_table = Table([[img5, img6]], colWidths=[250, 250])
row3_table.setStyle(TableStyle([...]))
flowables.append(KeepTogether([row3_table]))
```

**Benefits:**
- ✓ Each chart pair stays together on the same page
- ✓ If a row doesn't fit, it moves to the next page as a unit
- ✓ No awkward chart splits mid-row

## Issue 2: Blank Page Between Sections — FIXED ✓

**Problem:**
A blank page appeared between the overview section and the first deep dive because:
- `build()` method added `PageBreak()` after overview (line 981)
- `_section_deep_dive()` added `PageBreak()` at the start of each company (line 736)
- First deep dive got TWO page breaks = blank page

**Solution:**
Removed the `PageBreak()` after overview section in the `build()` method. Each deep dive still adds its own `PageBreak()` at the start, which is correct for separating companies.

**Location:** Line 996 in `pdf_generator.py`

**Before:**
```python
if "overview" in self.sections:
    story.extend(self._section_overview())
    story.append(PageBreak())  # ← Extra page break causing blank page
```

**After:**
```python
if "overview" in self.sections:
    story.extend(self._section_overview())
```

**Page Break Logic:**
- Cover page → ends with `PageBreak()` (correct)
- Overview → NO page break at end (fixed)
- First Deep Dive → starts with `PageBreak()` (correct - transitions from overview)
- Second Deep Dive → starts with `PageBreak()` (correct - separates from first)
- Third Deep Dive → starts with `PageBreak()` (correct - separates from second)

**Benefits:**
- ✓ No blank pages between sections
- ✓ Clean transition from overview to first deep dive
- ✓ Proper separation between multiple company deep dives

## Additional Change

**Import Update:**
Added `KeepTogether` to imports (line 28):

```python
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image, Table, TableStyle, KeepTogether
```

## Testing

✓ Module imports successfully
✓ No linter errors
✓ Code structure validated

## Expected Behavior

With these fixes, the PDF layout should now be:

1. **Cover Page**
2. **Overview Section** (2 tables)
3. **Deep Dive: Company 1** (starts on next available space after overview)
   - KPI cards
   - Row 1: Revenue + Revenue Growth (stays together)
   - Row 2: Margins + Op Margin Delta (stays together)
   - Row 3: FCF + Rule of 40 (stays together)
4. **Deep Dive: Company 2** (new page)
   - Same structure
5. **Deep Dive: Company 3** (new page)
   - Same structure

**No more:**
- ✗ Blank pages between sections
- ✗ Chart pairs splitting across pages

## Files Modified

- `pdf_generator.py` - Fixed chart splitting and blank page issues

## Summary

Both layout issues are resolved:
- ✓ Charts stay together in pairs (no mid-row splits)
- ✓ No blank pages between overview and deep dive sections
- ✓ Clean, professional page flow
