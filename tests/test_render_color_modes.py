"""Reading-mode recolouring inside the render scheduler (banded, bounded steps)."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from PySide6.QtGui import QImage

from neoview.ui import render_scheduler
from neoview.ui.page_modes import apply_color_mode
from neoview.ui.render_scheduler import RenderRequest, RenderScheduler, _Job


def _make_pdf(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    for k in range(30):
        page.draw_circle((40 + (k * 37) % 300, 40 + k * 14), 9, color=(0, 0, 1), fill=(1, 0, 0))
        page.insert_text((30, 25 + k * 15), f"line {k} of text", fontsize=10)
    doc.save(str(path))
    doc.close()
    return path


def _render(doc, mode: str, zoom: float = 1.5) -> QImage:
    got: list[QImage] = []
    scheduler = RenderScheduler()
    scheduler.page_rendered.connect(lambda _i, _g, _z, _f, img: got.append(img))
    scheduler.schedule([RenderRequest(0, doc[0], zoom, 1.0, mode)], generation=1)
    while scheduler.pending_count():
        scheduler._tick()
    assert len(got) == 1
    return got[0]


@pytest.mark.parametrize("mode", ["night", "sepia"])
def test_strip_recolouring_equals_whole_image_transform(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(render_scheduler, "COLOR_STRIP_PIXELS", 30_000)  # many strips
    doc = fitz.open(str(_make_pdf(tmp_path / "doc.pdf")))
    try:
        plain = _render(doc, "normal")
        colored = _render(doc, mode)
        expected = apply_color_mode(plain, mode).convertToFormat(colored.format())
        assert colored.size() == plain.size()
        assert colored == expected
    finally:
        doc.close()


def test_normal_mode_is_untouched(tmp_path):
    doc = fitz.open(str(_make_pdf(tmp_path / "doc.pdf")))
    try:
        img = _render(doc, "normal")
        ref_pix = doc[0].get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        ref = QImage(ref_pix.samples, ref_pix.width, ref_pix.height, ref_pix.stride,
                     QImage.Format.Format_RGB888).convertToFormat(QImage.Format.Format_RGB32)
        assert img == ref
    finally:
        doc.close()


def test_recolouring_runs_in_bounded_strips(tmp_path, monkeypatch):
    monkeypatch.setattr(render_scheduler, "COLOR_STRIP_PIXELS", 50_000)
    doc = fitz.open(str(_make_pdf(tmp_path / "doc.pdf")))
    try:
        job = _Job(RenderRequest(0, doc[0], 2.0, 1.0, "night"), generation=1)
        steps = 0
        while not job.step():
            steps += 1
        assert job.strips, "night mode should add recolouring steps"
        assert len(job.strips) > 1
        width = job.colored.width()
        assert all(h * width <= 50_000 for _y, h in job.strips)
        # Strips cover every row exactly once.
        rows = [y + i for y, h in job.strips for i in range(h)]
        assert rows == list(range(job.colored.height()))
        assert steps >= len(job.clips) + len(job.strips) - 1
    finally:
        doc.close()


def test_same_target_includes_color_mode(tmp_path):
    doc = fitz.open(str(_make_pdf(tmp_path / "doc.pdf")))
    try:
        a = RenderRequest(0, doc[0], 1.0, 1.0, "normal")
        assert a.same_target(RenderRequest(0, doc[0], 1.0, 1.0))
        assert not a.same_target(RenderRequest(0, doc[0], 1.0, 1.0, "night"))
    finally:
        doc.close()
