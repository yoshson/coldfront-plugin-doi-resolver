#!/usr/bin/env python
"""Django command-line utility for the ColdFront test instance.

This repository is a plugin, not a Django project, but pytest-django
locates the test project (``tests/integration/settings.py``) through the
presence of this file. It also allows driving the basic ColdFront test
instance by hand, e.g. with the "integration" dependency group installed:

    uv run --group integration python manage.py check
    DB_URL=sqlite:///coldfront.db uv run --group integration python manage.py migrate
"""

import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.integration.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django is not installed (no --group integration environment?)."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
