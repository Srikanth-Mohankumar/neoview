#!/usr/bin/env python3
"""Legacy entry point for NeoView.

This file remains for backward compatibility. Prefer `neoview` CLI.
"""

import os
import sys

repo_root = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.join(repo_root, "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from neoview.app import main


if __name__ == "__main__":
    main()
