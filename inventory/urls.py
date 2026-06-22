from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ItemCategoryViewSet, ItemViewSet,
    StockTransactionViewSet, ItemAllocationViewSet,
    inventory_forecast_view
)

router = DefaultRouter()
router.register(r'categories', ItemCategoryViewSet, basename='inventory-categories')
router.register(r'items', ItemViewSet, basename='inventory-items')
router.register(r'transactions', StockTransactionViewSet, basename='inventory-transactions')
router.register(r'allocations', ItemAllocationViewSet, basename='inventory-allocations')

urlpatterns = [
    path('', include(router.urls)),
    path('forecast/', inventory_forecast_view, name='inventory-forecast'),
]
