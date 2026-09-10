"""Write the final cover letter draft to a .docx file."""

import itertools
import re
import unicodedata
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt


def _sanitize(text: str) -> str:
    """Lowercase text and strip it down to filename-safe characters.

    Whitespace becomes underscores; anything that isn't alphanumeric or an
    underscore afterward is dropped.
    """
    text = text.strip().lower()
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^a-z0-9_]", "", text)
    return text


def _add_hyperlink(paragraph, url: str, text: str, color: str = "000000") -> None:
    """Append a real, clickable hyperlink run to `paragraph`.

    python-docx has no public API for hyperlinks — this builds the
    relationship + <w:hyperlink> XML element directly, which is the
    standard workaround. `color` is a 6-digit hex string with no '#'
    (default black, so links don't render in Word's default blue).
    """
    part = paragraph.part
    r_id = part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )

    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)

    run = OxmlElement("w:r")
    run_props = OxmlElement("w:rPr")

    color_elem = OxmlElement("w:color")
    color_elem.set(qn("w:val"), color)
    run_props.append(color_elem)

    underline_elem = OxmlElement("w:u")
    underline_elem.set(qn("w:val"), "single")
    run_props.append(underline_elem)

    run.append(run_props)

    text_elem = OxmlElement("w:t")
    text_elem.text = text
    run.append(text_elem)

    hyperlink.append(run)
    paragraph._p.append(hyperlink)


_BOLD_MARKDOWN_PATTERN = re.compile(r"\*\*(.+?)\*\*")

# Unicode "Mathematical Alphanumeric Symbols" block — bold/italic/bold-italic/
# sans/bold-sans/monospace/script/fraktur/double-struck Latin-letter
# lookalikes (e.g. "𝗣𝘆𝘁𝗵𝗼𝗻" for "Python"). Observed in practice (gpt-5.6-sol,
# on this pipeline) as a workaround the model reaches for to fake bold
# emphasis when a prompt discourages markdown without carving out an
# explicit bold exception. NFKC normalization decodes these back to plain
# ASCII; see _iter_bold_spans().
_STYLED_LETTER_RANGE = range(0x1D400, 0x1D7FF + 1)

# A bullet line may still arrive with a stray manual marker despite
# instructions.md telling the model not to add one — stripped defensively
# by _strip_leading_bullet_marker(). Deliberately does NOT match "**"
# (markdown bold) or "--".
_LEADING_BULLET_MARKER = re.compile(r"^(?:[•●▪]|-(?!-)|\*(?!\*))\s+")

# Paragraph spacing, tuned to match the candidate's established reference
# letter format (a real Word doc with a bold centered name, three bolded
# bullets with visible breathing room, and a tight sign-off) rather than
# python-docx's defaults.
_TIGHT_SPACE_AFTER = Pt(0)  # the date line, and the "Sincerely,"/name pair
_REGULAR_SPACE_AFTER = Pt(10)  # role line, salutation, opening/closing paragraphs
_BULLET_SPACE_AFTER = Pt(8)  # slightly tighter between the three bullets
_BULLET_LEFT_INDENT = Inches(0.5)
_BULLET_FIRST_LINE_INDENT = Inches(-0.25)  # hanging indent, so wrapped lines align under the text, not the bullet


def _iter_bold_spans(text: str):
    """Yield (chunk, is_bold) pairs from `text`, decoding two bold conventions.

    1. Literal **double-asterisk** markdown — the documented, intended
       convention (see instructions.md) for bullet lead-in headers.
    2. Unicode "styled" lookalike letters (see _STYLED_LETTER_RANGE) — a
       fake-bold workaround observed from the model in practice. Since the
       visual intent was clearly emphasis, these are decoded to plain
       ASCII and rendered as real bold runs rather than left as garbled
       glyphs that aren't actually bold once they reach Word.

    Whichever convention (or neither) appears in a given stretch of text,
    the caller gets back plain-ASCII chunks with a bold flag — never raw
    markdown asterisks or styled Unicode glyphs.
    """
    for is_styled, group in itertools.groupby(
        text, key=lambda ch: ord(ch) in _STYLED_LETTER_RANGE
    ):
        chunk = "".join(group)
        if is_styled:
            yield unicodedata.normalize("NFKC", chunk), True
            continue
        pos = 0
        for match in _BOLD_MARKDOWN_PATTERN.finditer(chunk):
            if match.start() > pos:
                yield chunk[pos : match.start()], False
            yield match.group(1), True
            pos = match.end()
        if pos < len(chunk):
            yield chunk[pos:], False


def _strip_leading_bullet_marker(line: str) -> str:
    """Remove a stray manual bullet marker some models add anyway.

    instructions.md tells the model not to type "•"/"-"/"*" at the start
    of a bullet line — the renderer adds a real bulleted-list marker
    automatically — but this strips one defensively if it shows up.
    Deliberately does not match "**" (markdown bold) or "--".
    """
    return _LEADING_BULLET_MARKER.sub("", line, count=1)


def _is_bullet_line(line: str) -> bool:
    """True if `line` looks like one of the three skill bullets.

    Detected by whether it starts with a bolded lead-in header — either
    literal **markdown** or the Unicode "styled" lookalike variant (see
    _iter_bold_spans) — after stripping any stray manual bullet marker.
    """
    candidate = _strip_leading_bullet_marker(line)
    if candidate.startswith("**"):
        return True
    return bool(candidate) and ord(candidate[0]) in _STYLED_LETTER_RANGE


def _add_paragraph(
    document: Document,
    text: str,
    *,
    alignment=None,
    style: str | None = None,
    space_before=None,
    space_after=None,
    line_spacing: float | None = None,
    left_indent=None,
    first_line_indent=None,
):
    """Add a paragraph, decoding bold spans (see _iter_bold_spans) into real
    bold runs and applying whichever direct paragraph formatting is given.

    Direct paragraph formatting (space_before/after, line_spacing, indents)
    always overrides whatever the named `style` would otherwise supply —
    used here so bullet paragraphs can use Word's built-in "List Bullet"
    style (for a real bulleted list, not a typed "•" character) while still
    getting this letter format's specific spacing and hanging indent rather
    than that style's own defaults.
    """
    para = document.add_paragraph(style=style) if style else document.add_paragraph()
    if alignment is not None:
        para.alignment = alignment

    pf = para.paragraph_format
    if space_before is not None:
        pf.space_before = space_before
    if space_after is not None:
        pf.space_after = space_after
    if line_spacing is not None:
        pf.line_spacing = line_spacing
    if left_indent is not None:
        pf.left_indent = left_indent
    if first_line_indent is not None:
        pf.first_line_indent = first_line_indent

    for chunk, is_bold in _iter_bold_spans(text):
        if not chunk:
            continue
        run = para.add_run(chunk)
        if is_bold:
            run.bold = True

    return para


def _add_header(
    document: Document,
    full_name: str,
    location: str,
    phone: str,
    email: str,
    linkedin_url: str,
    github_url: str,
    portfolio_url: str,
) -> None:
    """Add the centered, bolded name + contact-line header block to `document`."""
    name_para = document.add_paragraph()
    name_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    name_para.paragraph_format.space_after = Pt(3)
    name_run = name_para.add_run(full_name)
    name_run.font.size = Pt(15)
    name_run.bold = True

    contact_para = document.add_paragraph()
    contact_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    contact_para.paragraph_format.space_after = Pt(12)
    contact_para.add_run(f"{location} | {phone} | {email} | ")
    _add_hyperlink(contact_para, linkedin_url, "LinkedIn")
    contact_para.add_run(" | ")
    _add_hyperlink(contact_para, github_url, "GitHub")
    contact_para.add_run(" | ")
    _add_hyperlink(contact_para, portfolio_url, "Portfolio")


def write_docx(
    letter_text: str,
    company: str,
    role: str,
    output_dir: str = "output",
    *,
    full_name: str | None = None,
    location: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    linkedin_url: str | None = None,
    github_url: str | None = None,
    portfolio_url: str | None = None,
) -> str:
    """Write `letter_text` to a .docx file in `output_dir`.

    Produces a business-letter document: 1-inch margins, 11pt Times New
    Roman body text, no header/footer section. `letter_text` is split into
    one paragraph per non-empty line (splitting on ANY newline — the
    Generator is instructed to blank-line-separate every logical block,
    but in practice sometimes uses single newlines instead; splitting on
    every line rather than only on blank-line-separated blocks handles
    both without losing paragraph structure, since each logical block
    the Generator writes is always exactly one line of text).

    Each line is classified and formatted positionally:
      - The first line (the date) and the last two lines ("Sincerely," and
        the signed name) get tight spacing (no space after).
      - A line that starts with a bolded lead-in header — real **markdown**
        or a Unicode "styled" lookalike fake-bold (see _iter_bold_spans) —
        is treated as one of the three skill bullets: rendered with Word's
        real bulleted-list formatting (not a typed "•" character), a
        hanging indent, and single line spacing.
      - Every other line (role name, salutation, opening paragraph, closing
        paragraph(s)) gets standard paragraph spacing.
    Any bold spans within a line — **markdown** or Unicode fake-bold — are
    rendered as real bold runs throughout, not just within bullets.

    If `full_name` is provided, a centered header is added above the body:
    the name at 15pt bold, then a centered contact line at 11pt with
    LinkedIn/GitHub/Portfolio rendered as black (non-default-blue)
    hyperlinks. Pass `full_name` and the rest of the contact fields
    together, or omit all of them to skip the header entirely (e.g. for
    tests).

    Args:
        letter_text: The final, reviewer-approved cover letter body text.
        company: Company name, used to build the output filename.
        role: Role/job title, used to build the output filename.
        output_dir: Directory to write the .docx file into. Created if it
            doesn't already exist.
        full_name: Full name for the header. Omit to skip the header block.
        location: City/state line for the contact line.
        phone: Phone number for the contact line.
        email: Email address for the contact line.
        linkedin_url: LinkedIn profile URL, rendered as a hyperlink.
        github_url: GitHub profile URL, rendered as a hyperlink.
        portfolio_url: Portfolio URL, rendered as a hyperlink.

    Returns:
        The full filepath of the saved .docx file, as a string.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{_sanitize(company)}_{_sanitize(role)}.docx"
    filepath = out_dir / filename

    document = Document()

    section = document.sections[0]
    section.top_margin = Inches(1)
    section.bottom_margin = Inches(1)
    section.left_margin = Inches(1)
    section.right_margin = Inches(1)

    normal_style = document.styles["Normal"]
    normal_style.font.name = "Times New Roman"
    normal_style.font.size = Pt(11)
    normal_style.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    normal_style.paragraph_format.space_before = Pt(0)
    normal_style.paragraph_format.space_after = _REGULAR_SPACE_AFTER

    if full_name:
        _add_header(
            document,
            full_name=full_name,
            location=location,
            phone=phone,
            email=email,
            linkedin_url=linkedin_url,
            github_url=github_url,
            portfolio_url=portfolio_url,
        )

    lines = [line.strip() for line in letter_text.strip().splitlines() if line.strip()]

    for i, line in enumerate(lines):
        is_tight = i == 0 or i >= len(lines) - 2  # date line, or "Sincerely,"/name
        if _is_bullet_line(line):
            _add_paragraph(
                document,
                _strip_leading_bullet_marker(line),
                alignment=WD_ALIGN_PARAGRAPH.LEFT,
                style="List Bullet",
                space_before=Pt(0),
                space_after=_BULLET_SPACE_AFTER,
                line_spacing=1.0,
                left_indent=_BULLET_LEFT_INDENT,
                first_line_indent=_BULLET_FIRST_LINE_INDENT,
            )
        else:
            _add_paragraph(
                document,
                line,
                alignment=WD_ALIGN_PARAGRAPH.LEFT,
                space_after=_TIGHT_SPACE_AFTER if is_tight else _REGULAR_SPACE_AFTER,
            )

    document.save(str(filepath))
    return str(filepath)


if __name__ == "__main__":
    sample_letter = """September 09, 2026

Software Engineer, Test Company

Dear Recruiter,

My name is Jane Doe, and I am writing to express my interest in the Software Engineer position at Test Company. I am currently studying Computer Science, with a strong focus on distributed systems and developer tooling. I believe the following skills make me a strong fit for this role.

**Backend Systems:** During my internship at a fintech startup, I designed and shipped a rate-limiting service that reduced downstream API errors by 40%, working primarily in Python and Go. I built the request-throttling logic on top of a Redis-backed token bucket, instrumented it with per-client metrics, and rolled it out gradually behind a feature flag to validate behavior under real traffic. This work directly translates to the kind of high-throughput backend reliability Test Company's platform team maintains.

**Distributed Systems Coursework:** My graduate coursework in distributed systems covered consensus protocols, replication, and fault tolerance, which I applied in a course project building a Raft-based key-value store in Go. I implemented leader election, log replication, and snapshotting, and stress-tested the cluster under simulated network partitions to confirm it preserved linearizability. That hands-on grounding in distributed correctness is exactly what I'd bring to Test Company's infrastructure team.

**Open Source Contributions:** I have contributed several merged pull requests to a widely-used open-source observability tool, focused on improving its tracing instrumentation and reducing sampling overhead. Working across an unfamiliar, large codebase taught me to navigate other engineers' design decisions and communicate changes clearly through code review. I'm eager to bring that same collaborative, detail-oriented approach to Test Company's engineering culture.

As for my interest in Test Company, it is deeply rooted in the company's engineering culture and its investment in developer tooling. I've followed the team's engineering blog closely and admire the emphasis on internal platform quality. I am enthusiastic about the possibility of bringing my skills to Test Company and look forward to discussing how my background and experience would allow me to contribute to the Platform team.

Sincerely,
Jane Doe"""

    saved_path = write_docx(
        letter_text=sample_letter,
        company="Test Company",
        role="Software Engineer",
        full_name="Jane Doe",
        location="San Francisco, CA",
        phone="+1 (555) 555-5555",
        email="jane.doe@example.com",
        linkedin_url="https://www.linkedin.com/in/janedoe",
        github_url="https://github.com/janedoe",
        portfolio_url="https://janedoe.dev",
    )
    print(f"Saved test letter to: {saved_path}")
