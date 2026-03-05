import json
from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from graphene_file_upload.django import FileUploadGraphQLView
from graphql_jwt.exceptions import JSONWebTokenError, JSONWebTokenExpired
from graphql_jwt.settings import jwt_settings
from graphql_jwt.utils import jwt_decode
from .models import Blog, BlogImage

ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png"}
MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024

def blog_list(request):
    blogs = (
        Blog.objects.filter(is_active=True, is_deleted=False)
        .select_related("author")
        .prefetch_related("categories", "tags")
        .order_by("-created_at")
    )
    return render(request, "GraphQL/blog_list.html", {"blogs": blogs})

def blog_detail(request, slug):
    blog = get_object_or_404(
        Blog.objects.filter(is_active=True, is_deleted=False)
        .select_related("author")
        .prefetch_related("categories", "tags", "gallery"),
        slug=slug,
    )
    return render(request, "GraphQL/blog_detail.html", {"blog": blog})

@csrf_exempt
@require_POST
def increment_blog_view(request, slug):
    blog = get_object_or_404(Blog, slug=slug, is_active=True, is_deleted=False)
    Blog.objects.filter(pk=blog.pk).update(view_count=F("view_count") + 1)
    blog.refresh_from_db(fields=["view_count"])
    return JsonResponse(
        {
            "success": True,
            "blog_id": blog.id,
            "slug": blog.slug,
            "view_count": blog.view_count,
        }
    )

class CustomGraphQLView(FileUploadGraphQLView):
    TOKEN_ERROR_TEXTS = (
        "token has expired",
        "jwt authentication is required",
        "invalid jwt token",
    )
    NOT_FOUND_ERROR_TEXTS = ("not found",)

    def get_response(self, request, data, show_graphiql=False):
        result, status_code = super().get_response(request, data, show_graphiql)
        if not result:
            return result, status_code

        try:
            payload = json.loads(result)
        except (TypeError, json.JSONDecodeError):
            return result, status_code

        errors = payload.get("errors") if isinstance(payload, dict) else None
        if not errors:
            return result, status_code

        messages_list = []
        for error in errors:
            if isinstance(error, dict):
                messages_list.append(str(error.get("message", "")).lower())
            else:
                messages_list.append(str(error).lower())

        if any(
            token_text in message
            for message in messages_list
            for token_text in self.TOKEN_ERROR_TEXTS
        ):
            return result, 401

        if any(
            not_found_text in message
            for message in messages_list
            for not_found_text in self.NOT_FOUND_ERROR_TEXTS
        ):
            return result, 404

        return result, 400
def _get_user_from_jwt_request(request):
    auth_header = request.META.get("HTTP_AUTHORIZATION", "").strip()
    if not auth_header:
        return None, JsonResponse({"error": "JWT authentication is required"}, status=401)

    token_parts = auth_header.split()
    token = auth_header
    if len(token_parts) == 2 and token_parts[0].lower() in {"jwt", "bearer"}:
        token = token_parts[1]

    try:
        payload = jwt_decode(token)
        username = jwt_settings.JWT_PAYLOAD_GET_USERNAME_HANDLER(payload)
        user_model = get_user_model()
        lookup_field = user_model.USERNAME_FIELD
        user = user_model.objects.filter(**{lookup_field: username}).first()
        if not user:
            return None, JsonResponse({"error": "Invalid JWT token"}, status=401)
        return user, None
    except JSONWebTokenExpired:
        return None, JsonResponse({"error": "Token has expired"}, status=401)
    except JSONWebTokenError:
        return None, JsonResponse({"error": "Invalid JWT token"}, status=401)
    except Exception:
        return None, JsonResponse({"error": "Invalid JWT token"}, status=401)
def _validate_image_file(image_file, field_name):
    if not image_file:
        return None
    file_name = (image_file.name or "").lower()
    if "." not in file_name:
        return f"{field_name}: Only JPG and PNG files are allowed."

    file_extension = file_name.rsplit(".", 1)[1]
    if file_extension not in ALLOWED_IMAGE_EXTENSIONS:
        return f"{field_name}: Only JPG and PNG files are allowed."

    if image_file.size > MAX_IMAGE_SIZE_BYTES:
        return f"{field_name}: File size must be 5 MB or less."

    return None
@csrf_exempt
@require_POST
def upload_blog_images(request):
    user, error_response = _get_user_from_jwt_request(request)
    if error_response:
        return error_response
    if not user.is_superuser:
        return JsonResponse({"error": "Only superuser can upload images"}, status=403)

    featured_image = request.FILES.get("featured_image")
    gallery_images = request.FILES.getlist("gallery_images")

    if not featured_image and not gallery_images:
        return JsonResponse(
            {"error": "Provide featured_image and/or gallery_images"},
            status=400,
        )

    featured_image_error = _validate_image_file(featured_image, "featured_image")
    if featured_image_error:
        return JsonResponse({"error": featured_image_error}, status=400)

    for index, gallery_image in enumerate(gallery_images, start=1):
        gallery_image_error = _validate_image_file(gallery_image, f"gallery_images[{index}]")
        if gallery_image_error:
            return JsonResponse({"error": gallery_image_error}, status=400)

    response_data = {
        "uploaded_by": user.username,
        "featured_image_path": None,
        "featured_image_url": None,
        "gallery": [],
    }

    if featured_image:
        featured_path = default_storage.save(f"featured/{featured_image.name}", featured_image)
        response_data["featured_image_path"] = featured_path
        featured_url = default_storage.url(featured_path)
        response_data["featured_image_url"] = request.build_absolute_uri(featured_url)

    for gallery_image in gallery_images:
        gallery_obj = BlogImage.objects.create(image=gallery_image)
        response_data["gallery"].append(
            {
                "id": str(gallery_obj.id),
                "path": gallery_obj.image.name,
                "url": request.build_absolute_uri(gallery_obj.image.url),
            }
        )

    return JsonResponse(response_data, status=201)
