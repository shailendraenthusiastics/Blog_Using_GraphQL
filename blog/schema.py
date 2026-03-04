import graphene
import re
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.db.models import F
from django.utils.text import slugify
from django.utils import timezone
from graphene_django import DjangoObjectType
from graphql import GraphQLError
from graphql_auth import mutations as auth_mutations
from graphql_jwt.exceptions import JSONWebTokenError, JSONWebTokenExpired
from graphql_auth.schema import UserQuery, MeQuery
from graphql_jwt.utils import jwt_decode

from GraphQL.models import Blog, BlogCategory, BlogImage, BlogTag
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
def _normalize_text(value):
    if isinstance(value, str):
        return value.strip()
    return value
def _to_title_case(value):
    normalized = _normalize_text(value)
    if not normalized:
        return normalized
    return normalized.title()
def _validate_non_empty_name(name, label):
    if not name:
        raise GraphQLError(f"{label}: This field cannot be empty.")
def _validate_no_outer_or_multiple_spaces(value, label):
    if value is None:
        return
    if not isinstance(value, str):
        return
    if value != value.strip():
        raise GraphQLError(f"{label}: Leading or trailing spaces are not allowed.")
    if re.search(r"(?<=\S) {2,}(?=\S)", value):
        raise GraphQLError(f"{label}: Multiple spaces between words are not allowed.")
def _ensure_unique_name(model_cls, name, label, exclude_id=None):
    queryset = model_cls.objects.filter(name=name)
    if exclude_id is not None:
        queryset = queryset.exclude(pk=exclude_id)
    if queryset.exists():
        raise GraphQLError(f"{label}: '{name}' already exists.")
def _validate_blog_title_and_slug(title, slug):
    if title and title != title.title():
        raise GraphQLError("title: Title must be in title case.")
    if slug and not SLUG_PATTERN.match(slug):
        raise GraphQLError(
            "slug: Slug must contain only lowercase letters, numbers, and hyphens."
        )
def _build_slug_from_title(title):
    generated_slug = slugify(title or "")
    if not generated_slug:
        raise GraphQLError("slug: Slug could not be generated from title.")
    return generated_slug
def _ensure_slug_unique(slug, exclude_id=None):
    queryset = Blog.objects.filter(slug=slug)
    if exclude_id is not None:
        queryset = queryset.exclude(pk=exclude_id)
    if queryset.exists():
        raise GraphQLError("slug: This slug already exists.")

def _get_authenticated_user(info):
    user = info.context.user
    if user and user.is_authenticated:
        return user

    auth_header = info.context.META.get("HTTP_AUTHORIZATION", "").strip()
    if not auth_header:
        raise GraphQLError("JWT authentication is required")
    token_parts = auth_header.split()
    token = auth_header
    if len(token_parts) == 2 and token_parts[0].lower() in {"jwt", "bearer"}:
        token = token_parts[1]
    try:
        jwt_decode(token)
    except JSONWebTokenExpired as exc:
        raise GraphQLError("Token has expired") from exc
    except JSONWebTokenError as exc:
        if "Signature has expired" in str(exc):
            raise GraphQLError("Token has expired") from exc
        raise GraphQLError("Invalid JWT token") from exc
    except Exception as exc:
        if "Signature has expired" in str(exc):
            raise GraphQLError("Token has expired") from exc
        raise GraphQLError("Invalid JWT token") from exc

    raise GraphQLError("JWT authentication is required")
def _ensure_blog_write_permission(user, blog):
    if user.is_superuser:
        return
    if blog.author_id != user.id:
        raise GraphQLError("You can only update or delete your own blog")
def _ensure_superuser(user, action_name):
    if not user.is_superuser:
        raise GraphQLError(f"Only superuser can {action_name}")
class UserType(DjangoObjectType):
    class Meta:
        model = get_user_model()
        fields = ("id", "username", "email")
class BlogCategoryType(DjangoObjectType):
    class Meta:
        model = BlogCategory
        fields = "__all__"

class BlogTagType(DjangoObjectType):
    class Meta:
        model = BlogTag
        fields = "__all__"

class BlogImageType(DjangoObjectType):
    class Meta:
        model = BlogImage
        fields = "__all__"

    def resolve_image(self, info):
        if not self.image:
            return None
        request = getattr(info, "context", None)
        if request and hasattr(request, "build_absolute_uri"):
            return request.build_absolute_uri(self.image.url)
        return self.image.url
class BlogType(DjangoObjectType):
    class Meta:
        model = Blog
        fields = "__all__"

    def resolve_featured_image(self, info):
        if not self.featured_image:
            return None
        request = getattr(info, "context", None)
        if request and hasattr(request, "build_absolute_uri"):
            return request.build_absolute_uri(self.featured_image.url)
        return self.featured_image.url
class RegisterUser(graphene.Mutation):
    success = graphene.Boolean()
    errors = graphene.String()
    user = graphene.Field(UserType)

    class Arguments:
        username = graphene.String(required=True)
        password = graphene.String(required=True)
        email = graphene.String(required=True)

    def mutate(self, info, username, password, email):
        _validate_no_outer_or_multiple_spaces(username, "username")
        user_model = get_user_model()
        if user_model.objects.filter(username=username).exists():
            return RegisterUser(success=False, errors="Username taken")

        user = user_model.objects.create_user(username=username, email=email, password=password)
        return RegisterUser(success=True, user=user)

class CreateCategory(graphene.Mutation):
    category = graphene.Field(BlogCategoryType)

    class Arguments:
        name = graphene.String(required=True)
        is_active = graphene.Boolean(required=False)

    def mutate(self, info, name, is_active=True):
        current_user = _get_authenticated_user(info)
        _ensure_superuser(current_user, "create category")
        _validate_no_outer_or_multiple_spaces(name, "name")
        name = _normalize_text(name)
        _validate_non_empty_name(name, "name")
        _ensure_unique_name(BlogCategory, name, "name")
        try:
            category = BlogCategory.objects.create(name=name, is_active=is_active)
        except IntegrityError as exc:
            raise GraphQLError(f"name: '{name}' already exists.") from exc
        return CreateCategory(category=category)

class UpdateCategory(graphene.Mutation):
    category = graphene.Field(BlogCategoryType)

    class Arguments:
        id = graphene.ID(required=True)
        name = graphene.String(required=False)
        is_active = graphene.Boolean(required=False)

    def mutate(self, info, id, name=None, is_active=None):
        current_user = _get_authenticated_user(info)
        _ensure_superuser(current_user, "update category")
        try:
            category = BlogCategory.objects.get(pk=id)
        except BlogCategory.DoesNotExist as exc:
            raise GraphQLError("Category not found") from exc

        if name is not None:
            _validate_no_outer_or_multiple_spaces(name, "name")
            name = _normalize_text(name)
            _validate_non_empty_name(name, "name")
            _ensure_unique_name(BlogCategory, name, "name", exclude_id=category.id)
            category.name = name
        if is_active is not None:
            category.is_active = is_active
        try:
            category.save()
        except IntegrityError as exc:
            raise GraphQLError(f"name: '{category.name}' already exists.") from exc
        return UpdateCategory(category=category)
class DeleteCategory(graphene.Mutation):
    success = graphene.Boolean()

    class Arguments:
        id = graphene.ID(required=True)

    def mutate(self, info, id):
        current_user = _get_authenticated_user(info)
        _ensure_superuser(current_user, "delete category")
        category = BlogCategory.objects.filter(pk=id).first()
        if not category:
            return DeleteCategory(success=False)
        category.is_active = False
        category.save(update_fields=["is_active", "updated_at"])
        return DeleteCategory(success=True)
class CreateTag(graphene.Mutation):
    tag = graphene.Field(BlogTagType)

    class Arguments:
        name = graphene.String(required=True)
        is_active = graphene.Boolean(required=False)

    def mutate(self, info, name, is_active=True):
        current_user = _get_authenticated_user(info)
        _ensure_superuser(current_user, "create tag")
        _validate_no_outer_or_multiple_spaces(name, "name")
        name = _normalize_text(name)
        _validate_non_empty_name(name, "name")
        _ensure_unique_name(BlogTag, name, "name")
        try:
            tag = BlogTag.objects.create(name=name, is_active=is_active)
        except IntegrityError as exc:
            raise GraphQLError(f"name: '{name}' already exists.") from exc
        return CreateTag(tag=tag)
class UpdateTag(graphene.Mutation):
    tag = graphene.Field(BlogTagType)

    class Arguments:
        id = graphene.ID(required=True)
        name = graphene.String(required=False)
        is_active = graphene.Boolean(required=False)

    def mutate(self, info, id, name=None, is_active=None):
        current_user = _get_authenticated_user(info)
        _ensure_superuser(current_user, "update tag")
        try:
            tag = BlogTag.objects.get(pk=id)
        except BlogTag.DoesNotExist as exc:
            raise GraphQLError("Tag not found") from exc

        if name is not None:
            _validate_no_outer_or_multiple_spaces(name, "name")
            name = _normalize_text(name)
            _validate_non_empty_name(name, "name")
            _ensure_unique_name(BlogTag, name, "name", exclude_id=tag.id)
            tag.name = name
        if is_active is not None:
            tag.is_active = is_active
        try:
            tag.save()
        except IntegrityError as exc:
            raise GraphQLError(f"name: '{tag.name}' already exists.") from exc
        return UpdateTag(tag=tag)
class DeleteTag(graphene.Mutation):
    success = graphene.Boolean()

    class Arguments:
        id = graphene.ID(required=True)

    def mutate(self, info, id):
        current_user = _get_authenticated_user(info)
        _ensure_superuser(current_user, "delete tag")
        tag = BlogTag.objects.filter(pk=id).first()
        if not tag:
            return DeleteTag(success=False)
        tag.is_active = False
        tag.save(update_fields=["is_active", "updated_at"])
        return DeleteTag(success=True)
class CreateBlog(graphene.Mutation):
    blog = graphene.Field(BlogType)

    class Arguments:
        title = graphene.String(required=True)
        slug = graphene.String(required=False)
        short_description = graphene.String(required=True)
        description = graphene.String(required=True)
        featured_image = graphene.String(required=True)
        category_ids = graphene.List(graphene.ID, required=True)
        tag_ids = graphene.List(graphene.ID, required=True)
        gallery_ids = graphene.List(graphene.ID, required=False)
        is_active = graphene.Boolean(required=False)
        author_id = graphene.ID(required=False)

    def mutate(
        self,
        info,
        title,
        short_description,
        description,
        featured_image,
        category_ids,
        tag_ids,
        slug=None,
        gallery_ids=None,
        is_active=True,
        author_id=None,
    ):
        current_user = _get_authenticated_user(info)
        _validate_no_outer_or_multiple_spaces(title, "title")
        _validate_no_outer_or_multiple_spaces(short_description, "shortDescription")
        _validate_no_outer_or_multiple_spaces(description, "description")
        title = _normalize_text(title)
        short_description = _to_title_case(short_description)
        slug = _normalize_text(slug)

        if not slug:
            slug = _build_slug_from_title(title)
        _validate_blog_title_and_slug(title, slug)
        _ensure_slug_unique(slug)

        user_model = get_user_model()
        if author_id:
            if not current_user.is_superuser and str(current_user.id) != str(author_id):
                raise GraphQLError("Only superuser can create blog for another user")
            try:
                author = user_model.objects.get(pk=author_id)
            except user_model.DoesNotExist as exc:
                raise GraphQLError("Author not found") from exc
        else:
            author = current_user

        categories = list(BlogCategory.objects.filter(id__in=category_ids))
        if len(categories) != len(set(category_ids)):
            raise GraphQLError("One or more categories are invalid")

        tags = list(BlogTag.objects.filter(id__in=tag_ids))
        if len(tags) != len(set(tag_ids)):
            raise GraphQLError("One or more tags are invalid")

        blog = Blog(
            title=title,
            slug=slug,
            short_description=short_description,
            description=description,
            featured_image=featured_image,
            author=author,
            is_active=is_active,
        )
        try:
            blog.save()
        except IntegrityError as exc:
            if "slug" in str(exc).lower():
                raise GraphQLError("slug: This slug already exists.") from exc
            raise
        blog.categories.set(categories)
        blog.tags.set(tags)

        if gallery_ids:
            existing_gallery_images = BlogImage.objects.filter(id__in=gallery_ids)
            if existing_gallery_images.count() != len(set(gallery_ids)):
                raise GraphQLError("One or more gallery images are invalid")

        if gallery_ids:
            blog.gallery.set(list(BlogImage.objects.filter(id__in=gallery_ids)))

        return CreateBlog(blog=blog)

class UpdateBlog(graphene.Mutation):
    blog = graphene.Field(BlogType)

    class Arguments:
        id = graphene.ID(required=True)
        title = graphene.String(required=False)
        slug = graphene.String(required=False)
        short_description = graphene.String(required=False)
        description = graphene.String(required=False)
        featured_image = graphene.String(required=False)
        category_ids = graphene.List(graphene.ID, required=False)
        tag_ids = graphene.List(graphene.ID, required=False)
        gallery_ids = graphene.List(graphene.ID, required=False)
        is_active = graphene.Boolean(required=False)

    def mutate(
        self,
        info,
        id,
        title=None,
        slug=None,
        short_description=None,
        description=None,
        featured_image=None,
        category_ids=None,
        tag_ids=None,
        gallery_ids=None,
        is_active=None,
    ):
        current_user = _get_authenticated_user(info)
        try:
            blog = Blog.objects.get(pk=id)
        except Blog.DoesNotExist as exc:
            raise GraphQLError("Blog not found") from exc

        _ensure_blog_write_permission(current_user, blog)

        if title is not None:
            _validate_no_outer_or_multiple_spaces(title, "title")
            title = _normalize_text(title)
            _validate_blog_title_and_slug(title, blog.slug)
            blog.title = title
        if slug is not None:
            slug = _normalize_text(slug)
            if not slug:
                source_title = blog.title if title is None else title
                slug = _build_slug_from_title(source_title)
            _validate_blog_title_and_slug(blog.title, slug)
            _ensure_slug_unique(slug, exclude_id=blog.id)
            blog.slug = slug
        if short_description is not None:
            _validate_no_outer_or_multiple_spaces(short_description, "shortDescription")
            blog.short_description = _to_title_case(short_description)
        if description is not None:
            _validate_no_outer_or_multiple_spaces(description, "description")
            blog.description = description
        if featured_image is not None:
            blog.featured_image = featured_image
        if is_active is not None:
            blog.is_active = is_active
        try:
            blog.save()
        except IntegrityError as exc:
            if "slug" in str(exc).lower():
                raise GraphQLError("slug: This slug already exists.") from exc
            raise

        if category_ids is not None:
            categories = list(BlogCategory.objects.filter(id__in=category_ids))
            if len(categories) != len(set(category_ids)):
                raise GraphQLError("One or more categories are invalid")
            blog.categories.set(categories)

        if tag_ids is not None:
            tags = list(BlogTag.objects.filter(id__in=tag_ids))
            if len(tags) != len(set(tag_ids)):
                raise GraphQLError("One or more tags are invalid")
            blog.tags.set(tags)

        if gallery_ids is not None:
            existing_gallery_images = list(BlogImage.objects.filter(id__in=gallery_ids))
            if len(existing_gallery_images) != len(set(gallery_ids)):
                raise GraphQLError("One or more gallery images are invalid")
            blog.gallery.set(existing_gallery_images)

        return UpdateBlog(blog=blog)
class DeleteBlog(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    ok = graphene.Boolean()

    def mutate(self, info, id):
        blog = Blog.objects.get(pk=id, is_deleted=False)
        blog.is_deleted = True
        blog.deleted_at = timezone.now()
        blog.save(update_fields=["is_deleted", "deleted_at"])
        return DeleteBlog(ok=True)
class AuthMutation(graphene.ObjectType):
    register = RegisterUser.Field()
    token_auth = auth_mutations.ObtainJSONWebToken.Field()
    verify_token = auth_mutations.VerifyToken.Field()
    refresh_token = auth_mutations.RefreshToken.Field()
class BlogMutation(graphene.ObjectType):
    create_category = CreateCategory.Field()
    update_category = UpdateCategory.Field()
    delete_category = DeleteCategory.Field()
    create_tag = CreateTag.Field()
    update_tag = UpdateTag.Field()
    delete_tag = DeleteTag.Field()
    create_blog = CreateBlog.Field()
    update_blog = UpdateBlog.Field()
    delete_blog = DeleteBlog.Field()

class Query(UserQuery, MeQuery, graphene.ObjectType):
    user = graphene.Field(UserType, username=graphene.String())

    categories = graphene.List(BlogCategoryType, is_active=graphene.Boolean())
    category = graphene.Field(BlogCategoryType, id=graphene.ID(required=True))

    tags = graphene.List(BlogTagType, is_active=graphene.Boolean())
    tag = graphene.Field(BlogTagType, id=graphene.ID(required=True))

    blogs = graphene.List(
        BlogType,
        is_active=graphene.Boolean(),
        slug=graphene.String(),
        author_username=graphene.String(),
    )
    blog = graphene.Field(BlogType, id=graphene.ID(), slug=graphene.String())

    def resolve_user(self, info, username=None):
        if not username:
            return None
        user = get_user_model().objects.filter(username=username, is_active=True).first()
        if not user:
            raise GraphQLError("No user found")
        return user

    def resolve_categories(self, info, is_active=None):
        queryset = BlogCategory.objects.filter(is_active=True).order_by("-created_at")
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)
        return queryset

    def resolve_category(self, info, id):
        return BlogCategory.objects.filter(pk=id, is_active=True).first()

    def resolve_tags(self, info, is_active=None):
        queryset = BlogTag.objects.filter(is_active=True).order_by("-created_at")
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)
        return queryset

    def resolve_tag(self, info, id):
        return BlogTag.objects.filter(pk=id, is_active=True).first()

    def resolve_blogs(self, info, is_active=None, slug=None, author_username=None):
        queryset = Blog.objects.select_related("author").prefetch_related(
            "categories", "tags", "gallery"
        ).filter(is_active=True).order_by("-created_at")
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)
        if slug:
            queryset = queryset.filter(slug=slug)
        if author_username:
            queryset = queryset.filter(author__username=author_username)
        return queryset

    def resolve_blog(self, info, id=None, slug=None):
        queryset = Blog.objects.select_related("author").prefetch_related(
            "categories", "tags", "gallery"
        ).filter(is_active=True)
        if id:
            blog = queryset.filter(pk=id).first()
            if not blog:
                raise GraphQLError("Blog not found")
            Blog.objects.filter(pk=blog.pk).update(view_count=F("view_count") + 1)
            blog.refresh_from_db(fields=["view_count"])
            return blog
        if slug:
            blog = queryset.filter(slug=slug).first()
            if not blog:
                raise GraphQLError("Blog not found")
            return blog
        return None


class Mutation(AuthMutation, BlogMutation, graphene.ObjectType):
    pass
schema = graphene.Schema(query=Query, mutation=Mutation)
