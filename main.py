#!/usr/bin/env python3
"""Entry point: `python3 main.py` launches the Disputatio TUI.

Equivalent to `pip install -e .` and running the `disputatio` console script -
this file just exists so nothing needs to be installed first.
"""

from disputatio.app import run

if __name__ == "__main__":
    run()
