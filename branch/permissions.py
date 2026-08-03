from rest_framework.permissions import BasePermission


from core.utils import has_user_branch_access

class IsSuperAdminOrOwnBranchManager(BasePermission):
    """
    super_admin  → full access to any branch.
    branch_manager → access only when the requested branch is in their accessible branches.
    """

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.role == 'super_admin':
            return True
        if user.role == 'branch_manager':
            branch_pk = view.kwargs.get('pk')
            return has_user_branch_access(user, branch_pk)
        return False
