"""An isolated PDF editing session; the viewer's document is never mutated."""
from __future__ import annotations

import copy
import os
import shutil
import tempfile
import uuid
from dataclasses import replace
from pathlib import Path

import fitz

from neoview.models.view_state import DocumentSidecarState
from neoview.persistence.sidecar_store import load_sidecar, save_sidecar, sidecar_path_for


class PageOrganization:
    def __init__(self, document: fitz.Document, state: DocumentSidecarState):
        if (document.is_encrypted or document.needs_pass
                or (document.metadata or {}).get("encryption")):
            raise ValueError("Page organization is unavailable for password-protected PDFs.")
        self.document = fitz.open(stream=document.tobytes(), filetype="pdf")
        self.order = list(range(document.page_count))
        self.state = copy.deepcopy(state)
        self.dirty = False

    def close(self):
        self.document.close()

    def reorder(self, order: list[int]):
        if sorted(order) != sorted(self.order):
            raise ValueError("Reordering must retain every remaining page exactly once.")
        if order != self.order:
            self.order = list(order)
            self.dirty = True

    def delete(self, rows: list[int]):
        selected = set(rows)
        if not selected or any(row < 0 or row >= len(self.order) for row in selected):
            raise ValueError("Select valid pages to delete.")
        if len(selected) == len(self.order):
            raise ValueError("A PDF must contain at least one page.")
        self.order = [page for row, page in enumerate(self.order) if row not in selected]
        self.dirty = True

    def insert(self, path: str, before: int):
        if not 0 <= before <= len(self.order):
            raise ValueError("Invalid insertion position.")
        with fitz.open(path) as source:
            if source.needs_pass or (source.metadata or {}).get("encryption"):
                raise ValueError("Password-protected PDFs cannot currently be merged.")
            if not source.is_pdf or source.page_count == 0:
                raise ValueError("Choose a nonempty PDF.")
            start = self.document.page_count
            toc = self.document.get_toc()
            incoming_toc = source.get_toc()
            self.document.insert_pdf(source)
            self.document.set_toc(toc + [
                [level, title, page + start if page > 0 else page]
                for level, title, page in incoming_toc
            ])
            self.order[before:before] = range(start, self.document.page_count)
        incoming = load_sidecar(path)
        for name in ("annotations", "bookmarks"):
            getattr(self.state, name).extend(
                replace(record, id=uuid.uuid4().hex, page=record.page + start)
                for record in getattr(incoming, name)
            )
        self.dirty = True

    def mapped_state(self) -> DocumentSidecarState:
        mapping = {old: new for new, old in enumerate(self.order)}
        return DocumentSidecarState(
            annotations=[replace(a, page=mapping[a.page]) for a in self.state.annotations
                         if a.page in mapping],
            bookmarks=[replace(b, page=mapping[b.page]) for b in self.state.bookmarks
                       if b.page in mapping],
        )

    def save(self, path: str):
        """Stage both outputs before replacing either; roll back on replacement failure."""
        target = Path(path).absolute()
        sidecar = Path(sidecar_path_for(str(target)))
        with tempfile.TemporaryDirectory(prefix=".neoview-pages-", dir=target.parent) as work:
            staged = Path(work) / "output.pdf"
            with fitz.open(stream=self.document.tobytes(), filetype="pdf") as output:
                toc = output.get_toc()
                output.select(self.order)
                mapping = {old + 1: new + 1 for new, old in enumerate(self.order)}
                # Keep hierarchy valid when a deleted page owned a parent entry.
                remapped = []
                previous_level = 0
                for level, title, page in toc:
                    if page not in mapping:
                        continue
                    level = min(level, previous_level + 1)
                    remapped.append([level, title, mapping[page]])
                    previous_level = level
                output.set_toc(remapped)
                output.save(str(staged), garbage=4, deflate=True)
            save_sidecar(str(staged), self.mapped_state())
            pairs = [(staged, target), (Path(sidecar_path_for(str(staged))), sidecar)]
            backups = {}
            for _, destination in pairs:
                if destination.exists():
                    backup = Path(work) / (destination.name + ".backup")
                    shutil.copy2(destination, backup)
                    backups[destination] = backup
            replaced = []
            try:
                for source, destination in pairs:
                    os.replace(source, destination)
                    replaced.append(destination)
            except OSError:
                for destination in reversed(replaced):
                    if destination in backups:
                        os.replace(backups[destination], destination)
                    else:
                        destination.unlink(missing_ok=True)
                raise
        self.dirty = False
