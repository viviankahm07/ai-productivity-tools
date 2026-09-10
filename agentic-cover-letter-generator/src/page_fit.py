"""Estimate whether a rendered .docx cover letter fits on one printed page.

There's no PDF/word renderer available in this environment (no LibreOffice/
Word), so this can't get an exact page count the way opening the file in
Word would. Instead it re-opens the *already-rendered* .docx (so it's
checking the real fonts/sizes/spacing/margins/indents that were actually
applied, not a re-derivation of them) and simulates word-wrapping each
paragraph using real font metrics (PIL + the actual Times New Roman font
files, when available) to estimate how many lines it takes, then sums each
paragraph's line count against its measured line height and paragraph
spacing to get a total content height in points, compared against the
page's usable height.

This is an estimate, not an exact page count — good enough to drive a
"does this need tightening" decision, not to promise an exact line count.
"""

from pathlib import Path

from docx import Document
from docx.shared import Emu

# Times New Roman at typical single line spacing renders with roughly 1.15x
# the nominal font size as its line height (leading), per common typesetting
# reference tables for this font. Calibrated by running estimate_page_count()
# against the known-one-page reference letter
# (examples/Kahm_Vivian_Cover_Letter_Deutsche_Bank.docx, estimates ~0.94) and
# a known-slightly-over-one-page letter (estimates ~1.1-1.2) and checking
# both land on the correct side of _FIT_TOLERANCE below.
_LINE_HEIGHT_FACTOR = 1.15

# A page-count estimate slightly over 1.0 is expected noise (font hinting,
# kerning, and the greedy-wrap approximation aren't pixel-perfect vs. Word's
# own layout engine) — only treat it as "doesn't fit" once it clears this
# tolerance.
_FIT_TOLERANCE = 1.04

# Real Times New Roman, when present (macOS ships it at this path). Falls
# back to a plain character-count heuristic (_FALLBACK_AVG_CHAR_WIDTH_EM)
# when no matching font file can be found on this machine, so this still
# works (just less precisely) on a machine without these fonts installed.
_REGULAR_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "/Library/Fonts/Times New Roman.ttf",
    "C:\\Windows\\Fonts\\times.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
]
_BOLD_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
    "/Library/Fonts/Times New Roman Bold.ttf",
    "C:\\Windows\\Fonts\\timesbd.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
]

# Rendering fonts at this many points-per-point and dividing the measured
# width back down gives sub-pixel precision despite ImageFont.truetype()
# only accepting an integer pixel size.
_MEASURE_SCALE = 8

# Used only if no real font file is found on this machine at all — a rough
# average glyph width as a fraction of font size, for Times-like serif
# fonts (empirically ~0.47-0.50 em for mixed-case English prose).
_FALLBACK_AVG_CHAR_WIDTH_EM = 0.48

_font_cache: dict = {}


def _find_font(candidates: list[str]) -> str | None:
    for path in candidates:
        if Path(path).exists():
            return path
    return None


_REGULAR_FONT_PATH = _find_font(_REGULAR_FONT_CANDIDATES)
_BOLD_FONT_PATH = _find_font(_BOLD_FONT_CANDIDATES)


def _get_font(font_path: str, size_pt: float):
    from PIL import ImageFont

    size_px = max(1, round(size_pt * _MEASURE_SCALE))
    key = (font_path, size_px)
    font = _font_cache.get(key)
    if font is None:
        font = ImageFont.truetype(font_path, size=size_px)
        _font_cache[key] = font
    return font


def _measure_width_pt(text: str, size_pt: float, bold: bool) -> float:
    """Measure `text`'s rendered width in points at `size_pt`.

    Uses real font metrics when a matching font file was found on this
    machine; otherwise falls back to a flat average-character-width
    heuristic so this still produces a usable (if less precise) estimate
    everywhere.
    """
    font_path = (_BOLD_FONT_PATH if bold else _REGULAR_FONT_PATH) or _REGULAR_FONT_PATH
    if font_path is None:
        return len(text) * size_pt * _FALLBACK_AVG_CHAR_WIDTH_EM
    font = _get_font(font_path, size_pt)
    return font.getlength(text) / _MEASURE_SCALE


def _length_pt(value) -> float:
    """Return a python-docx Length's point value, or 0.0 if it's None."""
    return value.pt if value is not None else 0.0


def _paragraph_font_pt(paragraph, default_pt: float) -> float:
    """The dominant font size for `paragraph`'s lines (for line-height math).

    Prefers an explicit run-level size (e.g. the 15pt name header), then the
    paragraph's style, then the document default (Normal, 11pt here).
    """
    for run in paragraph.runs:
        if run.font.size is not None:
            return run.font.size.pt
    style = paragraph.style
    if style is not None and style.font.size is not None:
        return style.font.size.pt
    return default_pt


def _paragraph_words(paragraph, default_pt: float) -> list[tuple[str, bool, float]]:
    """(word, is_bold, font_pt) for each word in `paragraph`, run-aware.

    python-docx's `paragraph.runs` doesn't include text inside a raw
    `<w:hyperlink>` element (see src/docx_writer.py's `_add_hyperlink` —
    it appends hyperlink XML directly, bypassing the runs API), so a
    paragraph containing hyperlinks (the header's contact line) reports
    fewer/shorter runs than its visible text. Detected by comparing
    run-text length against `paragraph.text` length; when it looks like
    text is missing, falls back to treating the whole paragraph as one
    plain run at the default size so the estimate doesn't just silently
    drop that text's width. This only affects the header's short, fixed
    contact line — never the compressible bullet/body content.
    """
    run_text_len = sum(len(r.text) for r in paragraph.runs)
    if paragraph.text and run_text_len < len(paragraph.text) * 0.5:
        return [(word, False, default_pt) for word in paragraph.text.split(" ") if word]

    words = []
    for run in paragraph.runs:
        size = run.font.size.pt if run.font.size is not None else _paragraph_font_pt(paragraph, default_pt)
        bold = bool(run.font.bold)
        for word in run.text.split(" "):
            if word:
                words.append((word, bold, size))
    return words


def _wrapped_line_count(paragraph, usable_width_pt: float, default_pt: float) -> int:
    """Simulate greedy word-wrapping to estimate how many lines `paragraph` takes."""
    left_indent_pt = _length_pt(paragraph.paragraph_format.left_indent)
    available = max(usable_width_pt - left_indent_pt, 36.0)  # floor: never an absurdly narrow column

    words = _paragraph_words(paragraph, default_pt)
    if not words:
        return 1  # a blank paragraph still takes one line

    space_width = _measure_width_pt(" ", default_pt, False)

    line_count = 1
    current_width = 0.0
    for word, bold, size in words:
        word_width = _measure_width_pt(word, size, bold)
        addition = word_width if current_width == 0 else space_width + word_width
        if current_width + addition > available and current_width > 0:
            line_count += 1
            current_width = word_width
        else:
            current_width += addition
    return line_count


def estimate_page_count(filepath: str) -> float:
    """Estimate how many printed pages `filepath` (a .docx) takes up.

    Re-opens the already-rendered document and reads back its actual
    section geometry (page size, margins) and paragraph formatting (font
    sizes, bold runs, indents, spacing, line-spacing rule) to simulate
    word-wrapping and sum a total content height, then divides by the
    page's usable height. See the module docstring for why this is an
    estimate rather than an exact count.

    Args:
        filepath: Path to a .docx file, typically just produced by
            src.docx_writer.write_docx().

    Returns:
        Estimated page count as a float (e.g. 1.08 means "a little over
        one page").
    """
    document = Document(filepath)
    section = document.sections[0]

    # Length subtraction (Emu - Emu) returns a plain int (raw EMU) rather
    # than preserving the Length subclass, so `.pt` isn't available on the
    # result directly — rewrap with Emu() to get it back.
    usable_width_pt = Emu(section.page_width - section.left_margin - section.right_margin).pt
    usable_height_pt = Emu(section.page_height - section.top_margin - section.bottom_margin).pt

    normal_font = document.styles["Normal"].font
    default_pt = normal_font.size.pt if normal_font.size is not None else 11.0

    total_height_pt = 0.0
    for paragraph in document.paragraphs:
        pf = paragraph.paragraph_format
        style_pf = paragraph.style.paragraph_format if paragraph.style is not None else None

        space_before = _length_pt(pf.space_before) if pf.space_before is not None else (
            _length_pt(style_pf.space_before) if style_pf is not None else 0.0
        )
        space_after = _length_pt(pf.space_after) if pf.space_after is not None else (
            _length_pt(style_pf.space_after) if style_pf is not None else 0.0
        )

        multiplier = pf.line_spacing if isinstance(pf.line_spacing, (int, float)) else 1.0
        font_pt = _paragraph_font_pt(paragraph, default_pt)
        line_height_pt = font_pt * _LINE_HEIGHT_FACTOR * multiplier

        line_count = _wrapped_line_count(paragraph, usable_width_pt, default_pt)
        total_height_pt += space_before + space_after + line_count * line_height_pt

    if usable_height_pt <= 0:
        return 0.0
    return total_height_pt / usable_height_pt


def check_page_fit(filepath: str) -> tuple[bool, float]:
    """Return (fits_one_page, estimated_page_count) for the .docx at `filepath`.

    `fits_one_page` allows a small tolerance (_FIT_TOLERANCE) over exactly
    1.0 page, since this is an estimate, not an exact layout engine.
    """
    pages = estimate_page_count(filepath)
    return pages <= _FIT_TOLERANCE, pages


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print(f"Usage: python {sys.argv[0]} <path_to_docx>")
        sys.exit(1)

    fits, pages = check_page_fit(sys.argv[1])
    font_note = (
        f"regular font: {_REGULAR_FONT_PATH or '(none found — using char-count fallback)'}"
    )
    print(font_note)
    print(f"estimated pages: {pages:.3f}")
    print(f"fits one page (tolerance {_FIT_TOLERANCE}): {fits}")
