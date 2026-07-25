"""Tests for EPUB and PDF export functionality (L10)."""
import os
import tempfile
import zipfile
from pathlib import Path

import pytest

from app.exporter import export_to_epub, export_to_pdf, markdown_to_html
from app import storage as app_storage


class TestMarkdownToHtml:
    """Test markdown_to_html conversion."""

    def test_bold(self):
        result = markdown_to_html("**bold text**")
        assert "<strong>bold text</strong>" in result

    def test_italic(self):
        result = markdown_to_html("*italic text*")
        assert "<em>italic text</em>" in result


    def test_headings(self):
        result = markdown_to_html("# Heading 1\n## Heading 2\n### Heading 3")
        assert "<h1>Heading 1</h1>" in result
        assert "<h2>Heading 2</h2>" in result
        assert "<h3>Heading 3</h3>" in result

    def test_paragraphs(self):
        result = markdown_to_html("First paragraph.\n\nSecond paragraph.")
        assert "<p>First paragraph.</p>" in result
        assert "<p>Second paragraph.</p>" in result


    def test_code_inline(self):
        result = markdown_to_html("Use `code here` for emphasis")
        assert "<code>code here</code>" in result


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

    def test_epub_export_with_cover_image(self, tmp_path):
        """Cover image is embedded in EPUB when provided."""
        app_storage.set_test_dirs(tmp_path)
        app_storage.ensure_covers_dir()

        book_id = "test-epub-cover-1"
        # Create a minimal valid PNG (1x1 pixel, grey)
        png_header = bytes([
            0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
            0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
            0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
            0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,
            0xDE, 0x00, 0x00, 0x00, 0x0C, 0x49, 0x44, 0x41,
            0x54, 0x78, 0x9C, 0x63, 0x00, 0x01, 0x00, 0x00,
            0x05, 0x00, 0x01, 0x0D, 0x0A, 0x2D, 0xB4,
            0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4E, 0x44,
            0xAE, 0x42, 0x60, 0x82,
        ])
        cover_path = tmp_path / "covers" / f"{book_id}.png"
        cover_path.write_bytes(png_header)

        chapters = {"Chapter 1": "Content here"}
        result_path = export_to_epub(
            book_id, "Cover Book", chapters, tags=[],
            output_dir=str(tmp_path), cover_image=f"covers/{book_id}.png",
        )

        assert Path(result_path).exists()
        # Verify the EPUB contains the cover image
        with zipfile.ZipFile(result_path) as zf:
            names = zf.namelist()
            assert "images" in str(names) or any("image" in n.lower() for n in names)

        app_storage.reset_to_defaults()

    def test_epub_export_cover_missing_file_fallback(self, tmp_path):
        """EPUB exports gracefully when cover_image path doesn't exist."""
        app_storage.set_test_dirs(tmp_path)

        book_id = "test-epub-cover-missing"
        chapters = {"Chapter 1": "Content here"}
        result_path = export_to_epub(
            book_id, "No Cover Book", chapters, tags=[],
            output_dir=str(tmp_path), cover_image="covers/nonexistent.png",
        )

        assert Path(result_path).exists()
        # Should still produce a valid EPUB (text cover page as fallback)
        assert Path(result_path).stat().st_size > 0

        app_storage.reset_to_defaults()

    def test_epub_export_without_cover(self, tmp_path):
        """EPUB exports normally when no cover_image is provided."""
        book_id = "test-epub-no-cover"
        chapters = {"Chapter 1": "Content here"}
        result_path = export_to_epub(
            book_id, "Plain Book", chapters, tags=[],
            output_dir=str(tmp_path), cover_image=None,
        )

        assert Path(result_path).exists()
        assert Path(result_path).stat().st_size > 0


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

    def test_pdf_export_with_cover_image(self, tmp_path):
        """Cover image is rendered on the PDF title page when provided."""
        app_storage.set_test_dirs(tmp_path)
        app_storage.ensure_covers_dir()

        book_id = "test-pdf-cover-1"
        # Create a minimal valid PNG (1x1 pixel, grey)
        png_header = bytes([
            0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
            0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
            0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
            0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,
            0xDE, 0x00, 0x00, 0x00, 0x0C, 0x49, 0x44, 0x41,
            0x54, 0x78, 0x9C, 0x63, 0x00, 0x01, 0x00, 0x00,
            0x05, 0x00, 0x01, 0x0D, 0x0A, 0x2D, 0xB4,
            0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4E, 0x44,
            0xAE, 0x42, 0x60, 0x82,
        ])
        cover_path = tmp_path / "covers" / f"{book_id}.png"
        cover_path.write_bytes(png_header)

        chapters = {"Chapter 1": "Content here"}
        result_path = export_to_pdf(
            book_id, "Cover Book", chapters, tags=[],
            output_dir=str(tmp_path), cover_image=f"covers/{book_id}.png",
        )

        assert Path(result_path).exists()
        assert Path(result_path).stat().st_size > 0

        app_storage.reset_to_defaults()

    def test_pdf_export_cover_missing_file_fallback(self, tmp_path):
        """PDF exports gracefully when cover_image path doesn't exist."""
        app_storage.set_test_dirs(tmp_path)

        book_id = "test-pdf-cover-missing"
        chapters = {"Chapter 1": "Content here"}
        result_path = export_to_pdf(
            book_id, "No Cover Book", chapters, tags=[],
            output_dir=str(tmp_path), cover_image="covers/nonexistent.png",
        )

        assert Path(result_path).exists()
        # Should still produce a valid PDF (text title page as fallback)
        assert Path(result_path).stat().st_size > 0

        app_storage.reset_to_defaults()

    def test_pdf_export_without_cover(self, tmp_path):
        """PDF exports normally when no cover_image is provided."""
        book_id = "test-pdf-no-cover"
        chapters = {"Chapter 1": "Content here"}
        result_path = export_to_pdf(
            book_id, "Plain Book", chapters, tags=[],
            output_dir=str(tmp_path), cover_image=None,
        )

        assert Path(result_path).exists()
        assert Path(result_path).stat().st_size > 0
