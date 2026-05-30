"""Tenancy (organization) scoping primitives.

This package defines:
- a request-scoped tenant context (`current_org_id`)
- a SQLAlchemy mixin (`TenantScopedModel`) for tables that must be tenant-isolated
- ORM-level enforcement that auto-injects `WHERE org_id = :current_org_id`
"""

