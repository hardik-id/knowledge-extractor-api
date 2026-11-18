"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerSplitView

from apps.core.api import views as core_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("config.api_v1")),
    # Without API_DOCS_ENABLED these two paths fall through to the catch-all: 404.
    *(
        [
            path("api/schema", SpectacularAPIView.as_view(), name="schema"),
            path(
                "api/docs",
                SpectacularSwaggerSplitView.as_view(url_name="schema"),
                name="docs",
            ),
        ]
        if settings.API_DOCS_ENABLED
        else []
    ),
    # Keep last: unknown URLs under /api/ answer the JSON error contract.
    re_path(r"^api/(?P<rest>.*)$", core_views.api_not_found),
]

handler404 = "apps.core.api.views.handler404"
handler500 = "apps.core.api.views.handler500"
