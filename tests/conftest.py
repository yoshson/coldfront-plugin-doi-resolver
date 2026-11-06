"""Shared pytest configuration.

The integration tests under ``tests/integration`` boot a real ColdFront
instance and therefore need the ``integration`` dependency group
(``uv sync --group integration``). Without it, they are skipped at
collection time so that plain ``uv run pytest`` keeps working with just
the dev group.
"""

import importlib.util

if importlib.util.find_spec("coldfront") is None:
    collect_ignore = ["integration"]
