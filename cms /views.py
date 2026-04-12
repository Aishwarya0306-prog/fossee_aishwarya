from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import Http404, JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.cache import cache_page
from django.views.decorators.http import require_GET

from cms.models import BlogPost, MediaFile, Nav, Page, Tag

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CACHE_TTL_SHORT  = 60 * 5        # 5 minutes  — nav, page
CACHE_TTL_MEDIUM = 60 * 30       # 30 minutes — blog list
BLOG_PAGE_SIZE   = 10
MEDIA_PAGE_SIZE  = 24


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_nav_context() -> list:
    """
    Build the navigation context dict, served from cache when available.
    Matches the updated models: related_name='sub_items', ordering by position.
    """
    cached = cache.get('cms_nav_context')
    if cached is not None:
        return cached

    navs = []
    for nav in Nav.objects.filter(active=True).select_related().prefetch_related('sub_items'):
        navs.append({
            'id':              nav.pk,
            'name':            nav.name,
            'link':            nav.link,
            'icon':            nav.icon,
            'open_in_new_tab': nav.open_in_new_tab,
            'sub_items':       list(
                nav.sub_items.filter(active=True).order_by('position')
            ),
        })

    cache.set('cms_nav_context', navs, CACHE_TTL_SHORT)
    return navs


def _paginate(queryset, page_number: int, per_page: int):
    """Return a Page object; falls back to page 1 on bad input."""
    paginator = Paginator(queryset, per_page)
    try:
        return paginator.page(page_number)
    except (PageNotAnInteger, EmptyPage):
        return paginator.page(1)


def _base_context(request) -> dict:
    """Context shared by every template."""
    return {
        'navs':         _build_nav_context(),
        'current_path': request.path,
    }


# ---------------------------------------------------------------------------
# CMS page view
# ---------------------------------------------------------------------------

@require_GET
def page_view(request, permalink: str = ''):
    """
    Renders a CMS Page by permalink.
    Falls back to 'home' when no permalink is given.
    """
    if not permalink:
        permalink = 'home'

    # Sanitise: slugs must be alphanumeric + hyphens only
    if not permalink.replace('-', '').replace('/', '').isalnum():
        raise Http404

    cache_key = f'cms_page_{permalink}'
    page = cache.get(cache_key)

    if page is None:
        page = get_object_or_404(Page, permalink=permalink, active=True)
        cache.set(cache_key, page, CACHE_TTL_SHORT)

    ctx = _base_context(request)
    ctx['page'] = page
    ctx['seo']  = getattr(page, 'seo', None)

    return render(request, page.template, ctx)


# ---------------------------------------------------------------------------
# Blog views
# ---------------------------------------------------------------------------

@require_GET
def blog_list(request):
    """
    Paginated, filterable blog post listing.
    Supports ?tag=<slug> and ?q=<search term>.
    """
    tag_slug = request.GET.get('tag', '').strip()
    query    = request.GET.get('q',   '').strip()
    page_num = request.GET.get('page', 1)

    posts = (
        BlogPost.objects
        .filter(status=BlogPost.Status.PUBLISHED)
        .select_related('seo')
        .prefetch_related('tags')
        .order_by('-pub_date')
    )

    active_tag = None
    if tag_slug:
        active_tag = get_object_or_404(Tag, slug=tag_slug)
        posts = posts.filter(tags=active_tag)

    if query:
        posts = posts.filter(title__icontains=query) | posts.filter(excerpt__icontains=query)
        posts = posts.distinct()

    page_obj = _paginate(posts, page_num, BLOG_PAGE_SIZE)

    ctx = _base_context(request)
    ctx.update({
        'page_obj':   page_obj,
        'tags':       Tag.objects.all().order_by('name'),
        'active_tag': active_tag,
        'query':      query,
    })
    return render(request, 'cms/blog/list.html', ctx)


@require_GET
def blog_detail(request, slug: str):
    """Renders a single published blog post."""
    post = get_object_or_404(
        BlogPost.objects.select_related('seo').prefetch_related('tags'),
        slug=slug,
        status=BlogPost.Status.PUBLISHED,
    )

    # Cheap related posts: same tags, exclude self
    related = (
        BlogPost.objects
        .filter(status=BlogPost.Status.PUBLISHED, tags__in=post.tags.all())
        .exclude(pk=post.pk)
        .distinct()
        .order_by('-pub_date')[:3]
    )

    ctx = _base_context(request)
    ctx.update({
        'post':    post,
        'seo':     getattr(post, 'seo', None),
        'related': related,
    })
    return render(request, 'cms/blog/detail.html', ctx)


@require_GET
def blog_tag(request, slug: str):
    """Shortcut: redirect-style view that re-uses blog_list with a tag filter."""
    tag = get_object_or_404(Tag, slug=slug)
    return blog_list(request._wrapped if hasattr(request, '_wrapped') else request.__class__(
        request.environ | {'QUERY_STRING': f'tag={tag.slug}'}
    ))


# ---------------------------------------------------------------------------
# Media library view (staff only)
# ---------------------------------------------------------------------------

@require_GET
@login_required
def media_library(request):
    """
    Paginated media library, filterable by type.
    Restricted to logged-in users.
    """
    media_type = request.GET.get('type', '').strip()
    page_num   = request.GET.get('page', 1)

    files = MediaFile.objects.filter(active=True).order_by('-created_at')

    if media_type in MediaFile.MediaType.values:
        files = files.filter(media_type=media_type)

    page_obj = _paginate(files, page_num, MEDIA_PAGE_SIZE)

    ctx = _base_context(request)
    ctx.update({
        'page_obj':    page_obj,
        'media_types': MediaFile.MediaType.choices,
        'active_type': media_type,
    })
    return render(request, 'cms/media/library.html', ctx)


# ---------------------------------------------------------------------------
# Search view
# ---------------------------------------------------------------------------

@require_GET
def search(request):
    """
    Searches published Pages and BlogPosts.
    Returns JSON when ?format=json is present, otherwise renders a template.
    """
    query    = request.GET.get('q', '').strip()
    page_num = request.GET.get('page', 1)
    fmt      = request.GET.get('format', '')

    results = []
    if query:
        pages = (
            Page.objects
            .filter(active=True, title__icontains=query)
            .values('title', 'permalink')
        )
        posts = (
            BlogPost.objects
            .filter(status=BlogPost.Status.PUBLISHED, title__icontains=query)
            .values('title', 'slug', 'excerpt', 'pub_date')
        )

        results = [
            {'type': 'page', 'title': p['title'], 'url': f'/{p["permalink"]}/'}
            for p in pages
        ] + [
            {
                'type':    'blog',
                'title':   p['title'],
                'url':     f'/blog/{p["slug"]}/',
                'excerpt': p['excerpt'],
                'date':    p['pub_date'],
            }
            for p in posts
        ]

    if fmt == 'json':
        return JsonResponse({'query': query, 'results': results})

    page_obj = _paginate(results, page_num, 20)

    ctx = _base_context(request)
    ctx.update({'query': query, 'page_obj': page_obj})
    return render(request, 'cms/search.html', ctx)


# ---------------------------------------------------------------------------
# Custom error handlers (wire up in urls.py)
# ---------------------------------------------------------------------------

def handler_404(request, exception=None):
    ctx = _base_context(request)
    ctx['exception'] = str(exception) if exception else 'Page not found.'
    return render(request, 'cms/errors/404.html', ctx, status=404)


def handler_500(request):
    ctx = _base_context(request)
    return render(request, 'cms/errors/500.html', ctx, status=500)


def handler_403(request, exception=None):
    ctx = _base_context(request)
    return render(request, 'cms/errors/403.html', ctx, status=403)
