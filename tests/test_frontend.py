"""Frontend integrity tests — catch CSP and path bugs at test time."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _read_js_files():
    """Return dict of filename -> content for all .js files in static/."""
    files = {}
    for js_file in STATIC_DIR.glob("js/*.js"):
        files[js_file.name] = js_file.read_text()
    return files


class TestCSPCompliance:
    """Verify JS source doesn't violate the CSP policy."""

    def test_no_inline_event_handlers(self):
        """
        CSP directive 'script-src self' blocks HTML inline event handlers
        (onclick="...", onerror="...", etc.). Using them causes silent
        failures — the browser blocks the handler without any visible error.

        Buttons must use data-* attributes and attach listeners via
        addEventListener instead.

        Note: .onclick = () => ... (property assignment) is allowed by CSP.
        Only HTML attribute-style handlers (onclick="...") are blocked.
        """
        js_files = _read_js_files()
        # Match HTML attribute-style inline handlers (e.g. onclick="func()")
        # NOT property assignments (.onclick = ...)
        pattern = re.compile(r'"on(click|error|load|submit|change|focus|blur|keydown|keyup|keypress)=')

        violations = []
        for name, content in js_files.items():
            for match in pattern.finditer(content):
                violations.append(
                    f"{name}: inline {match.group(1)} handler at position {match.start()}"
                )

        assert not violations, (
            "Inline event handlers violate CSP and are silently blocked by the browser. "
            "Use data-* attributes + addEventListener instead.\n\n"
            + "\n".join(violations)
        )


class TestApiPathConsistency:
    """Verify frontend API paths match backend endpoint prefixes."""

    def test_api_fetch_paths(self):
        """
        All apiFetch calls must use paths starting with /books/ (the apiFetch
        wrapper prepends the /api prefix). Paths starting with /api/ would
        result in /api/api/ which is a 404.
        """
        js_files = _read_js_files()

        # apiFetch prepends '/api' so paths should NOT start with '/api/'
        bad_prefix_pattern = re.compile(r"apiFetch\s*\(\s*['\"](/api/)")

        violations = []
        for name, content in js_files.items():
            for match in bad_prefix_pattern.finditer(content):
                violations.append(
                    f"{name}: apiFetch called with '/api/' prefix (will double-prefix). "
                    f"Use '/books/...' instead."
                )

        assert not violations, "\n".join(violations)

    def test_export_links_use_api_prefix(self):
        """
        Export links use href attributes (not apiFetch), so they must
        include the /api/ prefix directly. Accepts both literal '/api/'
        and the ${API} template literal constant.
        """
        js_files = _read_js_files()

        # Find href attributes pointing to /books/.../export/...
        export_href_pattern = re.compile(r"href\s*=\s*['\"]([^'\"]*/books/[^'\"]*/export/[^'\"]*)['\"]")

        violations = []
        for name, content in js_files.items():
            for match in export_href_pattern.finditer(content):
                href_value = match.group(1)
                # ${API} is the correct way to reference the /api prefix
                if "/api/" not in href_value and "${API}" not in href_value:
                    violations.append(
                        f"{name}: export href missing /api/ prefix. "
                        f"Should be '/api/books/.../export/...' or '${{{API}}}/books/...'."
                    )

        assert not violations, "\n".join(violations)
