from setuptools import setup

setup(
    name="neoview",
    version="0.1.0",
    description="NeoView PDF viewer with rectangular crop/measure tool",
    py_modules=["pdf_crop_measure"],
    install_requires=["PySide6", "PyMuPDF"],
    entry_points={"console_scripts": ["neoview=pdf_crop_measure:main"]},
)
