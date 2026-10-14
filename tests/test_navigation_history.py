import pytest

from neoview.ui.navigation_history import HistoryEntry, NavigationHistory

A = HistoryEntry(0, 0.0, 1.0)
B = HistoryEntry(3, 120.0, 1.0)
C = HistoryEntry(7, 40.0, 1.5)
D = HistoryEntry(9, 10.0, 1.5)


def test_empty_history_has_nowhere_to_go():
    h = NavigationHistory()
    assert len(h) == 0
    assert h.current() is None
    assert h.index() == -1
    assert not h.can_go_back()
    assert not h.can_go_forward()
    assert h.back() is None
    assert h.forward() is None


def test_push_makes_entry_current():
    h = NavigationHistory()
    assert h.push(A) is True
    assert h.current() == A
    assert not h.can_go_back()
    h.push(B)
    assert h.current() == B
    assert h.can_go_back()
    assert not h.can_go_forward()


def test_back_and_forward_walk_the_list():
    h = NavigationHistory()
    for e in (A, B, C):
        h.push(e)
    assert h.back() == B
    assert h.back() == A
    assert h.back() is None
    assert h.current() == A
    assert h.forward() == B
    assert h.forward() == C
    assert h.forward() is None
    assert h.current() == C


def test_push_truncates_forward_history():
    h = NavigationHistory()
    for e in (A, B, C):
        h.push(e)
    h.back()
    h.back()  # at A, forward = [B, C]
    h.push(D)
    assert h.entries() == [A, D]
    assert not h.can_go_forward()
    assert h.back() == A


def test_consecutive_duplicates_collapse():
    h = NavigationHistory()
    h.push(A)
    assert h.push(A) is False
    assert h.push(HistoryEntry(0, 0.4, 1.0)) is False  # within the y tolerance
    assert len(h) == 1
    h.push(B)
    h.push(A)  # not consecutive with the first A -> kept
    assert h.entries() == [A, B, A]


@pytest.mark.parametrize(
    "other",
    [
        HistoryEntry(1, 0.0, 1.0),  # different page
        HistoryEntry(0, 5.0, 1.0),  # scrolled beyond tolerance
        HistoryEntry(0, 0.0, 1.25),  # different zoom
    ],
)
def test_entries_that_differ_are_not_collapsed(other):
    h = NavigationHistory()
    h.push(A)
    assert h.push(other) is True
    assert len(h) == 2


def test_duplicate_push_still_drops_forward_history():
    h = NavigationHistory()
    for e in (A, B, C):
        h.push(e)
    h.back()
    h.back()  # at A
    assert h.push(A) is False
    assert h.entries() == [A]
    assert not h.can_go_forward()


def test_history_is_bounded_and_drops_oldest():
    h = NavigationHistory(limit=5)
    entries = [HistoryEntry(i, 0.0, 1.0) for i in range(8)]
    for e in entries:
        h.push(e)
    assert len(h) == 5
    assert h.entries() == entries[3:]
    assert h.current() == entries[7]
    assert h.index() == 4
    steps = 0
    while h.back() is not None:
        steps += 1
    assert steps == 4
    assert h.current() == entries[3]


def test_default_limit_is_100():
    h = NavigationHistory()
    for i in range(150):
        h.push(HistoryEntry(i, 0.0, 1.0))
    assert len(h) == 100
    assert h.entries()[0].page_index == 50


def test_invalid_limit_rejected():
    with pytest.raises(ValueError):
        NavigationHistory(limit=0)


def test_back_records_where_the_user_left_from():
    h = NavigationHistory()
    h.push(A)
    h.push(B)
    scrolled = HistoryEntry(3, 500.0, 1.0)  # user scrolled after landing on B
    assert h.back(current=scrolled) == A
    assert h.forward(current=A) == scrolled


def test_forward_records_current_location():
    h = NavigationHistory()
    h.push(A)
    h.push(B)
    h.back()
    moved = HistoryEntry(0, 300.0, 1.0)
    assert h.forward(current=moved) == B
    assert h.back() == moved


def test_replace_current_updates_in_place_or_pushes_when_empty():
    h = NavigationHistory()
    h.replace_current(A)
    assert h.entries() == [A]
    h.push(B)
    h.replace_current(C)
    assert h.entries() == [A, C]
    assert h.index() == 1


def test_clear_resets():
    h = NavigationHistory()
    h.push(A)
    h.push(B)
    h.clear()
    assert len(h) == 0
    assert h.current() is None
    assert not h.can_go_back()


def test_push_coerces_plain_tuples():
    h = NavigationHistory()
    h.push((2, 10, 2))
    entry = h.current()
    assert isinstance(entry, HistoryEntry)
    assert entry == HistoryEntry(2, 10.0, 2.0)
    assert isinstance(entry.scroll_y, float)


def test_on_change_fires_only_when_state_changes():
    calls = []
    h = NavigationHistory(on_change=lambda b, f: calls.append((b, f)))
    h.push(A)  # (False, False) -> unchanged from initial state
    assert calls == []
    h.push(B)
    assert calls == [(True, False)]
    h.push(C)  # still (True, False)
    assert calls == [(True, False)]
    h.back()
    assert calls[-1] == (True, True)
    h.back()
    assert calls[-1] == (False, True)
    h.forward()
    h.forward()
    assert calls[-1] == (True, False)
    h.clear()
    assert calls[-1] == (False, False)


def test_listeners_can_be_added_and_removed():
    seen = []

    def listener(b, f):
        seen.append((b, f))

    h = NavigationHistory()
    h.add_listener(listener)
    h.push(A)
    h.push(B)
    assert seen == [(True, False)]
    h.remove_listener(listener)
    h.back()
    assert seen == [(True, False)]
    h.remove_listener(listener)  # removing twice is harmless
