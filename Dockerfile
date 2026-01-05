# PDF Crop/Measure Tool - Container Image
# ========================================
# Minimal container for running the PDF viewer with Wayland or X11 forwarding.
#
# BUILD:
#   docker build -t pdf-measure .
#
# RUN (Wayland - GNOME Wayland):
#   docker run -it --rm \
#     -e XDG_RUNTIME_DIR=/run/user/$(id -u) \
#     -e WAYLAND_DISPLAY=$WAYLAND_DISPLAY \
#     -e QT_QPA_PLATFORM=wayland \
#     -v $XDG_RUNTIME_DIR/$WAYLAND_DISPLAY:/run/user/$(id -u)/$WAYLAND_DISPLAY \
#     -v /path/to/pdfs:/pdfs \
#     pdf-measure /pdfs/document.pdf
#
# RUN (X11 - fallback, most compatible):
#   xhost +local:docker
#   docker run -it --rm \
#     -e DISPLAY=$DISPLAY \
#     -e QT_QPA_PLATFORM=xcb \
#     -v /tmp/.X11-unix:/tmp/.X11-unix \
#     -v /path/to/pdfs:/pdfs \
#     pdf-measure /pdfs/document.pdf
#
# NOTES:
#   - For Wayland, ensure $WAYLAND_DISPLAY is set (typically "wayland-0")
#   - For X11, run xhost +local:docker first to allow container access
#   - Mount your PDF directory to /pdfs or any path inside the container

FROM python:3.10-slim

# Install system dependencies for Qt/PySide6
# - libgl1: OpenGL support
# - libegl1: EGL for Wayland
# - libxkbcommon0: Keyboard support
# - libxcb*: X11/xcb support
# - libdbus-1-3: D-Bus for desktop integration
# - fontconfig/fonts-dejavu: Basic fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libegl1 \
    libxkbcommon0 \
    libxkbcommon-x11-0 \
    libxcb1 \
    libxcb-cursor0 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-randr0 \
    libxcb-render0 \
    libxcb-render-util0 \
    libxcb-shape0 \
    libxcb-shm0 \
    libxcb-sync1 \
    libxcb-xfixes0 \
    libxcb-xinerama0 \
    libxcb-xkb1 \
    libdbus-1-3 \
    fontconfig \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir \
    PySide6 \
    PyMuPDF

# Create app directory
WORKDIR /app

# Copy application
COPY pdf_crop_measure.py .

# Make executable
RUN chmod +x pdf_crop_measure.py

# Set entrypoint
ENTRYPOINT ["python", "/app/pdf_crop_measure.py"]

# Default: open file dialog (no arguments)
CMD []
