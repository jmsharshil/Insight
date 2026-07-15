import logging
from django.contrib.auth import get_user_model
from inventory.utils import get_inventory_forecast
from chat.notifications import send_system_notification

logger = logging.getLogger(__name__)

def inventory_forecast_alert_task(*args, **kwargs):
    """
    Background task to check inventory forecasts daily and alert super admins 
    about items in 'warning' or 'critical' status.
    """
    try:
        # Pass user=None so it analyzes all active items across branches
        forecasts = get_inventory_forecast(user=None)
        
        # Filter items with warning or critical status
        alert_items = [f for f in forecasts if f['status'] in ['warning', 'critical']]
        
        if not alert_items:
            return
            
        User = get_user_model()
        super_admins = User.objects.filter(role='super_admin', is_active=True)
        
        for admin in super_admins:
            body = "The following items require your attention:\n"
            for item in alert_items:
                body += f"- {item['item_name']} ({item['category']}): {item['status'].upper()} - {item['message']}\n"
                
            send_system_notification(
                user_id=str(admin.id),
                title=f'Inventory Alerts: {len(alert_items)} Items Low',
                body=body,
                metadata={'module': 'inventory', 'alert_count': len(alert_items)}
            )
            
    except Exception as e:
        logger.error(f"Failed to run inventory_forecast_alert_task: {e}")
