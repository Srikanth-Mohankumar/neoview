"""Bookmark transfer text rules shared with persisted sidecar limits."""
from neoview.persistence.sidecar_store import _MAX_BOOKMARK_TITLE_LEN


def normalized_title(title):
    if not isinstance(title, str):
        raise ValueError("Bookmark titles must be text.")
    title = title.strip()
    if not title or len(title) > _MAX_BOOKMARK_TITLE_LEN:
        raise ValueError(f"Bookmark titles must contain 1-{_MAX_BOOKMARK_TITLE_LEN} characters. "
                         "Rename empty or longer bookmarks before exporting.")
    return title
