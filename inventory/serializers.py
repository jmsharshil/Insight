from rest_framework import serializers
from .models import ItemCategory, Item, StockTransaction, ItemAllocation

class ItemCategorySerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    
    class Meta:
        model = ItemCategory
        fields = ['id', 'branch', 'branch_name', 'name', 'description', 'is_active', 'created_at', 'updated_at']
        extra_kwargs = {
            'branch': {'required': False}
        }


class ItemSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    
    class Meta:
        model = Item
        fields = [
            'id', 'category', 'category_name', 'name', 'description', 'size',
            'total_stock', 'reorder_level', 'unit_price', 'is_active',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['total_stock'] # Stock should be updated via transactions!


class StockTransactionSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source='item.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.name', read_only=True)
    transaction_type_display = serializers.CharField(source='get_transaction_type_display', read_only=True)
    
    class Meta:
        model = StockTransaction
        fields = [
            'id', 'item', 'item_name', 'transaction_type', 'transaction_type_display',
            'quantity', 'unit_price', 'reference', 'invoice_document', 'notes',
            'created_by', 'created_by_name', 'transaction_date'
        ]
        read_only_fields = ['created_by', 'transaction_date']


class ItemAllocationSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source='item.name', read_only=True)
    student_name = serializers.CharField(source='student.user.name', read_only=True)
    faculty_name = serializers.CharField(source='faculty.user.name', read_only=True)
    issued_by_name = serializers.CharField(source='issued_by.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = ItemAllocation
        fields = [
            'id', 'item', 'item_name', 'student', 'student_name', 'faculty', 'faculty_name',
            'quantity', 'status', 'status_display', 'issued_at', 'issued_by', 'issued_by_name',
            'returned_at', 'return_notes', 'notes'
        ]
        read_only_fields = ['issued_by', 'issued_at', 'returned_at']
