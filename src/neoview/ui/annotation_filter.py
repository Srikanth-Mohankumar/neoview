"""Controls and matching for the annotations sidebar."""

from PySide6.QtWidgets import QComboBox, QLineEdit, QVBoxLayout, QWidget

from neoview.models.view_state import AnnotationRecord


def annotation_matches(record: AnnotationRecord, kind: str, query: str) -> bool:
    """Match type and case-insensitive annotation contents without changing records."""
    if kind != "all" and record.type != kind:
        return False
    needle = query.strip().casefold()
    return not needle or needle in record.contents.casefold()


def build_filter_controls(
    type_combo: QComboBox, parent: QWidget | None = None,
) -> tuple[QWidget, QLineEdit]:
    """Group the existing type selector with an accessible text filter."""
    container = QWidget(parent)
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    layout.addWidget(type_combo)
    text_filter = QLineEdit(container)
    text_filter.setObjectName("annotation_text_filter")
    text_filter.setAccessibleName("Filter annotation text")
    text_filter.setPlaceholderText("Filter annotation text")
    text_filter.setToolTip("Show annotations whose text contains these words")
    text_filter.setClearButtonEnabled(True)
    layout.addWidget(text_filter)
    return container, text_filter
