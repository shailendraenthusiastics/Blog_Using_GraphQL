from django.contrib import admin
from .models import BlogCategory, BlogTag, Blog 
admin.site.register(BlogCategory)
admin.site.register(BlogTag)
admin.site.register(Blog)

