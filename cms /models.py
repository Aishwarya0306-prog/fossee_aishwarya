import os
import uuid
import mimetypes

from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

ALLOWED_STATIC_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg',
    '.css', '.js', '.ico', '.woff', '.woff2', '.ttf', '.eot',
}

ALLOWED_MEDIA_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg',
    '.mp4', '.webm', '.ogg', '.mp3', '.wav',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
}

MAX_STATIC_FILE_SIZE = 10 * 1024 * 1024   # 10 MB
MAX_MEDIA_FILE_SIZE  = 50 * 1024 * 1024   # 50 MB

slug_validator = RegexValidator(
    regex=r'^[a-z0-9]+(?:-[a-z0-9]+)*$',
    message='Only lowercase letters, numbers, and hyphens are allowed.',
)


def validate_file_extension(value, allowed: set):
    ext = os.path.splitext(value.name)[1].lower()
    if ext not in allowed:
        raise ValidationError(
            f'Unsupported file type "{ext}". '
            f'Allowed types: {", ".join(sorted(allowed))}'
        )


def validate_file_size(value, max_size: int):
    if value.size > max_size:
        raise ValidationError(
            f'File too large: {value.size / 1024 / 1024:.1f} MB. '
            f'Maximum allowed: {max_size / 1024 / 1024:.0f} MB.'
        )


def validate_safe_filename(value: str):
    """Prevent path traversal and shell-injection characters."""
    forbidden = set('/\\<>:"|?*\x00')
    if any(c in forbidden for c in value):
        raise ValidationError('Filename contains forbidden characters.')
    if value.startswith('.') or '..' in value:
        raise ValidationError('Filename must not start with a dot or contain "..".')


def validate_static_filename_unique(value: str):
    path = os.path.join('workshop_app', 'static', value)
    if os.path.exists(path):
        raise ValidationError(
            'A static file with that name already exists. '
            'Choose a unique name or use foldername/filename to place it in a subfolder.'
        )


def get_static_upload_path(instance, _):
    return f'static/cms/{instance.filename}'


def get_media_upload_path(instance, filename):
    ext  = os.path.splitext(filename)[1].lower()
    safe = f'{uuid.uuid4().hex}{ext}'
    return f'media/cms/{instance.media_type}/{safe}'


# ---------------------------------------------------------------------------
# Timestamp mixin
# ---------------------------------------------------------------------------

class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

class Nav(TimeStampedModel):
    name     = models.CharField(max_length=60)
    link     = models.CharField(max_length=255)
    position = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(999)],
        help_text='Display order (lower = first).',
    )
    active   = models.BooleanField(default=True)
    icon     = models.CharField(
        max_length=80, blank=True,
        help_text='Optional CSS icon class (e.g. "fa fa-home").',
    )
    open_in_new_tab = models.BooleanField(default=False)

    class Meta:
        ordering = ['position', 'name']
        verbose_name = 'Navigation item'
        verbose_name_plural = 'Navigation items'

    def __str__(self):
        return self.name


class SubNav(TimeStampedModel):
    nav      = models.ForeignKey(Nav, on_delete=models.CASCADE, related_name='sub_items')
    name     = models.CharField(max_length=60)
    link     = models.CharField(max_length=255)
    position = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(999)],
        help_text='Display order within the parent nav item.',
    )
    active   = models.BooleanField(default=True)
    icon     = models.CharField(max_length=80, blank=True)
    open_in_new_tab = models.BooleanField(default=False)

    class Meta:
        ordering = ['nav', 'position', 'name']
        verbose_name = 'Sub-navigation item'
        verbose_name_plural = 'Sub-navigation items'

    def __str__(self):
        return f'{self.nav.name} → {self.name}'


# ---------------------------------------------------------------------------
# SEO metadata (reusable via OneToOne on Page / Blog)
# ---------------------------------------------------------------------------

class SEOMeta(TimeStampedModel):
    meta_title       = models.CharField(max_length=70, blank=True)
    meta_description = models.CharField(max_length=160, blank=True)
    meta_keywords    = models.CharField(
        max_length=255, blank=True,
        help_text='Comma-separated keywords.',
    )
    og_title         = models.CharField('OG title',       max_length=95,  blank=True)
    og_description   = models.CharField('OG description', max_length=200, blank=True)
    og_image         = models.ImageField(
        'OG image', upload_to='media/cms/og/', blank=True, null=True,
        help_text='Recommended size: 1200 × 630 px.',
    )
    canonical_url    = models.URLField(blank=True, help_text='Leave blank to use the page URL.')
    no_index         = models.BooleanField(
        default=False,
        help_text='Add "noindex" to this page\'s robots meta tag.',
    )

    class Meta:
        verbose_name = 'SEO metadata'
        verbose_name_plural = 'SEO metadata'

    def __str__(self):
        return self.meta_title or '(no title)'


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

class Page(TimeStampedModel):
    permalink  = models.CharField(
        max_length=100, unique=True,
        validators=[slug_validator],
        help_text='URL slug — lowercase letters, numbers, and hyphens only.',
    )
    title      = models.CharField(max_length=100)
    imports    = models.TextField(
        blank=True, null=True,
        help_text=(
            'External CSS / JS imports placed inside &lt;head&gt;. '
            'Bootstrap 4 and jQuery are already included.'
        ),
    )
    content    = models.TextField(help_text='HTML body of the page.')
    template   = models.CharField(
        max_length=100, default='cms/default.html',
        help_text='Django template path to use when rendering this page.',
    )
    active     = models.BooleanField(default=True)
    pub_date   = models.DateTimeField('date published', default=timezone.now)
    seo        = models.OneToOneField(
        SEOMeta, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='page',
    )

    class Meta:
        ordering = ['title']
        verbose_name = 'Page'
        verbose_name_plural = 'Pages'

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return f'/{self.permalink}/'


# ---------------------------------------------------------------------------
# Blog
# ---------------------------------------------------------------------------

class Tag(TimeStampedModel):
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=60, unique=True, blank=True)

    class Meta:
        ordering = ['name']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class BlogPost(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT     = 'draft',     'Draft'
        REVIEW    = 'review',    'In review'
        PUBLISHED = 'published', 'Published'
        ARCHIVED  = 'archived',  'Archived'

    title        = models.CharField(max_length=200)
    slug         = models.SlugField(max_length=220, unique=True, blank=True)
    author       = models.CharField(max_length=100, blank=True)
    excerpt      = models.TextField(
        max_length=500, blank=True,
        help_text='Short summary shown in listing views (max 500 chars).',
    )
    content      = models.TextField(help_text='Full HTML / Markdown content of the post.')
    cover_image  = models.ImageField(
        upload_to='media/cms/blog/covers/', blank=True, null=True,
    )
    status       = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT,
        db_index=True,
    )
    tags         = models.ManyToManyField(Tag, blank=True, related_name='posts')
    featured     = models.BooleanField(default=False)
    allow_comments = models.BooleanField(default=True)
    pub_date     = models.DateTimeField('publish date', null=True, blank=True)
    seo          = models.OneToOneField(
        SEOMeta, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='blog_post',
    )

    class Meta:
        ordering = ['-pub_date', '-created_at']
        verbose_name = 'Blog post'
        verbose_name_plural = 'Blog posts'

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        if self.status == self.Status.PUBLISHED and not self.pub_date:
            self.pub_date = timezone.now()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return f'/blog/{self.slug}/'

    @property
    def is_published(self):
        return self.status == self.Status.PUBLISHED


# ---------------------------------------------------------------------------
# Media library
# ---------------------------------------------------------------------------

class MediaFile(TimeStampedModel):
    class MediaType(models.TextChoices):
        IMAGE    = 'image',    'Image'
        VIDEO    = 'video',    'Video'
        AUDIO    = 'audio',    'Audio'
        DOCUMENT = 'document', 'Document'
        OTHER    = 'other',    'Other'

    title      = models.CharField(max_length=150)
    media_type = models.CharField(
        max_length=10, choices=MediaType.choices, default=MediaType.IMAGE,
        db_index=True,
    )
    file       = models.FileField(
        upload_to=get_media_upload_path,
        storage=FileSystemStorage(location='workshop_app', base_url='/'),
        help_text='Allowed types: images, video, audio, PDF, Office docs (max 50 MB).',
    )
    alt_text   = models.CharField(
        max_length=200, blank=True,
        help_text='Descriptive text for screen readers / SEO.',
    )
    caption    = models.CharField(max_length=300, blank=True)
    file_size  = models.PositiveIntegerField(editable=False, null=True)
    mime_type  = models.CharField(max_length=100, editable=False, blank=True)
    active     = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Media file'
        verbose_name_plural = 'Media files'

    def clean(self):
        if self.file:
            validate_file_extension(self.file, ALLOWED_MEDIA_EXTENSIONS)
            validate_file_size(self.file, MAX_MEDIA_FILE_SIZE)

    def save(self, *args, **kwargs):
        if self.file:
            self.file_size = self.file.size
            mime, _ = mimetypes.guess_type(self.file.name)
            self.mime_type = mime or ''
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

class StaticFile(TimeStampedModel):
    filename = models.CharField(
        max_length=120,
        unique=True,
        validators=[validate_safe_filename, validate_static_filename_unique],
        help_text=(
            'Unique filename for this asset. '
            'Use foldername/filename to place it inside a subfolder. '
            'The file will be accessible at /static/cms/&lt;filename&gt;.'
        ),
    )
    file = models.FileField(
        upload_to=get_static_upload_path,
        storage=FileSystemStorage(location='workshop_app', base_url='/'),
        help_text='Static asset: image, CSS, JS, font, etc. (max 10 MB).',
    )
    description = models.CharField(max_length=200, blank=True)
    file_size   = models.PositiveIntegerField(editable=False, null=True)
    mime_type   = models.CharField(max_length=100, editable=False, blank=True)
    active      = models.BooleanField(default=True)

    class Meta:
        ordering = ['filename']
        verbose_name = 'Static file'
        verbose_name_plural = 'Static files'

    def clean(self):
        if self.file:
            validate_file_extension(self.file, ALLOWED_STATIC_EXTENSIONS)
            validate_file_size(self.file, MAX_STATIC_FILE_SIZE)

    def save(self, *args, **kwargs):
        if self.file:
            self.file_size = self.file.size
            mime, _ = mimetypes.guess_type(self.file.name)
            self.mime_type = mime or ''
        super().save(*args, **kwargs)

    def __str__(self):
        return self.filename
