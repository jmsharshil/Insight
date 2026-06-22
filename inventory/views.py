from rest_framework import viewsets, filters, status
from rest_framework.decorators import api_view, action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone

from .models import ItemCategory, Item, StockTransaction, ItemAllocation
from .serializers import (
    ItemCategorySerializer, ItemSerializer,
    StockTransactionSerializer, ItemAllocationSerializer
)
from .utils import get_inventory_forecast

class ItemCategoryViewSet(viewsets.ModelViewSet):
    queryset = ItemCategory.objects.all()
    serializer_class = ItemCategorySerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['branch', 'is_active']
    search_fields = ['name', 'description']


class ItemViewSet(viewsets.ModelViewSet):
    queryset = Item.objects.select_related('category').all()
    serializer_class = ItemSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['category', 'category__branch', 'is_active']
    search_fields = ['name', 'description']


class StockTransactionViewSet(viewsets.ModelViewSet):
    queryset = StockTransaction.objects.select_related('item', 'created_by').all()
    serializer_class = StockTransactionSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['item', 'transaction_type', 'item__category__branch']
    ordering_fields = ['transaction_date']

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class ItemAllocationViewSet(viewsets.ModelViewSet):
    queryset = ItemAllocation.objects.select_related('item', 'student', 'faculty', 'issued_by').all()
    serializer_class = ItemAllocationSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['item', 'status', 'student', 'faculty', 'item__category__branch']
    search_fields = ['student__admission_number', 'student__first_name', 'faculty__user__name']

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

                    item = Item.objects.get(id=item_id)

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
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(created_allocations, many=True)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
def inventory_forecast_view(request):
    """
    Returns dynamically computed forecasting data for all active items.
    """
    data = get_inventory_forecast()
    return Response(data)
