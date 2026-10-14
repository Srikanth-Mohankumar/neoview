"""Back/forward navigation history for a document view.

Pure Python, no Qt. ``PdfView`` owns one ``NavigationHistory`` per document and relays
``on_change`` as its ``history_changed(bool, bool)`` signal.

Model: a list of entries with a cursor pointing at the location the user is at now.

- ``push(entry)`` records a new location: everything after the cursor (the forward history)
  is dropped, the entry is appended and becomes current. If it is the same place as the
  current entry (see ``HistoryEntry.same_place``) nothing is added - consecutive duplicates
  collapse. The list is bounded; when it overflows the oldest entry is dropped.
- ``back(current)`` / ``forward(current)`` move the cursor and return the entry to restore,
  or ``None`` when there is nowhere to go. If ``current`` is given it overwrites the entry
  being left, so returning to it later restores where the user actually was (after
  scrolling), not where they first landed.
- ``replace_current(entry)`` updates the current entry in place without touching the rest.

Usage from a view, for every *jump* (link, outline, search hit, go-to-page dialog):

    history.push(location_before_jump)
    ... perform the jump ...
    history.push(location_after_jump)

Restoring an entry returned by ``back``/``forward`` must not push again; the view guards
its jump code with a flag while restoring.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

DEFAULT_LIMIT = 100

# Two entries closer than this are the same place.
_Y_TOLERANCE_PT = 1.0
_ZOOM_TOLERANCE = 1e-3


class HistoryEntry(NamedTuple):
    """A restorable view location."""

    page_index: int
    scroll_y: float  # vertical offset within the page, in PDF points from its top
    zoom: float

    def same_place(self, other: HistoryEntry) -> bool:
        return (
            self.page_index == other.page_index
            and abs(self.scroll_y - other.scroll_y) < _Y_TOLERANCE_PT
            and abs(self.zoom - other.zoom) < _ZOOM_TOLERANCE
        )


ChangeCallback = Callable[[bool, bool], None]


class NavigationHistory:
    def __init__(self, limit: int = DEFAULT_LIMIT, on_change: ChangeCallback | None = None):
        if limit < 1:
            raise ValueError("limit must be at least 1")
        self._limit = limit
        self._entries: list[HistoryEntry] = []
        self._cursor = -1
        self._listeners: list[ChangeCallback] = []
        if on_change is not None:
            self._listeners.append(on_change)
        self._last_state = (False, False)

    # -- queries -----------------------------------------------------------------------

    @property
    def limit(self) -> int:
        return self._limit

    def __len__(self) -> int:
        return len(self._entries)

    def entries(self) -> list[HistoryEntry]:
        return list(self._entries)

    def index(self) -> int:
        """Cursor position, -1 when empty."""
        return self._cursor

    def current(self) -> HistoryEntry | None:
        if self._cursor < 0:
            return None
        return self._entries[self._cursor]

    def can_go_back(self) -> bool:
        return self._cursor > 0

    def can_go_forward(self) -> bool:
        return 0 <= self._cursor < len(self._entries) - 1

    # -- listeners ---------------------------------------------------------------------

    def add_listener(self, callback: ChangeCallback) -> None:
        self._listeners.append(callback)

    def remove_listener(self, callback: ChangeCallback) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify(self) -> None:
        state = (self.can_go_back(), self.can_go_forward())
        if state == self._last_state:
            return
        self._last_state = state
        for callback in list(self._listeners):
            callback(*state)

    # -- mutation ----------------------------------------------------------------------

    def push(self, entry: HistoryEntry) -> bool:
        """Record ``entry`` as the new current location. Returns False if it collapsed."""
        entry = HistoryEntry(int(entry[0]), float(entry[1]), float(entry[2]))
        current = self.current()
        if current is not None and current.same_place(entry):
            # Still drop the forward history: the user navigated, just not far.
            if self.can_go_forward():
                del self._entries[self._cursor + 1 :]
                self._notify()
            return False
        del self._entries[self._cursor + 1 :]
        self._entries.append(entry)
        overflow = len(self._entries) - self._limit
        if overflow > 0:
            del self._entries[:overflow]
        self._cursor = len(self._entries) - 1
        self._notify()
        return True

    def replace_current(self, entry: HistoryEntry) -> None:
        """Overwrite the current entry (e.g. after the user scrolled). Pushes if empty."""
        if self._cursor < 0:
            self.push(entry)
            return
        self._entries[self._cursor] = HistoryEntry(
            int(entry[0]), float(entry[1]), float(entry[2])
        )

    def back(self, current: HistoryEntry | None = None) -> HistoryEntry | None:
        if not self.can_go_back():
            return None
        if current is not None:
            self.replace_current(current)
        self._cursor -= 1
        self._notify()
        return self._entries[self._cursor]

    def forward(self, current: HistoryEntry | None = None) -> HistoryEntry | None:
        if not self.can_go_forward():
            return None
        if current is not None:
            self.replace_current(current)
        self._cursor += 1
        self._notify()
        return self._entries[self._cursor]

    def clear(self) -> None:
        self._entries.clear()
        self._cursor = -1
        self._notify()
