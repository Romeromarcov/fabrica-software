#!/usr/bin/env python
"""Entrypoint de gestión del proyecto fixture mínimo (solo para ejercitar los gates)."""
import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover - solo en CI cuando falta Django
        raise ImportError(
            "Django no está instalado. Este proyecto fixture solo se usa en el job de "
            "CI 'runtime-gates'. Instala django + psycopg2-binary antes de correrlo."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
