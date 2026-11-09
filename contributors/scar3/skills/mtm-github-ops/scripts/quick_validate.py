"""Reuse the shared static-coverage regression suite for canonical skill upgrades."""
from pathlib import Path
import sys
import unittest

for root in Path(__file__).resolve().parents:
    tests = root / '_skill/engines/tests'
    if (tests / 'test_static_coverage.py').is_file():
        suite = unittest.defaultTestLoader.discover(str(tests), pattern='test_static_coverage.py')
        raise SystemExit(0 if unittest.TextTestRunner().run(suite).wasSuccessful() else 1)
print('UNKNOWN: shared static-coverage verifier unavailable', file=sys.stderr)
raise SystemExit(2)
