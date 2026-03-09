from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from GraphQL.models import Blog, BlogCategory, BlogImage, BlogTag


DASHBOARD_LOGIN_URL = "/admin-dashboard/login/"
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png"}
MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024

def _deprecated_graphql_action_response(request, redirect_name, graphql_action):
    message = f"This REST endpoint is deprecated. Use GraphQL action '{graphql_action}'."
    accepts_json = "application/json" in (request.headers.get("Accept") or "")
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if accepts_json or is_ajax:
        return JsonResponse({"success": False, "message": message}, status=410)

    messages.warning(request, message)
    return redirect(redirect_name)


def _is_superuser(user):
    return bool(user and user.is_authenticated and user.is_superuser)


def dashboard_login(request):
    next_url = request.GET.get("next") or request.POST.get("next") or "/admin-dashboard/dashboard/"
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = "/admin-dashboard/dashboard/"
    if next_url in {"/admin-dashboard/", "/admin-dashboard/login/"}:
        next_url = "/admin-dashboard/dashboard/"
    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""

        if not username or not password:
            messages.error(request, "Username and password are required.")
            return render(request, "admin_dashboard/login.html", {"next": next_url})

        user = authenticate(request, username=username, password=password)
        if user and user.is_superuser:
            login(request, user)
            return redirect(next_url)

        if user and not user.is_superuser:
            messages.error(request, "Only superuser can access the dashboard.")
        else:
            messages.error(request, "Invalid username or password.")

    return render(request, "admin_dashboard/login.html", {"next": next_url})


def dashboard_logout(request):
    logout(request)
    return redirect("admin_dashboard:login")


def _validate_image_upload(image_file):
    if not image_file:
        return "Image file is required."

    file_name = (image_file.name or "").lower()
    if "." not in file_name:
        return "Only JPG and PNG files are allowed."

    extension = file_name.rsplit(".", 1)[1]
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        return "Only JPG and PNG files are allowed."

    if image_file.size > MAX_IMAGE_SIZE_BYTES:
        return "File size must be 5 MB or less."

    return None


@csrf_exempt
@require_POST
@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def ckeditor_image_upload(request):
    upload = request.FILES.get("upload")
    validation_error = _validate_image_upload(upload)
    callback = request.GET.get("CKEditorFuncNum")

    if validation_error:
        if callback:
            response = (
                "<script>window.parent.CKEDITOR.tools.callFunction("
                f"{callback}, '', '{validation_error}');</script>"
            )
            return HttpResponse(response)
        return JsonResponse({"uploaded": 0, "error": {"message": validation_error}}, status=400)

    image = BlogImage.objects.create(image=upload)
    image_url = request.build_absolute_uri(image.image.url)

    if callback:
        response = (
            "<script>window.parent.CKEDITOR.tools.callFunction("
            f"{callback}, '{image_url}', 'Image uploaded successfully.');</script>"
        )
        return HttpResponse(response)

    return JsonResponse(
        {
            "uploaded": 1,
            "fileName": upload.name,
            "url": image_url,
            "urls": {"default": image_url},
        }
    )


@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def dashboard_home(request):
    return render(
        request,
        "admin_dashboard/home.html",
        {
            "active_menu": "home",
        },
    )


@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def dashboard_blogs(request):
    return render(
        request,
        "admin_dashboard/index.html",
        {
            "active_menu": "blogs",
        },
    )


@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def dashboard_blog_detail(request, blog_id):
    blog = get_object_or_404(Blog.objects.only("id"), pk=blog_id, is_deleted=False)
    return render(
        request,
        "admin_dashboard/blog_detail.html",
        {
            "blog": blog,
            "active_menu": "blogs",
        },
    )


@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def dashboard_blog_featured_image(request, blog_id):
    blog = get_object_or_404(Blog.objects.only("featured_image"), pk=blog_id, is_deleted=False)
    if blog.featured_image:
        return redirect(blog.featured_image.url)
    
@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def dashboard_blog_add(request):
    if request.method == "POST":
        return _deprecated_graphql_action_response(
            request,
            "admin_dashboard:dashboard_blogs",
            "createBlog",
        )

    return render(
        request,
        "admin_dashboard/blog_add.html",
        {
            "active_menu": "blogs",
        },
    )


@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def dashboard_categories(request):
    return render(
        request,
        "admin_dashboard/categories.html",
        {
            "active_menu": "categories",
        },
    )

@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def dashboard_category_detail(request, category_id):
    category = get_object_or_404(BlogCategory.objects.only("id"), pk=category_id)
    return render(
        request,
        "admin_dashboard/category_detail.html",
        {
            "category": category,
            "active_menu": "categories",
        },
    )


@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def dashboard_category_add(request):
    if request.method == "POST":
        return _deprecated_graphql_action_response(
            request,
            "admin_dashboard:dashboard_categories",
            "createCategory",
        )

    return render(
        request,
        "admin_dashboard/category_add.html",
        {
            "active_menu": "categories",
        },
    )


@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def dashboard_category_edit(request, category_id):
    category = get_object_or_404(BlogCategory.objects.only("id"), pk=category_id)

    if request.method == "POST":
        return _deprecated_graphql_action_response(
            request,
            "admin_dashboard:dashboard_categories",
            "updateCategory",
        )

    return render(
        request,
        "admin_dashboard/category_add.html",
        {"active_menu": "categories", "category": category, "is_edit": True},
    )


@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def dashboard_category_delete(request, category_id):
    if request.method == "POST":
        return _deprecated_graphql_action_response(
            request,
            "admin_dashboard:dashboard_categories",
            "deleteCategory",
        )

    return redirect("admin_dashboard:dashboard_categories")


@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def dashboard_tags(request):
    return render(
        request,
        "admin_dashboard/tags.html",
        {
            "active_menu": "tags",
        },
    )


@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def dashboard_tag_detail(request, tag_id):
    tag = get_object_or_404(BlogTag.objects.only("id"), pk=tag_id)
    return render(
        request,
        "admin_dashboard/tag_detail.html",
        {
            "tag": tag,
            "active_menu": "tags",
        },
    )

@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def dashboard_tag_add(request):
    if request.method == "POST":
        return _deprecated_graphql_action_response(
            request,
            "admin_dashboard:dashboard_tags",
            "createTag",
        )

    return render(
        request,
        "admin_dashboard/tag_add.html",
        {
            "active_menu": "tags",
        },
    )


@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def dashboard_tag_edit(request, tag_id):
    tag = get_object_or_404(BlogTag.objects.only("id"), pk=tag_id)

    if request.method == "POST":
        return _deprecated_graphql_action_response(
            request,
            "admin_dashboard:dashboard_tags",
            "updateTag",
        )

    return render(
        request,
        "admin_dashboard/tag_add.html",
        {"active_menu": "tags", "tag": tag, "is_edit": True},
    )

@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def dashboard_tag_delete(request, tag_id):
    if request.method == "POST":
        return _deprecated_graphql_action_response(
            request,
            "admin_dashboard:dashboard_tags",
            "deleteTag",
        )

    return redirect("admin_dashboard:dashboard_tags")


@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def blog_edit(request, pk):
    blog = get_object_or_404(Blog.objects.only("id"), pk=pk, is_deleted=False)

    if request.method == "POST":
        return _deprecated_graphql_action_response(
            request,
            "admin_dashboard:dashboard_blogs",
            "updateBlog",
        )

    return render(
        request,
        "admin_dashboard/blog_add.html",
        {
            "blog": blog,
            "is_edit": True,
            "active_menu": "blogs",
        },
    )


@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def blog_delete(request, pk):
    if request.method == "POST":
        return _deprecated_graphql_action_response(
            request,
            "admin_dashboard:dashboard_blogs",
            "deleteBlog",
        )

    return redirect("admin_dashboard:dashboard_blogs")
