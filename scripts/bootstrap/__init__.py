"""scripts.bootstrap — one-shot seeders, backfills, and already-applied config migrations.

Moved out of the repo root in the 2026-07 token-optimization pass: these are build-time /
migration tools, not runtime modules, and they were polluting the root import namespace.
All patch_* migrations here carry idempotency guards and have already been applied.
"""
