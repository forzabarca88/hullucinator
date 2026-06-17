"""Tests for EPUB and PDF export functionality (L10)."""
import sys
import os
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.exporter import export_to_epub, export_to_pdf, markdown_to_html
from app.storage import ensure_exports_dir


class TestMarkdownToHtml:
    """Test markdown_to_html conversion."""

    def test_bold(self):
        result = markdown_to_html("**bold text**")
        assert "<strong>bold text</strong>" in result

    def test_italic(self):
        result = markdown_to_html("*italic text*")
        assert "<em>italic text</em>" in result

    def test_combined_bold_italic(self):
        result = markdown_to_html("***bold and italic***")
        assert "strong" in result and "em" in result

    def test_headings(self):
        result = markdown_to_html("# Heading 1\n## Heading 2\n### Heading 3")
        assert "<h1>Heading 1</h1>" in result
        assert "<h2>Heading 2</h2>" in result
        assert "<h3>Heading 3</h3>" in result

    def test_paragraphs(self):
        result = markdown_to_html("First paragraph.\n\nSecond paragraph.")
        assert "<p>First paragraph.</p>" in result
        assert "<p>Second paragraph.</p>" in result

    def test_links(self):
        result = markdown_to_html("[Google](https://google.com)")
        assert '<a href="https://google.com">Google</a>' in result

    def test_code_inline(self):
        result = markdown_to_html("Use `code here` for emphasis")
        assert "<code>code here</code>" in result

    def test_blockquote(self):
        result = markdown_to_html("> This is a quote")
        assert "<blockquote>" in result

    def test_unordered_list(self):
        result = markdown_to_html("- Item 1\n- Item 2\n- Item 3")
        assert "<ul>" in result
        assert "<li>Item 1</li>" in result

    def test_ordered_list(self):
        result = markdown_to_html("1. First\n2. Second")
        assert "<ol>" in result
        assert "<li>First</li>" in result

    def test_empty_input(self):
        result = markdown_to_html("")
        assert result == ""

    def test_plain_text(self):
        """Plain text without markdown gets wrapped in <p>."""
        result = markdown_to_html("Just plain text")
        assert "<p>Just plain text</p>" in result

    def test_html_escaping(self):
        """Raw HTML characters in markdown are escaped."""
        result = markdown_to_html("1 < 2 > 3")
        assert "&lt;" in result and "&gt;" in result


class TestExportEpub:
    """Test EPUB export."""

    def test_epub_export_creates_file(self, tmp_path):
        """Export creates a valid .epub file."""
        book_id = "test-epub-1"
        title = "Test Book"
        chapters = {"Chapter 1": "Once upon a time...", "Chapter 2": "The end."}
        tags = ["fantasy", "adventure"]
        review = {"overall_score": 8, "verdict": "ready", "corrections": []}

        export_to_epub(book_id, title, chapters, tags, str(tmp_path), review)

        epub_path = tmp_path / f"{book_id}.epub"
        assert epub_path.exists()
        assert epub_path.stat().st_size > 0

    def test_epub_export_no_tags(self, tmp_path):
        """Export works with empty tags list."""
        book_id = "test-epub-2"
        export_to_epub(book_id, "No Tags Book", {"Ch 1": "Content"}, [], str(tmp_path), None)
        assert (tmp_path / f"{book_id}.epub").exists()

    def test_epub_export_no_review(self, tmp_path):
        """Export works without review metadata."""
        book_id = "test-epub-3"
        export_to_epub(book_id, "No Review Book", {"Ch 1": "Content"}, ["sci-fi"], str(tmp_path), None)
        assert (tmp_path / f"{book_id}.epub").exists()

    def test_epub_export_with_review_metadata(self, tmp_path):
        """Review metadata is included in EPUB."""
        book_id = "test-epub-4"
        review = {
            "overall_score": 9,
            "verdict": "ready",
            "corrections": [{"chapter": "Ch 1", "issue_type": "pacing", "corrected": True}],
        }
        export_to_epub(book_id, "Reviewed Book", {"Ch 1": "Content"}, [], str(tmp_path), review)
        assert (tmp_path / f"{book_id}.epub").exists()


class TestExportPdf:
    """Test PDF export."""

    def test_pdf_export_creates_file(self, tmp_path):
        """Export creates a valid .pdf file."""
        book_id = "test-pdf-1"
        title = "Test Book"
        chapters = {"Chapter 1": "Once upon a time...", "Chapter 2": "The end."}
        tags = ["fantasy"]
        review = {"overall_score": 8, "verdict": "ready", "corrections": []}

        export_to_pdf(book_id, title, chapters, tags, str(tmp_path), review)

        pdf_path = tmp_path / f"{book_id}.pdf"
        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 0

    def test_pdf_export_no_tags(self, tmp_path):
        """Export works with empty tags list."""
        book_id = "test-pdf-2"
        export_to_pdf(book_id, "No Tags Book", {"Ch 1": "Content"}, [], str(tmp_path), None)
        assert (tmp_path / f"{book_id}.pdf").exists()

    def test_pdf_export_no_review(self, tmp_path):
        """Export works without review metadata."""
        book_id = "test-pdf-3"
        export_to_pdf(book_id, "No Review Book", {"Ch 1": "Content"}, ["sci-fi"], str(tmp_path), None)
        assert (tmp_path / f"{book_id}.pdf").exists()

    def test_pdf_export_with_markdown(self, tmp_path):
        """PDF export handles markdown content."""
        book_id = "test-pdf-4"
        chapters = {"Ch 1": "**Bold** and *italic* text\n\n## A Section\n\nParagraph here."}
        export_to_pdf(book_id, "Markdown Book", chapters, [], str(tmp_path), None)
        assert (tmp_path / f"{book_id}.pdf").exists()
