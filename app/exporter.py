"""
EPUB and PDF export module.

EPUB export features full CSS styling, markdown→HTML conversion, TOC, and drop caps.
PDF export uses bundled fonts from the static directory.
"""

import re
import html as html_lib
import logging
from pathlib import Path

from app.logging import log_error_with_trace

import ebooklib
from ebooklib import epub
from fpdf import FPDF, XPos, YPos

from app.storage import EXPORTS_DIR, ensure_exports_dir

logger = logging.getLogger(__name__)

# (H6) Use the `markdown` library for robust HTML conversion
try:
    import markdown as markdown_lib
    HAS_MARKDOWN_LIB = True
except ImportError:
    HAS_MARKDOWN_LIB = False
    logger.warning("'markdown' library not installed. Using regex fallback. Install with: pip install markdown")

# ── PDF Font Configuration ──────────────────────────────────────────────

# Use bundled fonts from static/fonts/ — no system dependencies
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static" / "fonts"

FONT_PATHS = {
    "Playfair": str(_STATIC_DIR / "playfair-display-400.ttf"),
    "Playfair-Bold": str(_STATIC_DIR / "playfair-display-700.ttf"),
    "PlexMono": str(_STATIC_DIR / "ibm-plex-mono-400.ttf"),
    "PlexMono-Bold": str(_STATIC_DIR / "ibm-plex-mono-500.ttf"),
}


def _check_fonts():
    """Verify that required font files exist. Log warnings for missing fonts."""
    for name, path in FONT_PATHS.items():
        if not Path(path).exists():
            logger.warning("Font not found: %s (%s)", name, path)


_check_fonts()

# ── Markdown → HTML converter ──────────────────────────────────────────

def markdown_to_html(text: str) -> str:
    """Convert markdown-formatted text to clean, semantic HTML.
    
    (H6 fix: uses the `markdown` library when available for robust conversion,
    falls back to regex-based parser for basic compatibility.)
    """
    if HAS_MARKDOWN_LIB:
        extensions = ['tables', 'fenced_code', 'codehilite']
        return markdown_lib.markdown(text, extensions=extensions)
    
    # Regex fallback (kept for compatibility when markdown lib is unavailable)
    text = html_lib.escape(text)

    # Horizontal rules (--- or ***)
    text = re.sub(r'^\s*[-*_]{3,}\s*$', '<hr>', text, flags=re.MULTILINE)

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
            book.add_metadata('OPF', 'subject', tag, {})

    # CSS stylesheet (M8 fix: unique UID to avoid collision with book identifier)
    style = epub.EpubItem(
        uid='style_default_css',
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

# —— PDF Export —————————————————————————————————————————————————

def export_to_pdf(
    book_id: str,
    title: str,
    chapters: dict,
    tags: list[str] = None,
    output_dir: str = None,
    review: dict = None,
):
    """Export a book to PDF format. Returns the absolute path to the file.
    
    (H7 fix: enhanced formatting with proper page layout, chapter separators,
    and improved font handling.)
    """
    if output_dir is None:
        output_dir = str(EXPORTS_DIR)

    pdf = FPDF()
    pdf.add_page()

    # Register fonts (with error handling for missing fonts)
    fonts_registered = False
    try:
        pdf.add_font("Playfair", "", FONT_PATHS["Playfair"])
        pdf.add_font("Playfair", "B", FONT_PATHS["Playfair-Bold"])
        pdf.add_font("PlexMono", "", FONT_PATHS["PlexMono"])
        pdf.add_font("PlexMono", "B", FONT_PATHS["PlexMono-Bold"])
        fonts_registered = True
    except Exception as e:
        log_error_with_trace(
            "Font registration failed: %s. Falling back to built-in fonts.", e,
            exc=e, logger_obj=logger,
        )

    # Use appropriate font family name
    font_family = "Playfair" if fonts_registered else "Times"
    font_mono = "PlexMono" if fonts_registered else "Courier"

    # Title page with decorative border
    pdf.set_font(font_family, "B", 20)
    pdf.ln(30)
    pdf.cell(200, 15, text=title, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
    pdf.ln(6)
    
    # Decorative line
    pdf.set_draw_color(100, 100, 100)
    pdf.set_line_width(0.5)
    pdf.line(50, pdf.get_y(), 150, pdf.get_y())
    pdf.ln(10)
    
    if tags:
        pdf.set_font(font_family, "", 12)
        pdf.cell(200, 8, text=", ".join(tags), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        pdf.ln(4)
    
    if review:
        score = review.get('overall_score', '')
        verdict = review.get('verdict', '')
        corrections = review.get('corrections', [])
        pdf.set_font(font_family, "", 10)
        if score:
            verdict_display = "Approved" if verdict == "ready" else "Needs Revision"
            pdf.cell(200, 7, text=f'Review Score: {score}/10 ({verdict_display})', new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        if corrections:
            pdf.cell(200, 7, text=f'{len(corrections)} correction(s) applied during review', new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
    
    # Decorative line at bottom
    pdf.ln(10)
    pdf.line(50, pdf.get_y(), 150, pdf.get_y())

    # Chapter pages
    for c_title, content in chapters.items():
        pdf.add_page()
        
        # Chapter heading with decorative underline
        pdf.set_font(font_family, "B", 16)
        pdf.cell(200, 12, text=c_title, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        pdf.ln(2)
        
        # Underline for chapter title
        pdf.set_draw_color(150, 150, 150)
        pdf.set_line_width(0.3)
        pdf.line(25, pdf.get_y(), 175, pdf.get_y())
        pdf.ln(8)

        # Body text — strip markdown formatting for PDF
        clean = content
        clean = re.sub(r'^#+\s+', '', clean, flags=re.MULTILINE)
        clean = re.sub(r'\*\*(.+?)\*\*', r'\1', clean)
        clean = re.sub(r'\*(.+?)\*', r'\1', clean)
        clean = re.sub(r'`([^`]+)`', r'\1', clean)
        clean = re.sub(r'^\s*[-*]\s+', '', clean, flags=re.MULTILINE)
        clean = re.sub(r'^(\s*[-*_]){3,}\s*$', '', clean, flags=re.MULTILINE)

        pdf.set_font(font_family, "", 11)
        pdf.set_text_color(30, 30, 30)
        pdf.multi_cell(0, 6, text=clean)
        pdf.ln(4)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / f"{book_id}.pdf"
    pdf.output(str(pdf_path))
    return str(pdf_path)
