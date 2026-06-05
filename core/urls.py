from django.urls import path
from .views import PublicDropdownsView, AuthenticatedDropdownsView

urlpatterns = [
    path('dropdowns/public/', PublicDropdownsView.as_view(), name='public-dropdowns'),
    path('dropdowns/auth/', AuthenticatedDropdownsView.as_view(), name='auth-dropdowns'),
]
