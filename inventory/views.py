from rest_framework import viewsets, filters, status
from rest_framework.decorators import api_view, action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone

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

def resolve_profile_id(model_class, id_val):
    if not id_val:
        return None
    if model_class.objects.filter(id=id_val).exists():
        return id_val
    if User.objects.filter(id=id_val).exists():
        profile = model_class.objects.filter(user_id=id_val).first()
        if profile:
            return str(profile.id)
    return id_val


class ItemCategoryViewSet(viewsets.ModelViewSet):
    queryset = ItemCategory.objects.all()
    serializer_class = ItemCategorySerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['branch', 'is_active']
    search_fields = ['name', 'description']

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()
        if user.role != 'super_admin' and getattr(user, 'branch_id', None):
            qs = qs.filter(branch_id=user.branch_id)
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
            branch_id = getattr(user, 'branch_id', None)
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
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['category', 'category__branch', 'is_active']
    search_fields = ['name', 'description']

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()
        if user.role != 'super_admin' and getattr(user, 'branch_id', None):
            qs = qs.filter(category__branch_id=user.branch_id)
        return qs


class StockTransactionViewSet(viewsets.ModelViewSet):
    queryset = StockTransaction.objects.select_related('item', 'created_by').all()
    serializer_class = StockTransactionSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['item', 'transaction_type', 'item__category__branch']
    ordering_fields = ['transaction_date']

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()
        if user.role != 'super_admin' and getattr(user, 'branch_id', None):
            qs = qs.filter(item__category__branch_id=user.branch_id)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class ItemAllocationViewSet(viewsets.ModelViewSet):
    queryset = ItemAllocation.objects.select_related('item', 'student', 'faculty', 'issued_by').all()
    serializer_class = ItemAllocationSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['item', 'status', 'student', 'faculty', 'item__category__branch']
    search_fields = ['student__admission_number', 'student__first_name', 'faculty__user__name']

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()
        if user.role != 'super_admin' and getattr(user, 'branch_id', None):
            qs = qs.filter(item__category__branch_id=user.branch_id)
        return qs

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
                reference=f"Allocated to {allocation.student.admission_number if allocation.student else allocation.faculty.user.name if allocation.faculty else 'Unknown'}",
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
        
        student_id = resolve_profile_id(StudentProfile, student_id)
        faculty_id = resolve_profile_id(FacultyProfile, faculty_id)

        allocations_data = request.data.get('allocations', [])

        if not student_id and not faculty_id:
            return Response({'error': 'Must provide either student or faculty ID.'}, status=status.HTTP_400_BAD_REQUEST)
        
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
                        reference=f"Bulk allocation to {allocation.student.admission_number if allocation.student else allocation.faculty.user.name if allocation.faculty else 'Unknown'}",
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

    def _notify_allocation(self, allocation):
        """Send system notification to super_admins when inventory is allocated."""
        try:
            from core.utils import notify_users_by_role
            recipient_name = (
                allocation.student.admission_number if allocation.student
                else allocation.faculty.user.name if allocation.faculty
                else 'Unknown'
            )
            notify_users_by_role(
                roles=['super_admin'],
                title='Inventory Allocated',
                body=f"{allocation.quantity}x {allocation.item.name} allocated to {recipient_name} by {self.request.user.name}.",
                metadata={'allocation_id': str(allocation.id), 'item_id': str(allocation.item.id)},
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
