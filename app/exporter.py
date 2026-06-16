"""
EPUB and PDF export module.

EPUB export features full CSS styling, markdown→HTML conversion, TOC, and drop caps.
PDF export uses plain text with configurable DejaVu font paths.
"""
import os
import re
import html as html_lib
import logging
from pathlib import Path

import ebooklib
from ebooklib import epub
from fpdf.fpdf import FPDF

from app.storage import EXPORTS_DIR, ensure_exports_dir

logger = logging.getLogger(__name__)

# ── PDF Font Configuration ──────────────────────────────────────────────

# Default DejaVu font paths (common on Debian/Ubuntu)
_DEFAULT_FONT_DIR = "/usr/share/fonts/truetype/dejavu"

# Can be overridden via environment variable PDF_FONT_DIR
FONT_DIR = Path(os.environ.get("PDF_FONT_DIR", _DEFAULT_FONT_DIR))

FONT_PATHS = {
    "DejaVu": str(FONT_DIR / "DejaVuSans.ttf"),
    "DejaVu-Bold": str(FONT_DIR / "DejaVuSans-Bold.ttf"),
    "DejaVuMono": str(FONT_DIR / "DejaVuSansMono.ttf"),
    "DejaVuMono-Bold": str(FONT_DIR / "DejaVuSansMono-Bold.ttf"),
}


def _check_fonts():
    """Verify that required font files exist. Log warnings for missing fonts."""
    for name, path in FONT_PATHS.items():
        if not Path(path).exists():
            logger.warning("Font not found: %s (%s)", name, path)


_check_fonts()

# ── Markdown → HTML converter ──────────────────────────────────────────

def markdown_to_html(text: str) -> str:
    """Convert markdown-formatted text to clean, semantic HTML."""
    # Escape HTML entities first
    text = html_lib.escape(text)

    # Horizontal rules (--- or ***)
    text = re.sub(r'^(\s*[-*_]){3,}\s*$', '<hr>', text, flags=re.MULTILINE)

    # Headings (# ## ###) — order matters: longest first
    text = re.sub(r'^###\s+(.+)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)
    text = re.sub(r'^##\s+(.+)$', r'<h2>\1</h2>', text, flags=re.MULTILINE)
    text = re.sub(r'^#\s+(.+)$', r'<h1>\1</h1>', text, flags=re.MULTILINE)

    # Bold (**text** or __text__)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'__(.+?)__', r'<strong>\1</strong>', text)

    # Italic (*text* or _text_) — must come after bold
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    text = re.sub(r'_(.+?)_', r'<em>\1</em>', text)

    # Inline code (`code`)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

    # Unordered list items (- item or * item) — process consecutive lines
    lines = text.split('\n')
    result_lines = []
    in_list = False
    for line in lines:
        list_match = re.match(r'^\s*[-*]\s+(.+)$', line)
        if list_match:
            if not in_list:
                result_lines.append('<ul>')
                in_list = True
            result_lines.append(f'  <li>{list_match.group(1)}</li>')
        else:
            if in_list:
                result_lines.append('</ul>')
                in_list = False
            result_lines.append(line)
    if in_list:
        result_lines.append('</ul>')
    text = '\n'.join(result_lines)

    # Ordered list items (1. item)
    lines = text.split('\n')
    result_lines = []
    in_list = False
    for line in lines:
        list_match = re.match(r'^\s*\d+\.\s+(.+)$', line)
        if list_match:
            if not in_list:
                result_lines.append('<ol>')
                in_list = True
            result_lines.append(f'  <li>{list_match.group(1)}</li>')
        else:
            if in_list:
                result_lines.append('</ol>')
                in_list = False
            result_lines.append(line)
    if in_list:
        result_lines.append('</ol>')
    text = '\n'.join(result_lines)

    # Strip stray # at start of lines that weren't caught as headings
    text = re.sub(r'^#\s+', '', text, flags=re.MULTILINE)

    # Split into paragraphs by blank lines
    blocks = re.split(r'\n\s*\n', text)
    html_parts = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        # Block-level elements pass through as-is
        if re.match(r'^<(h[1-6]|hr|ul|ol|/ul|/ol|li)\b', block):
            html_parts.append(block)
        else:
            # Regular paragraph — replace single newlines with <br>
            formatted = block.replace('\n', '<br>')
            html_parts.append(f'<p>{formatted}</p>')

    return '\n'.join(html_parts)


# ── EPUB CSS ────────────────────────────────────────────────────────────

EPUB_CSS = """\
@page {
    margin: 2em 1.5em;
}

body {
    font-family: "Palatino Linotype", Palatino, Georgia, "Times New Roman", serif;
    font-size: 1.1em;
    line-height: 1.7;
    color: #1a1a1a;
    text-align: justify;
    hyphens: auto;
}

h1 {
    font-family: "Georgia", "Times New Roman", serif;
    font-size: 2em;
    font-weight: normal;
    text-align: center;
    margin-top: 3em;
    margin-bottom: 1em;
    color: #2c2c2c;
    letter-spacing: 0.05em;
}

h2 {
    font-family: "Georgia", "Times New Roman", serif;
    font-size: 1.5em;
    font-weight: normal;
    margin-top: 2em;
    margin-bottom: 0.8em;
    color: #333;
}

h3 {
    font-family: "Georgia", "Times New Roman", serif;
    font-size: 1.2em;
    font-weight: bold;
    margin-top: 1.5em;
    margin-bottom: 0.6em;
    color: #444;
}

p {
    margin-top: 0;
    margin-bottom: 1em;
    text-indent: 1.5em;
}

p:first-of-type {
    text-indent: 0;
}

strong { font-weight: bold; }
em    { font-style: italic; }

code {
    font-family: "Courier New", Courier, monospace;
    font-size: 0.9em;
    background-color: #f4f4f4;
    padding: 0.1em 0.3em;
    border-radius: 3px;
}

hr {
    border: none;
    border-top: 1px solid #ccc;
    margin: 2em 0;
    text-align: center;
}

hr:after {
    content: "\\2726";
    display: inline-block;
    color: #999;
    padding: 0 1em;
    background: white;
    position: relative;
    top: -0.8em;
    font-size: 0.8em;
}

ul, ol {
    margin: 1em 0;
    padding-left: 2em;
}

li {
    margin-bottom: 0.5em;
    text-indent: 0;
}

.cover-page h1 {
    font-size: 2.5em;
    margin-top: 20vh;
    letter-spacing: 0.15em;
    text-transform: uppercase;
}

.chapter-body p:first-of-type::first-letter {
    font-size: 3em;
    float: left;
    line-height: 0.8;
    margin-right: 0.1em;
    margin-top: 0.1em;
    font-family: "Georgia", serif;
    color: #2c2c2c;
}
"""


# ── EPUB Export ─────────────────────────────────────────────────────────

def export_to_epub(
    book_id: str,
    title: str,
    chapters: dict,
    tags: list[str] = None,
    output_dir: str = None,
    review: dict = None,
):
    """Export a book to EPUB format. Returns the absolute path to the file."""
    if output_dir is None:
        output_dir = str(EXPORTS_DIR)

    book = epub.EpubBook()
    book.set_identifier(book_id)
    book.set_title(title)
    book.set_language('en')

    # Add genre/theme tags as EPUB subjects
    if tags:
        for tag in tags:
            subject = epub.EpubMeta()
            subject.name = 'subject'
            subject.content = tag
            book.add_metadata('OPF', 'subject', [tag])

    # CSS stylesheet
    style = epub.EpubItem(
        uid=book_id,
        file_name='style/default.css',
        media_type='text/css',
        content=EPUB_CSS.encode('utf-8')
    )
    book.add_item(style)

    # ── Cover page ──
    cover_page = epub.EpubHtml(title='Cover', file_name='cover.xhtml', lang='en')
    cover_html = '<div class="cover-page">'
    cover_html += f'<h1>{html_lib.escape(title)}</h1>'
    if tags:
        cover_html += f'<p style="margin-top:1rem;font-size:0.9em;opacity:0.7;">{html_lib.escape(", ".join(tags))}</p>'
    if review:
        score = review.get('overall_score', '')
        verdict = review.get('verdict', '')
        if score:
            cover_html += f'<p style="margin-top:0.5rem;font-size:0.8em;opacity:0.6;">Reviewed: {score}/10 ({verdict})</p>'
    cover_html += '</div>'
    cover_page.content = cover_html
    book.add_item(cover_page)

    # ── Chapters ──
    chapters_list = []
    for idx, (c_title, content) in enumerate(chapters.items(), 1):
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', c_title)
        c = epub.EpubHtml(
            title=c_title,
            file_name=f'chapters/chapter_{idx}.xhtml',
            lang='en'
        )
        converted = markdown_to_html(content)
        c.content = f'<div class="chapter-body">\n{converted}\n</div>'
        book.add_item(c)
        chapters_list.append(c)

    # ── TOC & Spine ──
    book.toc = [cover_page] + chapters_list
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ['nav', 'cover'] + chapters_list

    # ── Write ──
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    epub_path = out_dir / f"{book_id}.epub"
    epub.write_epub(str(epub_path), book, {})
    return str(epub_path)


# ── PDF Export ──────────────────────────────────────────────────────────

def export_to_pdf(
    book_id: str,
    title: str,
    chapters: dict,
    tags: list[str] = None,
    output_dir: str = None,
    review: dict = None,
):
    """Export a book to PDF format. Returns the absolute path to the file."""
    if output_dir is None:
        output_dir = str(EXPORTS_DIR)

    pdf = FPDF()
    pdf.add_page()

    # Register fonts (with error handling for missing fonts)
    try:
        pdf.add_font("DejaVu", "", FONT_PATHS["DejaVu"], uni=True)
        pdf.add_font("DejaVu", "B", FONT_PATHS["DejaVu-Bold"], uni=True)
        pdf.add_font("DejaVuMono", "", FONT_PATHS["DejaVuMono"], uni=True)
        pdf.add_font("DejaVuMono", "B", FONT_PATHS["DejaVuMono-Bold"], uni=True)
    except Exception as e:
        logger.error("Font registration failed: %s. Falling back to Helvetica.", e)
        # Fallback to built-in Helvetica if DejaVu fonts are missing
        pdf.add_font("DejaVu", "", "", uni=False)
        pdf.add_font("DejaVu", "B", "", uni=False)
        pdf.add_font("DejaVuMono", "", "", uni=False)
        pdf.add_font("DejaVuMono", "B", "", uni=False)

    # Title page
    pdf.set_font("DejaVu", "B", 18)
    pdf.cell(200, 12, txt=title, ln=True, align='C')
    pdf.ln(4)
    if tags:
        pdf.set_font("DejaVu", size=11)
        pdf.cell(200, 7, txt=", ".join(tags), ln=True, align='C')
    if review:
        score = review.get('overall_score', '')
        verdict = review.get('verdict', '')
        corrections = review.get('corrections', [])
        pdf.ln(2)
        pdf.set_font("DejaVu", size=9)
        if score:
            pdf.cell(200, 6, txt=f'Reviewed: {score}/10 ({verdict})', ln=True, align='C')
        if corrections:
            pdf.cell(200, 6, txt=f'{len(corrections)} correction(s) applied', ln=True, align='C')
    pdf.ln(10)

    for c_title, content in chapters.items():
        pdf.add_page()
        # Chapter heading
        pdf.set_font("DejaVu", "B", 14)
        pdf.cell(200, 10, txt=c_title, ln=True, align='L')
        pdf.ln(4)

        # Body text — strip markdown for PDF
        clean = content
        clean = re.sub(r'^#+\s+', '', clean, flags=re.MULTILINE)
        clean = re.sub(r'\*\*(.+?)\*\*', r'\1', clean)
        clean = re.sub(r'\*(.+?)\*', r'\1', clean)
        clean = re.sub(r'`([^`]+)`', r'\1', clean)
        clean = re.sub(r'^\s*[-*]\s+', '', clean, flags=re.MULTILINE)
        clean = re.sub(r'^(\s*[-*_]){3,}\s*$', '', clean, flags=re.MULTILINE)

        pdf.set_font("DejaVu", size=11)
        pdf.multi_cell(0, 5.5, txt=clean)
        pdf.ln(3)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / f"{book_id}.pdf"
    pdf.output(str(pdf_path))
    return str(pdf_path)
