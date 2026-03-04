from django.urls import path

from .views import (
    blog_delete,
    blog_edit,
    ckeditor_image_upload,
    dashboard_blog_add,
    dashboard_blog_detail,
    dashboard_blogs,
    dashboard_categories,
    dashboard_category_add,
    dashboard_category_delete,
    dashboard_category_detail,
    dashboard_category_edit,
    dashboard_home,
    dashboard_login,
    dashboard_logout,
    dashboard_tag_delete,
    dashboard_tag_edit,
    dashboard_tag_add,
    dashboard_tag_detail,
    dashboard_tags,
)

app_name = "admin_dashboard"

urlpatterns = [
    path("login/", dashboard_login, name="login"),
    path("logout/", dashboard_logout, name="logout"),
    path("ckeditor/upload/", ckeditor_image_upload, name="ckeditor_upload"),
    path("", dashboard_login, name="index"),
    path("blogs/add/", dashboard_blog_add, name="blog_add"),
    path("blogs/<int:pk>/edit/", blog_edit, name="blog_edit"),
    path("blogs/<int:pk>/delete/", blog_delete, name="blog_delete"),
    path("dashboard/", dashboard_home, name="dashboard_home"),
    path("dashboard/blogs/", dashboard_blogs, name="dashboard_blogs"),
    path("dashboard/blogs/add/", dashboard_blog_add, name="dashboard_blog_add"),
    path("dashboard/blogs/<int:blog_id>/", dashboard_blog_detail, name="dashboard_blog_detail"),
    path("dashboard/categories/", dashboard_categories, name="dashboard_categories"),
    path("dashboard/categories/add/", dashboard_category_add, name="dashboard_category_add"),
    path("dashboard/categories/<int:category_id>/edit/", dashboard_category_edit, name="dashboard_category_edit"),
    path("dashboard/categories/<int:category_id>/delete/", dashboard_category_delete, name="dashboard_category_delete"),
    path("dashboard/categories/<int:category_id>/", dashboard_category_detail, name="dashboard_category_detail"),
    path("dashboard/tags/", dashboard_tags, name="dashboard_tags"),
    path("dashboard/tags/add/", dashboard_tag_add, name="dashboard_tag_add"),
    path("dashboard/tags/<int:tag_id>/edit/", dashboard_tag_edit, name="dashboard_tag_edit"),
    path("dashboard/tags/<int:tag_id>/delete/", dashboard_tag_delete, name="dashboard_tag_delete"),
    path("dashboard/tags/<int:tag_id>/", dashboard_tag_detail, name="dashboard_tag_detail"),
]
