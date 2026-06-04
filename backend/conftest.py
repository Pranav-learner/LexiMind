"""Pytest bootstrap.

Ensures the backend/ directory (this file's dir) is on sys.path so `import app...`
resolves regardless of where pytest is invoked from. Also forces the reranker off by
default so the unit/integration suite never tries to download the ~1GB cross-encoder.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

# Tests that specifically exercise the reranker inject a fake model instead.
os.environ.setdefault("LEXIMIND_ENABLE_RERANKER", "0")
