"""
core/mixins.py — Shared model & queryset mixins for consistent patterns.
"""

import uuid
from django.db import models


class TimestampMixin(models.Model):
    """Adds created_at / updated_at to any model."""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SoftDeleteMixin(models.Model):
    """Soft-delete pattern with is_deleted flag."""
    is_deleted = models.BooleanField(default=False)

    class Meta:
        abstract = True

    def soft_delete(self):
        # self.is_deleted = True
        # self.save(update_fields=['is_deleted'])
        pass


class UUIDPrimaryKeyMixin(models.Model):
    """UUID as primary key for all models."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class BranchScopedQuerySet(models.QuerySet):
    """
    QuerySet mixin that adds .for_branch(branch_id) helper.
    Usage:
        class MyModel(models.Model):
            branch = models.ForeignKey('branch.Branch', ...)
            objects = BranchScopedManager()
    """

    def for_branch(self, branch_id):
        """Filter queryset to a specific branch."""
        if branch_id:
            return self.filter(branch_id=branch_id)
        return self

    def active(self):
        """Filter to non-deleted records (if model has is_deleted)."""
        if hasattr(self.model, 'is_deleted'):
            return self.filter(is_deleted=False)
        return self.all()


class BranchScopedManager(models.Manager):
    """Manager that uses BranchScopedQuerySet."""

    def get_queryset(self):
        return BranchScopedQuerySet(self.model, using=self._db)

    def for_branch(self, branch_id):
        return self.get_queryset().for_branch(branch_id)

    def active(self):
        return self.get_queryset().active()
