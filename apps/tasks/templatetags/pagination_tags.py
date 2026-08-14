"""
Template helpers for building a compact, numbered pagination bar.

Django's Paginator already knows how to build an "elided" page range
(e.g. 1, 2, ..., 8, 9, 10, ..., 24, 25) via get_elided_page_range(), but
that method needs the *current* page number as an argument, and Django
templates can't call a method with arguments directly. This filter is a
thin wrapper so any template can do:

    {% for page_num in page_obj|elided_range %}

and get back either a page number (int) or the string "…" for a gap,
ready to loop over.
"""
from django import template

register = template.Library()


@register.filter
def elided_range(page_obj, on_each_side=1):
    """Return an elided list of page numbers around the current page.

    `page_obj` is the Page instance Django's paginator views/context give
    you (e.g. `page_obj` in the standard pagination context). Entries are
    either an int (a real page number) or the literal string "…" for a
    collapsed run of skipped pages.
    """
    paginator = page_obj.paginator
    try:
        on_each_side = int(on_each_side)
    except (TypeError, ValueError):
        on_each_side = 1

    elided = paginator.get_elided_page_range(
        page_obj.number, on_each_side=on_each_side, on_ends=1
    )
    return [page if page != paginator.ELLIPSIS else "…" for page in elided]


@register.simple_tag
def querystring_without_page(request):
    """Rebuild the current querystring, dropping any existing `page` key,
    so pagination links can safely append their own `page=N` without
    losing an active search term, status filter, sort order, etc."""
    if not request:
        return ""
    params = request.GET.copy()
    params.pop("page", None)
    encoded = params.urlencode()
    return f"{encoded}&" if encoded else ""
