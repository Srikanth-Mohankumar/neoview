"""Export unique embedded PDF image resources without rasterizing pages."""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox

from neoview.ui.tool_support import snapshot


def image_xrefs(document) -> list[int]:
    """Return unique image references in first-page occurrence order."""
    seen = set()
    result = []
    for page_number in range(document.page_count):
        for image in document.get_page_images(page_number, full=True):
            # Soft masks are embedded image resources too; retain them as
            # separate files rather than flattening or losing transparency data.
            for xref in image[:2]:
                if xref > 0 and xref not in seen:
                    seen.add(xref)
                    result.append(xref)
    return result


def extract_embedded_images(document, destination: str) -> list[Path]:
    """Stage original image bytes and publish a new, never-overwritten folder.

    Images with the same PDF resource reference appear once. A soft mask remains
    a separate PDF resource; this exports the stored image bytes, not a flattened
    rendering of transparency or page appearance.
    """
    target = Path(destination).absolute()
    if os.path.lexists(target):
        raise FileExistsError("Choose a parent folder without an existing image output folder.")
    xrefs = image_xrefs(document)
    if not xrefs:
        return []
    stage = Path(tempfile.mkdtemp(prefix=".neoview-images-", dir=target.parent))
    names = []
    published = False
    try:
        for index, xref in enumerate(xrefs, 1):
            resource = document.extract_image(xref)
            extension = resource.get("ext", "")
            content = resource.get("image")
            if not isinstance(extension, str) or not re.fullmatch(r"[a-zA-Z0-9]{1,10}", extension):
                raise ValueError("The PDF contains an image with an invalid file extension.")
            if not isinstance(content, bytes) or not content:
                raise ValueError("The PDF image could not be extracted.")
            name = f"image-{index:04d}-xref-{xref}.{extension.lower()}"
            (stage / name).write_bytes(content)
            names.append(name)
        # Reserve the destination rather than replacing an existing directory.
        # Publishing individual already-staged files is cross-platform; on any
        # failure only this newly created output directory is removed.
        target.mkdir()
        published = True
        for name in names:
            os.rename(stage / name, target / name)
    except Exception:
        if published:
            shutil.rmtree(target)
        raise
    finally:
        shutil.rmtree(stage)
    return [target / name for name in names]


def run(window) -> None:
    with snapshot(window) as (document, _state, source):
        if not image_xrefs(document):
            QMessageBox.information(window, "Extract Images", "This PDF has no embedded images.")
            return
        parent = QFileDialog.getExistingDirectory(
            window, "Choose Parent Folder for Extracted Images", str(Path(source).parent),
        )
        if not parent:
            return
        destination = Path(parent) / (Path(source).stem + "-images")
        images = extract_embedded_images(document, str(destination))
        QMessageBox.information(
            window, "Images Extracted", f"Saved {len(images)} embedded image(s) to {destination}",
        )
