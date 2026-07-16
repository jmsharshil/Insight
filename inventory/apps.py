from django.apps import AppConfig


class InventoryConfig(AppConfig):
    name = 'inventory'

    def ready(self):
        try:
            from scheduler.services import TaskScheduler
            from inventory.services import inventory_forecast_alert_task
            
            TaskScheduler.register('inventory_forecast_alert', inventory_forecast_alert_task)
            TaskScheduler.schedule(
                task_type='inventory_forecast_alert',
                delay_seconds=0,
                is_recurring=True,
                interval_seconds=86400  # daily
            )
        except Exception:
            pass
