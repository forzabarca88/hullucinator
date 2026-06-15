"""
JSON file persistence layer.

Uses an absolute path derived from the project root so that storage works
regardless of the working directory from which the server is started.
"""
import json
from pathlib import Path
from typing import Optional, List
from app.schemas import BookState

# Absolute path: one level up from this file's parent (app/) is the project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "books"
EXPORTS_DIR = PROJECT_ROOT / "exports"


def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def ensure_exports_dir():
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)


def save_book(book_id: str, state: BookState):
    """Persist a BookState to disk as a JSON file."""
    if state.id != book_id:
        raise ValueError(f"Book ID mismatch: filename '{book_id}' != model id '{state.id}'")
    ensure_data_dir()
    file_path = DATA_DIR / f"{book_id}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(state.model_dump_json(indent=4))


def load_book(book_id: str) -> Optional[BookState]:
    """Load a BookState from disk. Returns None if file doesn't exist."""
    file_path = DATA_DIR / f"{book_id}.json"
    if not file_path.exists():
        return None

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        return BookState(**data)


def list_books() -> List[BookState]:
    """Return all stored books sorted by creation time (newest first)."""
    books = []
    ensure_data_dir()
    for file_path in sorted(DATA_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            books.append(BookState(**data))
        except (json.JSONDecodeError, Exception):
            continue
    return books
