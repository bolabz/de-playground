"""de_playground — local data-engineering reference rig (Azure-shaped, free/OSS).

No `__all__`: sub-packages (`common`, `config`, `contracts`, `extract`, `load`,
`transform`) carry heavy optional imports (pyspark, dlt) — eagerly hoisting them into
the top-level `__init__` would force every consumer to pay for them. Reach for the
sub-packages explicitly: `from de_playground.contracts import FactSalesDoc`.
"""

from __future__ import annotations
