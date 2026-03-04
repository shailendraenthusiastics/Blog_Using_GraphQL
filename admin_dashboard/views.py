import re

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.utils.text import slugify  # added
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from GraphQL.models import Blog, BlogCategory, BlogImage, BlogTag


DOUBLE_SPACE_PATTERN = re.compile(r"(?<=\S) {2,}(?=\S)")
DASHBOARD_LOGIN_URL = "/admin-dashboard/login/"
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png"}
MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024


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


def _clean_text(value, label, max_length=None, check_leading_trailing=True):
    raw_value = value or ""
    if check_leading_trailing and raw_value != raw_value.strip():
        raise ValueError(f"{label} cannot have leading or trailing spaces.")

    normalized = raw_value.strip()
    if not normalized:
        raise ValueError(f"{label} is required.")
    if DOUBLE_SPACE_PATTERN.search(normalized):
        raise ValueError(f"{label} cannot contain multiple spaces between words.")
    if max_length and len(normalized) > max_length:
        raise ValueError(f"{label} must be {max_length} characters or fewer.")
    return normalized


def _to_title_case(value):
    return " ".join(word.capitalize() for word in value.split())


def _is_title_case(value):
    return value == value.title()


def _normalize_rich_text_for_validation(value):
    raw_value = value or ""
    without_tags = re.sub(r"<[^>]+>", "", raw_value)
    normalized_spaces = without_tags.replace("&nbsp;", " ").replace("\xa0", " ")
    return normalized_spaces


def _build_unique_slug(title):
    base_slug = slugify(title)
    if not base_slug:
        raise ValueError("Slug could not be generated from title.")

    slug = base_slug
    counter = 1
    while Blog.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{counter}"
        counter += 1
    return slug


def _build_unique_term_slug(model_class, source_value, current_id=None):
    base_slug = slugify(source_value)
    if not base_slug:
        raise ValueError("Slug could not be generated.")

    slug = base_slug
    counter = 1
    query = model_class.objects.all()
    if current_id:
        query = query.exclude(pk=current_id)

    while query.filter(slug=slug).exists():
        slug = f"{base_slug}-{counter}"
        counter += 1
    return slug


def _build_unique_username_from_name(author_name):
    base_username = slugify(author_name).replace("-", "_")
    if not base_username:
        raise ValueError("Author name is invalid.")

    username = base_username
    counter = 1
    while User.objects.filter(username__iexact=username).exists():
        username = f"{base_username}_{counter}"
        counter += 1
    return username


def _get_or_create_author(author_name):
    normalized_name = _clean_text(author_name, "Author name", 150)
    parts = normalized_name.split()
    first_name = parts[0]
    last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

    existing_user = User.objects.filter(first_name__iexact=first_name, last_name__iexact=last_name).first()
    if existing_user:
        return existing_user

    username = _build_unique_username_from_name(normalized_name)
    return User.objects.create_user(
        username=username,
        first_name=first_name,
        last_name=last_name,
        is_active=True,
    )


@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def dashboard_home(request):
    context = {
        "total_blogs": Blog.objects.count(),
        "total_tags": BlogTag.objects.count(),
        "total_categories": BlogCategory.objects.count(),
        "active_blogs": Blog.objects.filter(is_active=True).count(),
        "inactive_blogs": Blog.objects.filter(is_active=False).count(),
        "active_tags": BlogTag.objects.filter(is_active=True).count(),
        "inactive_tags": BlogTag.objects.filter(is_active=False).count(),
        "active_categories": BlogCategory.objects.filter(is_active=True).count(),
        "inactive_categories": BlogCategory.objects.filter(is_active=False).count(),
        "active_menu": "home",
    }
    return render(request, "admin_dashboard/home.html", context)


@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def dashboard_blogs(request):
    status = (request.GET.get("status") or "all").lower()
    blogs = Blog.objects.select_related("author").prefetch_related("categories", "tags")
    if status == "active":
        blogs = blogs.filter(is_active=True)
    elif status == "inactive":
        blogs = blogs.filter(is_active=False)
    else:
        status = "all"
    blogs = blogs.order_by("-created_at")
    return render(
        request,
        "admin_dashboard/index.html",
        {
            "blogs": blogs,
            "active_menu": "blogs",
            "status_filter": status,
        },
    )


@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def dashboard_blog_detail(request, blog_id):
    blog = get_object_or_404(
        Blog.objects.select_related("author").prefetch_related("categories", "tags", "gallery"),
        pk=blog_id,
    )
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
def dashboard_blog_add(request):
    categories = BlogCategory.objects.filter(is_active=True).order_by("name")
    tags = BlogTag.objects.filter(is_active=True).order_by("name")
    selected_category_ids = []
    selected_tag_ids = []
    form_values = {
        "author_name": "",
        "title": "",
        "short_description": "",
        "description": "",
        "is_active": True,
    }
    field_errors = {
        "author_name": [],
        "title": [],
        "short_description": [],
        "description": [],
        "featured_image": [],
        "category_ids": [],
        "tag_ids": [],
    }
    non_field_errors = []

    if request.method == "POST":
        selected_category_ids = request.POST.getlist("category_ids")
        selected_tag_ids = request.POST.getlist("tag_ids")
        form_values = {
            "author_name": request.POST.get("author_name") or "",
            "title": request.POST.get("title") or "",
            "short_description": request.POST.get("short_description") or "",
            "description": request.POST.get("description") or "",
            "is_active": request.POST.get("is_active") == "on",
        }

        def add_field_error(field_name, error_message):
            if field_name in field_errors:
                field_errors[field_name].append(error_message)
            else:
                non_field_errors.append(error_message)

        title = ""
        short_description = ""
        description = ""
        selected_author = None

        try:
            title = _clean_text(form_values["title"], "Title", 150)
            if not _is_title_case(title):
                add_field_error("title", "Title must be in Title Case.")
        except ValueError as exc:
            add_field_error("title", str(exc))

        try:
            short_description = _to_title_case(
                _clean_text(form_values["short_description"], "Short description", 255)
            )
        except ValueError as exc:
            add_field_error("short_description", str(exc))

        try:
            normalized_description = _normalize_rich_text_for_validation(form_values["description"])
            _clean_text(normalized_description, "Description", check_leading_trailing=False)
            description = (form_values["description"] or "").strip()
        except ValueError as exc:
            add_field_error("description", str(exc))

        try:
            selected_author = _get_or_create_author(form_values["author_name"])
        except ValueError as exc:
            add_field_error("author_name", str(exc))

        featured_image = request.FILES.get("featured_image")
        delete_featured_image = request.POST.get("delete_featured_image") == "1"
        gallery_images = request.FILES.getlist("gallery_images") or request.FILES.getlist("gallery_images[]")
        remove_gallery_image_ids = request.POST.getlist("remove_gallery_image_ids")
        if not featured_image:
            add_field_error("featured_image", "Featured image is required.")

        if not selected_category_ids:
            add_field_error("category_ids", "At least one category is required.")
        if not selected_tag_ids:
            add_field_error("tag_ids", "At least one tag is required.")
        if len(selected_category_ids) != len(set(selected_category_ids)):
            add_field_error("category_ids", "Duplicate categories are not allowed.")
        if len(selected_tag_ids) != len(set(selected_tag_ids)):
            add_field_error("tag_ids", "Duplicate tags are not allowed.")

        selected_categories = list(BlogCategory.objects.filter(id__in=selected_category_ids, is_active=True))
        selected_tags = list(BlogTag.objects.filter(id__in=selected_tag_ids, is_active=True))
        if selected_category_ids and len(selected_categories) != len(selected_category_ids):
            add_field_error("category_ids", "One or more categories are invalid.")
        if selected_tag_ids and len(selected_tags) != len(selected_tag_ids):
            add_field_error("tag_ids", "One or more tags are invalid.")

        has_errors = any(field_errors[field_name] for field_name in field_errors) or bool(non_field_errors)

        if not has_errors:
            try:
                slug = _build_unique_slug(title)
            except ValueError as exc:
                add_field_error("title", str(exc))
                slug = ""

        has_errors = any(field_errors[field_name] for field_name in field_errors) or bool(non_field_errors)

        if not has_errors:
            blog = Blog.objects.create(
                title=title,
                slug=slug,
                short_description=short_description,
                description=description,
                featured_image=featured_image,
                author=selected_author,
                is_active=form_values["is_active"],
            )
            blog.categories.set(selected_categories)
            blog.tags.set(selected_tags)
            if gallery_images:
                created_gallery_images = [BlogImage.objects.create(image=image_file) for image_file in gallery_images]
                blog.gallery.set(created_gallery_images)
            messages.success(request, "Blog created successfully.")
            return redirect("admin_dashboard:dashboard_blogs")

    return render(
        request,
        "admin_dashboard/blog_add.html",
        {
            "categories": categories,
            "tags": tags,
            "form_values": form_values,
            "field_errors": field_errors,
            "non_field_errors": non_field_errors,
            "selected_category_ids": selected_category_ids,
            "selected_tag_ids": selected_tag_ids,
            "active_menu": "blogs",
        },
    )


@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def dashboard_categories(request):
    status = (request.GET.get("status") or "all").lower()
    categories = BlogCategory.objects.all()
    page_number = request.GET.get("page")
    if status == "active":
        categories = categories.filter(is_active=True)
    elif status == "inactive":
        categories = categories.filter(is_active=False)
    else:
        status = "all"
    categories = categories.order_by("-created_at")
    paginator = Paginator(categories, 10)
    categories = paginator.get_page(page_number)
    serial_start = (categories.number - 1) * paginator.per_page
    return render(
        request,
        "admin_dashboard/categories.html",
        {
            "categories": categories,
            "serial_start": serial_start,
            "active_menu": "categories",
            "status_filter": status,
        },
    )


@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def dashboard_category_detail(request, category_id):
    category = get_object_or_404(BlogCategory, pk=category_id)
    related_blogs = Blog.objects.filter(categories=category).select_related("author").order_by("-created_at")
    return render(
        request,
        "admin_dashboard/category_detail.html",
        {
            "category": category,
            "related_blogs": related_blogs,
            "active_menu": "categories",
        },
    )


@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def dashboard_category_add(request):
    if request.method == "POST":
        try:
            name = _to_title_case(_clean_text(request.POST.get("name"), "Category name", 100))
            raw_slug = (request.POST.get("slug") or "").strip()
            if BlogCategory.objects.filter(name__iexact=name).exists():
                raise ValueError("Category already exists.")
            slug_source = raw_slug or name
            slug = _build_unique_term_slug(BlogCategory, slug_source)
            BlogCategory.objects.create(name=name, slug=slug, is_active=request.POST.get("is_active") == "on")
            messages.success(request, "Category created successfully.")
            return redirect("admin_dashboard:dashboard_categories")  # changed
        except ValueError as exc:
            messages.error(request, str(exc))

    return render(request, "admin_dashboard/category_add.html", {"active_menu": "categories"})


@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def dashboard_category_edit(request, category_id):
    category = get_object_or_404(BlogCategory, pk=category_id)

    if request.method == "POST":
        try:
            name = _to_title_case(_clean_text(request.POST.get("name"), "Category name", 100))
            raw_slug = (request.POST.get("slug") or "").strip()
            if BlogCategory.objects.filter(name__iexact=name).exclude(pk=category.pk).exists():
                raise ValueError("Category already exists.")
            slug_source = raw_slug or name
            slug = _build_unique_term_slug(BlogCategory, slug_source, current_id=category.pk)
            category.name = name
            category.slug = slug
            category.is_active = request.POST.get("is_active") == "on"
            category.save(update_fields=["name", "slug", "is_active", "updated_at"])
            messages.success(request, "Category updated successfully.")
            return redirect("admin_dashboard:dashboard_categories")
        except ValueError as exc:
            messages.error(request, str(exc))

    return render(
        request,
        "admin_dashboard/category_add.html",
        {"active_menu": "categories", "category": category, "is_edit": True},
    )


@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def dashboard_category_delete(request, category_id):
    category = get_object_or_404(BlogCategory, pk=category_id)
    if request.method == "POST":
        category.is_active = False
        category.save(update_fields=["is_active", "updated_at"])
        messages.success(request, "Category marked as inactive successfully.")
    return redirect("admin_dashboard:dashboard_categories")


@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def dashboard_tags(request):
    status = (request.GET.get("status") or "all").lower()
    tags = BlogTag.objects.all()
    page_number = request.GET.get("page")
    if status == "active":
        tags = tags.filter(is_active=True)
    elif status == "inactive":
        tags = tags.filter(is_active=False)
    else:
        status = "all"
    tags = tags.order_by("-created_at")
    paginator = Paginator(tags, 10)
    tags = paginator.get_page(page_number)
    serial_start = (tags.number - 1) * paginator.per_page
    return render(
        request,
        "admin_dashboard/tags.html",
        {
            "tags": tags,
            "serial_start": serial_start,
            "active_menu": "tags",
            "status_filter": status,
        },
    )


@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def dashboard_tag_detail(request, tag_id):
    tag = get_object_or_404(BlogTag, pk=tag_id)
    related_blogs = Blog.objects.filter(tags=tag).select_related("author").order_by("-created_at")
    return render(
        request,
        "admin_dashboard/tag_detail.html",
        {
            "tag": tag,
            "related_blogs": related_blogs,
            "active_menu": "tags",
        },
    )


@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def dashboard_tag_add(request):
    if request.method == "POST":
        try:
            name = _to_title_case(_clean_text(request.POST.get("name"), "Tag name", 100))
            raw_slug = (request.POST.get("slug") or "").strip()
            if BlogTag.objects.filter(name__iexact=name).exists():
                raise ValueError("Tag already exists.")
            slug_source = raw_slug or name
            slug = _build_unique_term_slug(BlogTag, slug_source)
            BlogTag.objects.create(name=name, slug=slug, is_active=request.POST.get("is_active") == "on")
            messages.success(request, "Tag created successfully.")
            return redirect("admin_dashboard:dashboard_tags")  # changed
        except ValueError as exc:
            messages.error(request, str(exc))

    return render(request, "admin_dashboard/tag_add.html", {"active_menu": "tags"})


@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def dashboard_tag_edit(request, tag_id):
    tag = get_object_or_404(BlogTag, pk=tag_id)

    if request.method == "POST":
        try:
            name = _to_title_case(_clean_text(request.POST.get("name"), "Tag name", 100))
            raw_slug = (request.POST.get("slug") or "").strip()
            if BlogTag.objects.filter(name__iexact=name).exclude(pk=tag.pk).exists():
                raise ValueError("Tag already exists.")
            slug_source = raw_slug or name
            slug = _build_unique_term_slug(BlogTag, slug_source, current_id=tag.pk)
            tag.name = name
            tag.slug = slug
            tag.is_active = request.POST.get("is_active") == "on"
            tag.save(update_fields=["name", "slug", "is_active", "updated_at"])
            messages.success(request, "Tag updated successfully.")
            return redirect("admin_dashboard:dashboard_tags")
        except ValueError as exc:
            messages.error(request, str(exc))

    return render(
        request,
        "admin_dashboard/tag_add.html",
        {"active_menu": "tags", "tag": tag, "is_edit": True},
    )


@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def dashboard_tag_delete(request, tag_id):
    tag = get_object_or_404(BlogTag, pk=tag_id)
    if request.method == "POST":
        tag.is_active = False
        tag.save(update_fields=["is_active", "updated_at"])
        messages.success(request, "Tag marked as inactive successfully.")
    return redirect("admin_dashboard:dashboard_tags")


@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def blog_edit(request, pk):
    blog = get_object_or_404(Blog, pk=pk, is_deleted=False)
    categories = BlogCategory.objects.filter(is_active=True).order_by("name")
    tags = BlogTag.objects.filter(is_active=True).order_by("name")
    form_values = {
        "author_name": blog.author.get_full_name() or blog.author.username,
        "title": blog.title,
        "short_description": blog.short_description,
        "description": blog.description,
        "is_active": blog.is_active,
    }
    field_errors = {
        "author_name": [],
        "title": [],
        "short_description": [],
        "description": [],
        "featured_image": [],
        "category_ids": [],
        "tag_ids": [],
    }
    non_field_errors = []
    selected_category_ids = list(map(str, blog.categories.values_list("id", flat=True)))
    selected_tag_ids = list(map(str, blog.tags.values_list("id", flat=True)))
    pending_delete_featured_image = False
    pending_remove_gallery_ids = []

    if request.method == "POST":
        selected_category_ids = request.POST.getlist("category_ids")
        selected_tag_ids = request.POST.getlist("tag_ids")
        form_values = {
            "author_name": request.POST.get("author_name") or "",
            "title": request.POST.get("title") or "",
            "short_description": request.POST.get("short_description") or "",
            "description": request.POST.get("description") or "",
            "is_active": request.POST.get("is_active") == "on",
        }

        def add_field_error(field_name, error_message):
            if field_name in field_errors:
                field_errors[field_name].append(error_message)
            else:
                non_field_errors.append(error_message)

        title = ""
        short_description = ""
        description = ""
        selected_author = None

        try:
            title = _clean_text(form_values["title"], "Title", 150)
            if not _is_title_case(title):
                add_field_error("title", "Title must be in Title Case.")
        except ValueError as exc:
            add_field_error("title", str(exc))

        try:
            short_description = _to_title_case(
                _clean_text(form_values["short_description"], "Short description", 255)
            )
        except ValueError as exc:
            add_field_error("short_description", str(exc))

        try:
            normalized_description = _normalize_rich_text_for_validation(form_values["description"])
            _clean_text(normalized_description, "Description", check_leading_trailing=False)
            description = (form_values["description"] or "").strip()
        except ValueError as exc:
            add_field_error("description", str(exc))

        try:
            selected_author = _get_or_create_author(form_values["author_name"])
        except ValueError as exc:
            add_field_error("author_name", str(exc))

        featured_image = request.FILES.get("featured_image")
        delete_featured_image = request.POST.get("delete_featured_image") == "1"
        gallery_images = request.FILES.getlist("gallery_images") or request.FILES.getlist("gallery_images[]")
        remove_gallery_image_ids = request.POST.getlist("remove_gallery_image_ids")
        pending_delete_featured_image = delete_featured_image
        pending_remove_gallery_ids = list(remove_gallery_image_ids)

        featured_image_required = delete_featured_image or not blog.featured_image
        if featured_image_required and not featured_image:
            add_field_error("featured_image", "Featured image is required.")

        if not selected_category_ids:
            add_field_error("category_ids", "At least one category is required.")
        if not selected_tag_ids:
            add_field_error("tag_ids", "At least one tag is required.")
        if len(selected_category_ids) != len(set(selected_category_ids)):
            add_field_error("category_ids", "Duplicate categories are not allowed.")
        if len(selected_tag_ids) != len(set(selected_tag_ids)):
            add_field_error("tag_ids", "Duplicate tags are not allowed.")

        selected_categories = list(BlogCategory.objects.filter(id__in=selected_category_ids, is_active=True))
        selected_tags = list(BlogTag.objects.filter(id__in=selected_tag_ids, is_active=True))
        if selected_category_ids and len(selected_categories) != len(selected_category_ids):
            add_field_error("category_ids", "One or more categories are invalid.")
        if selected_tag_ids and len(selected_tags) != len(selected_tag_ids):
            add_field_error("tag_ids", "One or more tags are invalid.")

        has_errors = any(field_errors[field_name] for field_name in field_errors) or bool(non_field_errors)

        if not has_errors:
            blog.author = selected_author
            blog.title = title
            blog.short_description = short_description
            blog.description = description
            blog.is_active = form_values["is_active"]
            if delete_featured_image and blog.featured_image:
                blog.featured_image.delete(save=False)
                blog.featured_image = ""
            if featured_image:
                blog.featured_image = featured_image
            blog.save()

            blog.categories.set(selected_categories)
            blog.tags.set(selected_tags)
            if remove_gallery_image_ids:
                remove_ids = []
                for value in remove_gallery_image_ids:
                    try:
                        remove_ids.append(int(value))
                    except (TypeError, ValueError):
                        continue
                if remove_ids:
                    removable_images = BlogImage.objects.filter(id__in=remove_ids)
                    for image in removable_images:
                        blog.gallery.remove(image)
                        if not image.blogs.exists():
                            image.delete()
            if gallery_images:
                created_gallery_images = [BlogImage.objects.create(image=image_file) for image_file in gallery_images]
                blog.gallery.add(*created_gallery_images)

            messages.success(request, "Blog updated successfully.")
            return redirect("admin_dashboard:dashboard_blogs")

    return render(
        request,
        "admin_dashboard/blog_add.html",
        {
            "blog": blog,
            "categories": categories,
            "tags": tags,
            "form_values": form_values,
            "field_errors": field_errors,
            "non_field_errors": non_field_errors,
            "selected_category_ids": selected_category_ids,
            "selected_tag_ids": selected_tag_ids,
            "pending_delete_featured_image": pending_delete_featured_image,
            "pending_remove_gallery_ids": pending_remove_gallery_ids,
            "is_edit": True,
            "active_menu": "blogs",
        },
    )


@login_required(login_url=DASHBOARD_LOGIN_URL)
@user_passes_test(_is_superuser, login_url=DASHBOARD_LOGIN_URL)
def blog_delete(request, pk):
    blog = get_object_or_404(Blog, pk=pk)
    if request.method == "POST":
        blog.is_active = False
        if blog.is_deleted:
            blog.is_deleted = False
            blog.deleted_at = None
            blog.save(update_fields=["is_active", "is_deleted", "deleted_at", "updated_at"])
        else:
            blog.save(update_fields=["is_active", "updated_at"])
        messages.success(request, "Blog marked as inactive successfully.")
    return redirect("admin_dashboard:dashboard_blogs")
