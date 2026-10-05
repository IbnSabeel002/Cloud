"""Deterministic core of the daily job-hunt agent.

The model fetches pages and writes prose. This package decides: it parses pay
and dates, de-duplicates, applies hard filters, scores, and merges the tracker.
Standard library only, so it runs in any fresh container with no installs.
"""

__version__ = "1.0.0"
