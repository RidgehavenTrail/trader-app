"""Factor builders — one module per factor, each exporting compute() -> reading.

Pure functions: pull data, derive {light, value, metric, state?, asof, extras?}.
No Flask, no scheduling, no state WRITES. (READ-ONLY access to the snapshot log
via stoplight.store is allowed — silicon_e's 63-bar roll and the memory canary's
event reconstruction depend on it; the scheduler owns all writes.) Metric
strings are ASCII-only — Windows cp1252 console logs choke on glyphs; arrows
live in extras for the frontend to render. Each is runnable standalone:
    python -m stoplight.factors.<name>
"""
