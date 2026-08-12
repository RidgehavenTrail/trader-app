"""Shared data fetchers — the only stoplight code that touches the internet.

Factor builders import from here so retry/backoff/unit handling lives in ONE
place per source, not 16.
"""
