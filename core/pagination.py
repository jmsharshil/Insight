"""
core/pagination.py — Reusable pagination for APIView-based list endpoints.

Usage:
    from core.pagination import paginate_queryset

    class MyListView(APIView):
        def get(self, request):
            qs = MyModel.objects.all()
            return paginate_queryset(qs, request, MySerializer)
"""

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework import status


class StandardPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 100
    page_query_param = 'page'


def paginate_queryset(queryset, request, serializer_class, serializer_context=None):
    """
    Paginate a queryset and return a Response with prev/next/count.

    Args:
        queryset: Django QuerySet to paginate
        request: DRF Request object
        serializer_class: Serializer to use for the data
        serializer_context: Optional dict for serializer context (e.g. {'request': request})

    Returns:
        Response with structure:
        {
            "success": true,
            "count": 150,
            "next": "http://host/api/items/?page=3",
            "previous": "http://host/api/items/?page=1",
            "page_size": 20,
            "data": [ ... ]
        }
    """
    paginator = StandardPagination()
    page = paginator.paginate_queryset(queryset, request)

    if serializer_context is None:
        serializer_context = {'request': request}

    if page is not None:
        serializer = serializer_class(page, many=True, context=serializer_context)
        return Response({
            'success': True,
            'count': paginator.page.paginator.count,
            'next': paginator.get_next_link(),
            'previous': paginator.get_previous_link(),
            'page_size': paginator.get_page_size(request),
            'data': serializer.data,
        }, status=status.HTTP_200_OK)

    # Fallback: if pagination somehow fails, return unpaginated
    serializer = serializer_class(queryset, many=True, context=serializer_context)
    return Response({
        'success': True,
        'count': queryset.count(),
        'next': None,
        'previous': None,
        'page_size': len(serializer.data),
        'data': serializer.data,
    }, status=status.HTTP_200_OK)
