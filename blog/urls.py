"""
URL configuration for blog project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
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

from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from django.views.decorators.csrf import csrf_exempt
from GraphQL.views import (
    CustomGraphQLView,
    blog_detail,
    blog_list,
    increment_blog_view,
    upload_blog_images,
)
from graphene_django.views import GraphQLView


urlpatterns = [
    path("blogs/", blog_list, name="blog_list"),
    path("blogs/<slug:slug>/", blog_detail, name="blog_detail"),
    path("blogs/<slug:slug>/increment-view/", increment_blog_view, name="increment_blog_view"),
    path("admin-dashboard/", include("admin_dashboard.urls")),
    path("admin/", admin.site.urls),
    #path("graphql/", csrf_exempt(CustomGraphQLView.as_view(graphiql=True))),
    path("graphql/", csrf_exempt(GraphQLView.as_view(graphiql=True))),
    path("api/upload-images/", upload_blog_images),
]
GraphQLView.graphiql_template = "graphene_graphiql_explorer/graphiql.html"
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
