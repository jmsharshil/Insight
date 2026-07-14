from datetime import timedelta
from django.utils import timezone
from django.db.models import Sum

from .models import Item, ItemAllocation

def get_inventory_forecast(user=None):
    """
    Analyzes all active inventory items to project future stock status.
    Returns a list of dicts with forecasting details.
    """
    items = Item.objects.filter(is_active=True).select_related('category')
    
    if user and user.role != 'super_admin' and getattr(user, 'branch_id', None):
        items = items.filter(category__branch_id=user.branch_id)
    
    thirty_days_ago = timezone.now() - timedelta(days=30)
    
    forecast_data = []
    
    for item in items:
        # 1. Calculate 30-day burn rate
        allocations_30d = ItemAllocation.objects.filter(
            item=item,
            status='issued',
            issued_at__gte=thirty_days_ago
        ).aggregate(total=Sum('quantity'))['total'] or 0
        
        daily_burn_rate = allocations_30d / 30.0
        
        # 2. Project demand for the next 30 days
        projected_30d_demand = int(daily_burn_rate * 30)
        
        # 3. Predict days until stockout
        if daily_burn_rate > 0:
            days_until_stockout = int(item.total_stock / daily_burn_rate)
        else:
            days_until_stockout = 9999  # practically infinite
            
        # 4. Status determination
        projected_stock = item.total_stock - projected_30d_demand
        if projected_stock <= 0:
            status = 'critical'
            message = f"Stockout expected in {days_until_stockout} days!"
        elif projected_stock <= item.reorder_level:
            status = 'warning'
            message = "Projected to hit reorder level within 30 days."
        elif item.total_stock <= item.reorder_level:
            status = 'warning'
            message = "Currently at or below reorder level."
        else:
            status = 'healthy'
            message = "Stock is healthy for the next 30 days."
            
        forecast_data.append({
            'item_id': item.id,
            'item_name': item.name,
            'category': item.category.name,
            'current_stock': item.total_stock,
            'reorder_level': item.reorder_level,
            'last_30d_usage': allocations_30d,
            'daily_burn_rate': round(daily_burn_rate, 2),
            'projected_30d_demand': projected_30d_demand,
            'days_until_stockout': days_until_stockout if days_until_stockout != 9999 else "999+",
            'status': status,
            'message': message,
        })
        
    return forecast_data
