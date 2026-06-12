"""FastAPI serving deployable — separate workspace member from the de_playground core.

The package marker is here so static analysis (import-linter, mypy, pyright) can scan
api/ as `api.*` and enforce the serving-plane isolation contract: api may import ONLY
`de_playground.contracts`, never the pipeline runtime (common/extract/transform/load/
config). See docs/PYTHON_HARDENING_PLAN.md WS3 + WS7.
"""

from __future__ import annotations
