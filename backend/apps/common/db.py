"""Conexiones a la base en los procesos largos (worker de integraciones y
monitor de alertas)."""

from django.db import connections


def close_stale_connections():
    """Como ``close_old_connections()``, pero sin tocar una conexión que está
    dentro de una transacción abierta.

    Cerrarla le cortaría la transacción a quien llamó al comando (un
    ``call_command`` dentro de ``atomic()``, o un TestCase sobre Postgres:
    con SQLite en memoria Django ignora el cierre y el problema no se ve; en
    CI rompía los tests de ``run_monitor`` y los siguientes de su clase).
    Django hace lo mismo en el ciclo de un request: nunca cierra conexiones a
    mitad de una transacción.
    """
    for conn in connections.all(initialized_only=True):
        if not conn.in_atomic_block:
            conn.close_if_unusable_or_obsolete()
