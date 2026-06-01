from rest_framework.permissions import BasePermission


class IsSuperAdminOrOwnBranchManager(BasePermission):
    """
    super_admin  → full access to any branch.
    branch_manager → access only when the requested branch == their own branch.
    """

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.role == 'super_admin':
            return True
        if user.role == 'branch_manager':
            branch_pk = view.kwargs.get('pk')
            return str(user.branch_id) == str(branch_pk)
        return False
