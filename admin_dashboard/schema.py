import graphene
import re
from graphene_django import DjangoObjectType
from django.contrib.auth.models import User
from django.utils.text import slugify
from GraphQL.models import BlogCategory


DOUBLE_SPACE_PATTERN = re.compile(r"(?<=\S) {2,}(?=\S)")
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


def _build_unique_term_slug(model_class, source_value, current_id=None):
    base_slug = slugify(source_value or "")
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


class UserType(DjangoObjectType):
    class Meta:
        model = User
        fields = ("id", "username", "first_name", "last_name", "is_superuser")


class BlogCategoryType(DjangoObjectType):
    class Meta:
        model = BlogCategory
        fields = "__all__"

class Query(graphene.ObjectType):

    categories = graphene.List(
        BlogCategoryType,
        status=graphene.String()
    )

    def resolve_categories(self, info, status="all"):

        user = info.context.user

        if not (user.is_authenticated and user.is_superuser):
            raise Exception("Not authorized")

        qs = BlogCategory.objects.all().order_by("-created_at")

        if status == "active":
            qs = qs.filter(is_active=True)

        if status == "inactive":
            qs = qs.filter(is_active=False)

        return qs

class CreateCategory(graphene.Mutation):

    class Arguments:
        name = graphene.String(required=True)
        slug = graphene.String()
        is_active = graphene.Boolean()

    category = graphene.Field(BlogCategoryType)
    success = graphene.Boolean()
    message = graphene.String()

    def mutate(self, info, name, slug=None, is_active=True):

        user = info.context.user
        if not (user.is_authenticated and user.is_superuser):
            raise Exception("Not authorized")

        name = _to_title_case(_clean_text(name, "Category name", 100))

        if BlogCategory.objects.filter(name__iexact=name).exists():
            return CreateCategory(success=False, message="Category already exists")

        slug_source = slug or name
        slug = _build_unique_term_slug(BlogCategory, slug_source)

        category = BlogCategory.objects.create(
            name=name,
            slug=slug,
            is_active=is_active
        )

        return CreateCategory(
            category=category,
            success=True,
            message="Category created"
        )


class UpdateCategory(graphene.Mutation):

    class Arguments:
        id = graphene.Int(required=True)
        name = graphene.String(required=True)
        slug = graphene.String()
        is_active = graphene.Boolean()

    success = graphene.Boolean()

    def mutate(self, info, id, name, slug=None, is_active=True):

        user = info.context.user
        if not (user.is_authenticated and user.is_superuser):
            raise Exception("Not authorized")

        category = BlogCategory.objects.get(id=id)

        name = _to_title_case(_clean_text(name, "Category name", 100))

        slug_source = slug or name
        slug = _build_unique_term_slug(
            BlogCategory,
            slug_source,
            current_id=category.id
        )

        category.name = name
        category.slug = slug
        category.is_active = is_active
        category.save()

        return UpdateCategory(success=True)


class DeleteCategory(graphene.Mutation):

    class Arguments:
        id = graphene.Int(required=True)

    success = graphene.Boolean()

    def mutate(self, info, id):

        user = info.context.user
        if not (user.is_authenticated and user.is_superuser):
            raise Exception("Not authorized")

        category = BlogCategory.objects.get(id=id)

        category.is_active = False
        category.save()

        return DeleteCategory(success=True)


class Mutation(graphene.ObjectType):

    create_category = CreateCategory.Field()
    update_category = UpdateCategory.Field()
    delete_category = DeleteCategory.Field()


schema = graphene.Schema(query=Query, mutation=Mutation)
