from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SupportQueryViewSet

router = DefaultRouter()
router.register(r'queries', SupportQueryViewSet, basename='supportquery')

urlpatterns = [
    path('', include(router.urls)),
]
