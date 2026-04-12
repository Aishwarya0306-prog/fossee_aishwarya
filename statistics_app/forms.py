from datetime import date, timedelta

from django import forms
from django.core.exceptions import ValidationError

from workshop_app.models import WorkshopType, states

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SORT_CHOICES = [
    ("-date", "Latest first"),
    ("date",  "Oldest first"),
    ("title", "Workshop name (A–Z)"),
    ("-title","Workshop name (Z–A)"),
]

STATUS_CHOICES = [
    ("",           "All statuses"),
    ("completed",  "Completed"),
    ("upcoming",   "Upcoming"),
    ("cancelled",  "Cancelled"),
]

# Shared widget CSS classes
_INPUT   = "ws-input"
_SELECT  = "ws-select"
_CHECK   = "ws-check"


# ---------------------------------------------------------------------------
# Shared widget factory helpers
# ---------------------------------------------------------------------------

def _date_widget(placeholder: str = "") -> forms.DateInput:
    return forms.DateInput(attrs={
        "type":        "date",
        "class":       _INPUT,
        "placeholder": placeholder,
    })


def _select_widget(extra: str = "") -> forms.Select:
    return forms.Select(attrs={"class": f"{_SELECT} {extra}".strip()})


def _text_widget(placeholder: str = "") -> forms.TextInput:
    return forms.TextInput(attrs={
        "class":       _INPUT,
        "placeholder": placeholder,
        "autocomplete":"off",
    })


# ---------------------------------------------------------------------------
# FilterForm
# ---------------------------------------------------------------------------

class FilterForm(forms.Form):
    """
    Filter form for the workshop listing view.

    All fields are optional — omitting a field means "no filter applied"
    for that dimension. The only cross-field constraint is that
    from_date must not be after to_date when both are provided.
    """

    # ── Date range ────────────────────────────────────────────────
    from_date = forms.DateField(
        required=False,
        label="From",
        widget=_date_widget(),
        help_text="Start of date range (inclusive).",
    )
    to_date = forms.DateField(
        required=False,
        label="To",
        widget=_date_widget(),
        help_text="End of date range (inclusive).",
    )

    # ── Keyword search ────────────────────────────────────────────
    keyword = forms.CharField(
        required=False,
        max_length=120,
        label="Search",
        widget=_text_widget("Search by title, instructor, institute…"),
        help_text="Searches workshop title, instructor, and institute name.",
    )

    # ── Workshop type ─────────────────────────────────────────────
    workshop_type = forms.ModelChoiceField(
        queryset=WorkshopType.objects.all().order_by("workshoptype_name"),
        required=False,
        label="Workshop type",
        empty_label="All types",
        widget=_select_widget(),
    )

    # ── State ─────────────────────────────────────────────────────
    state = forms.ChoiceField(
        choices=[("", "All states")] + list(states),
        required=False,
        label="State",
        widget=_select_widget(),
    )

    # ── Status ────────────────────────────────────────────────────
    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
        required=False,
        label="Status",
        widget=_select_widget(),
    )

    # ── My workshops toggle ───────────────────────────────────────
    show_workshops = forms.BooleanField(
        required=False,
        label="My workshops only",
        help_text="Show only workshops you are associated with.",
        widget=forms.CheckboxInput(attrs={"class": _CHECK}),
    )

    # ── Sorting ───────────────────────────────────────────────────
    sort = forms.ChoiceField(
        choices=SORT_CHOICES,
        required=False,
        label="Sort by",
        widget=_select_widget(),
    )

    # ── Results per page ──────────────────────────────────────────
    per_page = forms.ChoiceField(
        choices=[("10", "10"), ("25", "25"), ("50", "50"), ("100", "100")],
        required=False,
        label="Results per page",
        initial="25",
        widget=_select_widget(),
    )

    # ----------------------------------------------------------------
    # __init__ — smart defaults & initial population
    # ----------------------------------------------------------------

    #: Keyword arguments that map directly to field names.
    #: Any key listed here is popped from kwargs and set as
    #: the field's initial value, so adding a new field only
    #: requires adding its name to this tuple.
    _INITIAL_KEYS = (
        "from_date",
        "to_date",
        "keyword",
        "workshop_type",
        "state",
        "status",
        "show_workshops",
        "sort",
        "per_page",
    )

    def __init__(self, *args, **kwargs):
        # Pop all recognised initial-value kwargs before calling super()
        # so Django's Form.__init__ never sees unknown keyword arguments.
        initials = {
            key: kwargs.pop(key, None)
            for key in self._INITIAL_KEYS
        }

        super().__init__(*args, **kwargs)

        # Apply smarter defaults when the caller did not pass a value.
        if initials["from_date"] is None:
            initials["from_date"] = date.today().replace(day=1)          # first day of current month
        if initials["to_date"] is None:
            initials["to_date"] = date.today() + timedelta(days=90)      # ~3 months ahead
        if initials["sort"] is None:
            initials["sort"] = "-date"                                    # Latest first
        if initials["per_page"] is None:
            initials["per_page"] = "25"

        # Apply all initials to their respective fields
        for field_name, value in initials.items():
            if field_name in self.fields and value is not None:
                self.fields[field_name].initial = value

    # ----------------------------------------------------------------
    # Field-level validation
    # ----------------------------------------------------------------

    def clean_from_date(self):
        value = self.cleaned_data.get("from_date")
        if value and value.year < 2000:
            raise ValidationError("Date must be on or after 01 Jan 2000.")
        return value

    def clean_to_date(self):
        value = self.cleaned_data.get("to_date")
        if value and value.year > date.today().year + 5:
            raise ValidationError("Date is too far in the future.")
        return value

    def clean_keyword(self):
        value = self.cleaned_data.get("keyword", "")
        # Strip surrounding whitespace and collapse internal runs
        return " ".join(value.split())

    # ----------------------------------------------------------------
    # Cross-field validation
    # ----------------------------------------------------------------

    def clean(self):
        cleaned = super().clean()
        from_date = cleaned.get("from_date")
        to_date   = cleaned.get("to_date")

        if from_date and to_date:
            if from_date > to_date:
                self.add_error(
                    "from_date",
                    ValidationError(
                        '"From" date (%(from)s) must not be after '
                        '"To" date (%(to)s).',
                        params={"from": from_date, "to": to_date},
                        code="date_order",
                    ),
                )

            max_range = timedelta(days=365 * 3)   # 3-year window cap
            if (to_date - from_date) > max_range:
                self.add_error(
                    "to_date",
                    ValidationError(
                        "Date range cannot exceed 3 years. "
                        "Please narrow your selection.",
                        code="range_too_large",
                    ),
                )

        return cleaned

    # ----------------------------------------------------------------
    # Convenience helpers
    # ----------------------------------------------------------------

    @property
    def has_active_filters(self) -> bool:
        """
        Returns True if any filter beyond the default sort/per_page
        has been set by the user. Useful in templates to show a
        'Clear filters' button only when needed.
        """
        if not self.is_valid():
            return False
        cd = self.cleaned_data
        return any([
            cd.get("keyword"),
            cd.get("workshop_type"),
            cd.get("state"),
            cd.get("status"),
            cd.get("show_workshops"),
        ])

    def as_query_dict(self) -> dict:
        """
        Return cleaned data as a flat dict suitable for building
        query strings or passing to a queryset filter helper.
        Non-truthy optional fields are omitted.
        """
        if not self.is_valid():
            return {}
        cd = self.cleaned_data
        return {k: v for k, v in cd.items() if v not in (None, "", False)}
