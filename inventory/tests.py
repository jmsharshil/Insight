from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from inventory.utils import get_inventory_forecast


class InventoryForecastTests(SimpleTestCase):
    @patch('inventory.utils.ItemAllocation.objects.filter')
    @patch('inventory.utils.Item.objects.filter')
    def test_no_recent_usage_has_no_stockout_day_sentinel(
        self, mock_items_filter, mock_allocations_filter
    ):
        item = SimpleNamespace(
            id='item-id',
            name='Uniform Shirt',
            category=SimpleNamespace(name='Uniforms'),
            total_stock=10,
            reorder_level=2,
        )
        mock_items_filter.return_value.select_related.return_value = [item]
        mock_allocations_filter.return_value.aggregate.return_value = {'total': None}

        forecast = get_inventory_forecast()

        self.assertIsNone(forecast[0]['days_until_stockout'])
        self.assertEqual(forecast[0]['status'], 'healthy')
        self.assertIn('No recent usage', forecast[0]['message'])

    @patch('inventory.utils.ItemAllocation.objects.filter')
    @patch('inventory.utils.Item.objects.filter')
    def test_stockout_days_are_calculated_for_recent_usage(
        self, mock_items_filter, mock_allocations_filter
    ):
        item = SimpleNamespace(
            id='item-id',
            name='Uniform Shirt',
            category=SimpleNamespace(name='Uniforms'),
            total_stock=10,
            reorder_level=2,
        )
        mock_items_filter.return_value.select_related.return_value = [item]
        mock_allocations_filter.return_value.aggregate.return_value = {'total': 60}

        forecast = get_inventory_forecast()

        self.assertEqual(forecast[0]['days_until_stockout'], 5)
