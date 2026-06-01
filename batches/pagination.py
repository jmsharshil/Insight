"""
Custom pagination classes for API responses.
"""
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardPagination(PageNumberPagination):
    """Standard pagination with 50 items per page."""
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_response(self, queryset, serializer):
        """Helper to return standardized paginated response."""
        return Response({
            'success': True,
            'count': self.page.paginator.count,
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'page_size': self.page_size,
            'data': serializer.data,
        })


class LargePagination(PageNumberPagination):
    """Pagination for large datasets with 100 items per page."""
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 200
