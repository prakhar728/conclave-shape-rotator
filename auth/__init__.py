"""Cookie-based authentication for the Conclave v1 product.

`session.py` issues + reads opaque server-side session tokens; `routes.py`
mounts the `/auth/v1/*` HTTP surface. The legacy `/auth/send-otp` family in
`api/routes.py` predates this package and is deliberately untouched — both
surfaces coexist until the old `web/` SPA is retired in Phase 1.12.
"""
