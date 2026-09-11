from rest_framework import viewsets, filters, status
from rest_framework.decorators import api_view, action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from core.utils import get_user_branch_ids, get_user_branch_id

from .models import ItemCategory, Item, StockTransaction, ItemAllocation
from django.core.exceptions import ValidationError as DjangoValidationError
from .serializers import (
    ItemCategorySerializer, ItemSerializer,
    StockTransactionSerializer, ItemAllocationSerializer
)
from .utils import get_inventory_forecast

from students.models import StudentProfile
from faculty.models import FacultyProfile
from django.contrib.auth import get_user_model

User = get_user_model()
SALES_ROLES = {
    'sales_senior_executive',
    'sales_executive',
    'tele_caller',
    'senior_tele_caller',
    'associate_bdm',
}

def resolve_profile_id(model_class, id_val):
    if not id_val:
        return None
    if model_class.objects.filter(id=id_val).exists():
        return id_val
    if User.objects.filter(id=id_val).exists():
        profile = model_class.objects.filter(user_id=id_val).first()
        if profile:
            return str(profile.id)
from rest_framework.permissions import IsAuthenticated, SAFE_METHODS

class IsStaffOrReadOnlyForStudentParent(IsAuthenticated):
    """
    Ensures students and parents only have read-only (GET, HEAD, OPTIONS) access to inventory.
    Only staff, faculty, and admins can perform write/mutation actions.
    """
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        if getattr(request.user, 'role', None) in ('student', 'parents') and request.method not in SAFE_METHODS:
            return False
        return True


class ItemCategoryViewSet(viewsets.ModelViewSet):
    queryset = ItemCategory.objects.all()
    serializer_class = ItemCategorySerializer
    permission_classes = [IsStaffOrReadOnlyForStudentParent]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['branch', 'is_active']
    search_fields = ['name', 'description']

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()
        if user.role != 'super_admin':
            branch_ids = get_user_branch_ids(user)
            if branch_ids:
                qs = qs.filter(branch_id__in=branch_ids)
        return qs

    def create(self, request, *args, **kwargs):
        user = request.user
        # Make a mutable copy of the incoming data
        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)

        if user.role == 'super_admin':
            # Super admin must explicitly provide the branch
            if not data.get('branch'):
                return Response(
                    {'branch': 'Branch is required when creating a category as a Super Admin.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            # For branch managers and other non-super_admin roles, inject branch automatically
            branch_id = get_user_branch_id(user)
            if branch_id and not data.get('branch'):
                data['branch'] = str(branch_id)

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        serializer.save()


class ItemViewSet(viewsets.ModelViewSet):
    queryset = Item.objects.select_related('category').all()
    serializer_class = ItemSerializer
    permission_classes = [IsStaffOrReadOnlyForStudentParent]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['category', 'category__branch', 'is_active']
    search_fields = ['name', 'description']

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()
        if user.role != 'super_admin':
            branch_ids = get_user_branch_ids(user)
            if branch_ids:
                qs = qs.filter(category__branch_id__in=branch_ids)
        return qs


class StockTransactionViewSet(viewsets.ModelViewSet):
    queryset = StockTransaction.objects.select_related('item', 'created_by').all()
    serializer_class = StockTransactionSerializer
    permission_classes = [IsStaffOrReadOnlyForStudentParent]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['item', 'transaction_type', 'item__category__branch']
    ordering_fields = ['transaction_date']

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()
        if user.role != 'super_admin':
            branch_ids = get_user_branch_ids(user)
            if branch_ids:
                qs = qs.filter(item__category__branch_id__in=branch_ids)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class ItemAllocationViewSet(viewsets.ModelViewSet):
    queryset = ItemAllocation.objects.select_related('item', 'student', 'faculty', 'sales_user', 'issued_by').all()
    serializer_class = ItemAllocationSerializer
    permission_classes = [IsStaffOrReadOnlyForStudentParent]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['item', 'status', 'student', 'faculty', 'sales_user', 'item__category__branch']
    search_fields = ['student__admission_number', 'student__first_name', 'faculty__user__name', 'sales_user__name', 'item__name']

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()

        if user.role in SALES_ROLES:
            return qs.filter(sales_user=user)

        if user.role == 'student':
            return qs.filter(student__user=user)

        if user.role == 'parents':
            from students.models import ParentLink, StudentProfile
            linked_ids = list(ParentLink.objects.filter(parent=user).values_list('student_id', flat=True))
            if not linked_ids and hasattr(user, 'linked_students'):
                linked_ids = list(StudentProfile.objects.filter(user__in=user.linked_students.all()).values_list('id', flat=True))
            return qs.filter(student_id__in=linked_ids)

        if user.role == 'faculty':
            return qs.filter(faculty__user=user)

        if user.role != 'super_admin':
            branch_ids = get_user_branch_ids(user)
            if branch_ids:
                qs = qs.filter(item__category__branch_id__in=branch_ids)
        return qs

    @action(detail=False, methods=['get'], url_path='my')
    def my_allocations(self, request):
        """
        Returns all items allocated to the currently authenticated user
        (supports sales users, students, parents, and faculty).
        Supports status filter (?status=issued or ?status=returned).
        For parents, also supports ?student=<student_id> to view a specific child's items.
        """
        user = request.user
        qs = self.get_queryset()
        status_filter = request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        student_id = request.query_params.get('student')
        if student_id and user.role == 'parents':
            qs = qs.filter(student_id=student_id)
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        data = request.data.copy() if hasattr(request.data, 'copy') else request.data
        if 'student' in data and data['student']:
            data['student'] = resolve_profile_id(StudentProfile, data['student'])
        if 'faculty' in data and data['faculty']:
            data['faculty'] = resolve_profile_id(FacultyProfile, data['faculty'])
            
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        try:
            self.perform_create(serializer)
        except DjangoValidationError as e:
            return Response({'error': e.message}, status=status.HTTP_400_BAD_REQUEST)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        allocation = serializer.save(issued_by=self.request.user)
        # Create a stock transaction to deduct the allocated items
        if allocation.status == 'issued':
            StockTransaction.objects.create(
                item=allocation.item,
                transaction_type='allocation',
                quantity=-allocation.quantity,
                reference=f"Allocated to {self._allocation_recipient(allocation)}",
                notes=allocation.notes,
                created_by=self.request.user
            )
            # Notify super admins
            self._notify_allocation(allocation)

    @action(detail=True, methods=['post'])
    def return_item(self, request, pk=None):
        allocation = self.get_object()
        if allocation.status == 'returned':
            return Response({'detail': 'Item is already returned.'}, status=status.HTTP_400_BAD_REQUEST)
        
        return_notes = request.data.get('return_notes', '')
        allocation.status = 'returned'
        allocation.returned_at = timezone.now()
        allocation.return_notes = return_notes
        allocation.save()

        # Add stock back
        StockTransaction.objects.create(
            item=allocation.item,
            transaction_type='return',
            quantity=allocation.quantity,
            reference=f"Return from allocation {allocation.id}",
            notes=return_notes,
            created_by=request.user
        )
        return Response({'status': 'Item returned successfully.'})

    @action(detail=False, methods=['post'])
    def bulk_issue(self, request):
        student_id = request.data.get('student')
        faculty_id = request.data.get('faculty')
        sales_user_id = request.data.get('sales_user')
        
        student_id = resolve_profile_id(StudentProfile, student_id)
        faculty_id = resolve_profile_id(FacultyProfile, faculty_id)
        sales_user = User.objects.filter(id=sales_user_id).first() if sales_user_id else None

        allocations_data = request.data.get('allocations', [])

        target_count = sum(bool(target) for target in (student_id, faculty_id, sales_user_id))
        if target_count != 1:
            return Response({'error': 'Provide exactly one of student, faculty, or sales_user.'}, status=status.HTTP_400_BAD_REQUEST)
        if sales_user_id and (not sales_user or sales_user.role not in SALES_ROLES):
            return Response({'error': 'The selected sales_user must have a sales role.'}, status=status.HTTP_400_BAD_REQUEST)
        
        if not allocations_data or not isinstance(allocations_data, list):
            return Response({'error': 'Must provide a list of allocations.'}, status=status.HTTP_400_BAD_REQUEST)

        created_allocations = []
        from django.db import transaction

        try:
            with transaction.atomic():
                for alloc_data in allocations_data:
                    item_id = alloc_data.get('item')
                    quantity = int(alloc_data.get('quantity', 1))
                    notes = alloc_data.get('notes', '')

                    item = Item.objects.select_for_update().get(id=item_id)

                    # Pre-validate stock before creating anything
                    if item.total_stock - quantity < 0:
                        raise DjangoValidationError(
                            f"Insufficient stock for '{item.name}'. "
                            f"Available: {item.total_stock}, Requested: {quantity}."
                        )

                    allocation = ItemAllocation.objects.create(
                        item=item,
                        student_id=student_id,
                        faculty_id=faculty_id,
                        sales_user=sales_user,
                        quantity=quantity,
                        status='issued',
                        notes=notes,
                        issued_by=request.user
                    )
                    
                    # Create StockTransaction
                    StockTransaction.objects.create(
                        item=item,
                        transaction_type='allocation',
                        quantity=-quantity,
                        reference=f"Bulk allocation to {self._allocation_recipient(allocation)}",
                        notes=notes,
                        created_by=request.user
                    )
                    created_allocations.append(allocation)
        except Item.DoesNotExist:
            return Response({'error': 'One or more items not found.'}, status=status.HTTP_404_NOT_FOUND)
        except DjangoValidationError as e:
            return Response({'error': e.message}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # Notify super admins about bulk allocation
        for alloc in created_allocations:
            self._notify_allocation(alloc)

        serializer = self.get_serializer(created_allocations, many=True)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @staticmethod
    def _allocation_recipient(allocation):
        if allocation.student:
            return allocation.student.admission_number
        if allocation.faculty:
            return allocation.faculty.user.name
        if allocation.sales_user:
            return allocation.sales_user.name
        return 'Unknown'

    def _notify_allocation(self, allocation):
        """Send system notification to super_admins, recipient sales users, students, and parents when inventory is allocated."""
        try:
            from core.utils import notify_users_by_role, send_system_notification
            recipient_name = self._allocation_recipient(allocation)
            notify_users_by_role(
                roles=['super_admin'],
                title='Inventory Allocated',
                body=f"{allocation.quantity}x {allocation.item.name} allocated to {recipient_name} by {self.request.user.name}.",
                metadata={'allocation_id': str(allocation.id), 'item_id': str(allocation.item.id)},
            )
            if allocation.sales_user:
                send_system_notification(
                    user=allocation.sales_user,
                    title='Inventory Allocated',
                    body=f"You have been allocated {allocation.quantity}x {allocation.item.name}.",
                    data={
                        'allocation_id': str(allocation.id),
                        'item_id': str(allocation.item.id),
                        'type': 'inventory_allocated',
                        'route': f"/inventory/allocations/{allocation.id}"
                    },
                    notification_type='inventory',
                )
            if allocation.student:
                student_user = getattr(allocation.student, 'user', None)
                if student_user:
                    send_system_notification(
                        user=student_user,
                        title='Inventory Issued',
                        body=f"You have been issued {allocation.quantity}x {allocation.item.name}.",
                        data={
                            'allocation_id': str(allocation.id),
                            'item_id': str(allocation.item.id),
                            'type': 'inventory_allocated',
                            'route': f"/inventory/allocations/{allocation.id}"
                        },
                        notification_type='inventory',
                    )
                # Also notify student's parents
                try:
                    from students.models import ParentLink
                    student_display = student_user.name if student_user else allocation.student.admission_number
                    parents = ParentLink.objects.filter(student=allocation.student).select_related('parent')
                    for pl in parents:
                        if pl.parent and pl.parent.is_active:
                            send_system_notification(
                                user=pl.parent,
                                title='Student Inventory Issued',
                                body=f"{allocation.quantity}x {allocation.item.name} has been issued to {student_display}.",
                                data={
                                    'allocation_id': str(allocation.id),
                                    'item_id': str(allocation.item.id),
                                    'student_id': str(allocation.student.id),
                                    'type': 'inventory_allocated',
                                    'route': f"/inventory/allocations/{allocation.id}"
                                },
                                notification_type='inventory',
                            )
                except Exception:
                    pass
            if allocation.faculty and getattr(allocation.faculty, 'user', None):
                send_system_notification(
                    user=allocation.faculty.user,
                    title='Inventory Allocated',
                    body=f"You have been allocated {allocation.quantity}x {allocation.item.name}.",
                    data={
                        'allocation_id': str(allocation.id),
                        'item_id': str(allocation.item.id),
                        'type': 'inventory_allocated',
                        'route': f"/inventory/allocations/{allocation.id}"
                    },
                    notification_type='inventory',
                )
        except Exception:
            import logging
            logging.getLogger(__name__).error(f"Failed to send allocation notification for {allocation.id}", exc_info=True)


@api_view(['GET'])
def inventory_forecast_view(request):
    """
    Returns dynamically computed forecasting data for all active items.
    """
    data = get_inventory_forecast(user=request.user)
    return Response(data)
