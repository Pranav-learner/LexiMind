"""Minimal authentication module (Phase 3, Module 1).

Gives `owner_id` a real identity so workspaces can be scoped per user, without pulling in a
full OAuth/JWT stack. Crypto is stdlib-only (see `security.py`). Collaboration, roles, and
permissions are intentionally out of scope and arrive in a later module.
"""
