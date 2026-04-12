import datetime as dt
import logging

import pandas as pd

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET
from django.db.models import Count

from teams.models import Team
from workshop_app.models import Workshop, states

from .forms import FilterForm

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_LOOKAHEAD_DAYS = 15
CACHE_TTL_STATS        = 60 * 10       # 10 minutes
ALLOWED_SORT_FIELDS    = {"date", "-date", "title", "-title"}
STATUS_MAP             = {0: "Pending", 1: "Success", 2: "Rejected"}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_instructor(user) -> bool:
    """Return True if the user belongs to the 'instructor' group."""
    return user.groups.filter(name="instructor").exists()


def _base_workshop_qs():
    """
    Base queryset with all relations pre-joined to avoid N+1 queries
    throughout both views.
    """
    return Workshop.objects.select_related(
        "workshop_type",
        "coordinator",
        "coordinator__profile",
        "instructor",
    )


def _safe_sort(sort: str) -> str:
    """
    Validate the sort field against an allowlist to prevent
    arbitrary ORDER BY injection, then map to a real model field.
    """
    sort = sort if sort in ALLOWED_SORT_FIELDS else "-date"
    return sort.replace("title", "workshop_type__workshoptype_name")


def _apply_filters(qs, cleaned: dict, user=None):
    """
    Apply every FilterForm cleaned_data key to the queryset.
    Only non-empty values produce WHERE clauses — no silent defaults.
    """
    from_date      = cleaned.get("from_date")
    to_date        = cleaned.get("to_date")
    state          = cleaned.get("state")
    workshop_type  = cleaned.get("workshop_type")
    status         = cleaned.get("status")
    keyword        = cleaned.get("keyword", "").strip()
    show_workshops = cleaned.get("show_workshops")
    sort           = cleaned.get("sort") or "-date"

    if from_date and to_date:
        qs = qs.filter(date__range=(from_date, to_date))
    if state:
        qs = qs.filter(coordinator__profile__state=state)
    if workshop_type:
        qs = qs.filter(workshop_type=workshop_type)
    if status:
        # Reverse-map human label → integer code safely
        reverse_status = {v.lower(): k for k, v in STATUS_MAP.items()}
        code = reverse_status.get(status.lower())
        if code is not None:
            qs = qs.filter(status=code)
    if keyword:
        qs = (
            qs.filter(workshop_type__workshoptype_name__icontains=keyword)
            | qs.filter(coordinator__first_name__icontains=keyword)
            | qs.filter(coordinator__profile__institute__icontains=keyword)
        ).distinct()
    if show_workshops and user and user.is_authenticated:
        if _is_instructor(user):
            qs = qs.filter(instructor=user)
        else:
            qs = qs.filter(coordinator=user)

    return qs.order_by(_safe_sort(sort))


def _build_csv_response(workshops) -> HttpResponse | None:
    """
    Build a streaming CSV HttpResponse from the workshop queryset.
    Returns None when the queryset is empty so the caller can show a message.
    """
    data = workshops.values(
        "workshop_type__workshoptype_name",
        "coordinator__first_name",
        "coordinator__last_name",
        "instructor__first_name",
        "instructor__last_name",
        "coordinator__profile__state",
        "date",
        "status",
    )
    df = pd.DataFrame(list(data))
    if df.empty:
        return None

    # Humanise coded columns
    df["status"] = df["status"].map(STATUS_MAP).fillna("Unknown")
    state_lookup = dict(states)
    df["coordinator__profile__state"] = (
        df["coordinator__profile__state"]
        .map(state_lookup)
        .fillna(df["coordinator__profile__state"])
    )

    df.rename(columns={
        "workshop_type__workshoptype_name": "Workshop Type",
        "coordinator__first_name":          "Coordinator First Name",
        "coordinator__last_name":           "Coordinator Last Name",
        "instructor__first_name":           "Instructor First Name",
        "instructor__last_name":            "Instructor Last Name",
        "coordinator__profile__state":      "State",
        "date":                             "Date",
        "status":                           "Status",
    }, inplace=True)

    filename = f"workshops_{dt.date.today().isoformat()}.csv"
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    df.to_csv(response, index=False)
    return response


def _get_page(qs, page_number, per_page: int):
    """Paginate and fall back to page 1 on any bad input."""
    paginator = Paginator(qs, per_page)
    try:
        return paginator.page(page_number)
    except (EmptyPage, PageNotAnInteger):
        return paginator.page(1)


def _stats_cache_key(get_params: dict) -> str:
    """Stable cache key derived from the full set of GET parameters."""
    fingerprint = frozenset(
        (k, v) for k, v in sorted(get_params.items()) if k != "page"
    )
    return f"ws_public_stats_{hash(fingerprint)}"


# ---------------------------------------------------------------------------
# Public workshop statistics view
# ---------------------------------------------------------------------------

@require_GET
def workshop_public_stats(request):
    """
    Filterable, paginated workshop listing with optional CSV export.

    Filter dimensions: date range, state, workshop type, status,
    keyword search, my-workshops toggle, and sort order.
    All powered by the updated FilterForm.
    """
    user     = request.user
    get_data = request.GET

    # Instantiate form — unbound when no GET params, bound otherwise
    form = FilterForm(get_data or None)

    # Default date window (used when form is unbound or both dates are absent)
    today        = timezone.now().date()
    default_from = today
    default_to   = today + dt.timedelta(days=DEFAULT_LOOKAHEAD_DAYS)

    base_qs = _base_workshop_qs().filter(status=1)

    if form.is_valid():
        cleaned = form.cleaned_data

        # Fill in missing date bounds with defaults (don't mutate form data)
        if not cleaned.get("from_date"):
            cleaned["from_date"] = default_from
        if not cleaned.get("to_date"):
            cleaned["to_date"] = default_to

        workshops = _apply_filters(base_qs, cleaned, user=user)

        # ── CSV download ────────────────────────────────────────
        if get_data.get("download"):
            csv_response = _build_csv_response(workshops)
            if csv_response:
                return csv_response
            messages.warning(
                request,
                "No workshops match the current filters — nothing to download.",
            )

    elif get_data:
        # Submitted but invalid — log for debugging, show default window
        logger.debug(
            "workshop_public_stats: FilterForm invalid — %s", form.errors.as_json()
        )
        workshops = base_qs.filter(
            date__range=(default_from, default_to)
        ).order_by("date")

    else:
        # Fresh page load with no params
        workshops = base_qs.filter(
            date__range=(default_from, default_to)
        ).order_by("date")

    # ── Aggregated state/type counts (cache per unique filter set) ──
    cache_key = _stats_cache_key(dict(get_data))
    stats     = cache.get(cache_key)
    if stats is None:
        ws_states, ws_count        = Workshop.objects.get_workshops_by_state(workshops)
        ws_type, ws_type_count     = Workshop.objects.get_workshops_by_type(workshops)
        stats = (ws_states, ws_count, ws_type, ws_type_count)
        cache.set(cache_key, stats, CACHE_TTL_STATS)

    ws_states, ws_count, ws_type, ws_type_count = stats

    # ── Pagination ───────────────────────────────────────────────
    per_page = 25
    if form.is_valid():
        try:
            per_page = int(form.cleaned_data.get("per_page") or 25)
        except (ValueError, TypeError):
            pass

    page_obj = _get_page(workshops, get_data.get("page"), per_page)

    context = {
        "form":          form,
        "objects":       page_obj,
        "ws_states":     ws_states,
        "ws_count":      ws_count,
        "ws_type":       ws_type,
        "ws_type_count": ws_type_count,
    }
    return render(request, "statistics_app/workshop_public_stats.html", context)


# ---------------------------------------------------------------------------
# Team statistics view
# ---------------------------------------------------------------------------

@login_required
@require_GET
def team_stats(request, team_id=None):
    """
    Per-member workshop count chart for a given team.

    Security: the requesting user must be a member of the team.
    Queries: single COUNT aggregation instead of one query per member.
    Caching: member counts are cached 10 minutes per team.
    """
    user = request.user

    all_teams = (
        Team.objects
        .prefetch_related("members__user")
        .order_by("id")
    )

    if not all_teams.exists():
        messages.warning(request, "No teams have been created yet.")
        return redirect(reverse("workshop_app:index"))

    team = (
        get_object_or_404(all_teams, id=team_id)
        if team_id
        else all_teams.first()
    )

    # ── Membership guard ─────────────────────────────────────────
    if not team.members.filter(user=user).exists():
        messages.info(request, "You are not a member of this team.")
        return redirect(reverse("workshop_app:index"))

    # ── Per-member counts (cached per team pk) ───────────────────
    cache_key    = f"team_stats_{team.pk}"
    member_data  = cache.get(cache_key)

    if member_data is None:
        members = (
            team.members
            .select_related("user")
            .order_by("user__first_name", "user__last_name")
        )

        # One aggregated query replaces N individual count queries
        member_ids  = list(members.values_list("user_id", flat=True))
        count_map   = {
            row["instructor_id"]: row["count"]
            for row in Workshop.objects
                .filter(instructor_id__in=member_ids)
                .values("instructor_id")
                .annotate(count=Count("id"))
        }

        member_data = {
            (m.user.get_full_name() or m.user.username): count_map.get(m.user_id, 0)
            for m in members
        }
        cache.set(cache_key, member_data, CACHE_TTL_STATS)

    context = {
        "team_labels": list(member_data.keys()),
        "ws_count":    list(member_data.values()),
        "all_teams":   all_teams,
        "active_team": team,
    }
    return render(request, "statistics_app/team_stats.html", context)
