"""Host-side Claude bridge (run via ``make bridge``).

A dedicated, dependency-free subpackage so ``app/bridge/server.py`` runs standalone
on the host under bare ``python3`` (the runner image needs no claude/auth mount). It
deliberately lives OUTSIDE ``app/ai`` because a script run directly puts its own
directory on ``sys.path[0]`` — and ``app/ai/types.py`` would shadow the stdlib
``types`` module, breaking the daemon's stdlib imports.
"""
