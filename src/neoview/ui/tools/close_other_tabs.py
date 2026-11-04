"""Close inactive tabs through the viewer's existing persistence path."""
from __future__ import annotations


def run(window) -> None:
    active = window.current_view()
    if active is None or window.current_context().file_path is None:
        window._status.showMessage("Open a PDF before closing other tabs", 2000)
        return None
    closed = 0
    # Stable widget identity matters: every removal shifts subsequent indices.
    for index in range(window._tabs.count() - 1, -1, -1):
        if window._tabs.widget(index) is not active:
            window._close_tab_index(index)
            closed += 1
    window._tabs.setCurrentWidget(active)
    window._status.showMessage(f"Closed {closed} other tab(s)", 2000)
    return None
