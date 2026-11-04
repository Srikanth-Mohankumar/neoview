"""Close document tabs after the active tab through normal persistence paths."""
from __future__ import annotations


def run(window) -> None:
    """Retain the active tab and every tab before it; save all closed sidecars."""
    current = window._tabs.currentIndex()
    if current < 0:
        window._status.showMessage("No tabs to close", 2000)
        return None
    closed = window._tabs.count() - current - 1
    for index in range(window._tabs.count() - 1, current, -1):
        window._close_tab_index(index)
    message = f"Closed {closed} tabs to the right" if closed else "No tabs to the right"
    window._status.showMessage(message, 2000)
    return None
