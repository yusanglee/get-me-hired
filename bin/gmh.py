#!/usr/bin/env python3
"""get-me-hired launcher for any OS: python3 bin/gmh.py <command> [args] (bin/gmh and bin/gmh.cmd call this)."""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.__main__ import main  # noqa: E402

if __name__ == '__main__':
    sys.exit(main())
