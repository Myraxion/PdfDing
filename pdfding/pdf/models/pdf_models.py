import re
from datetime import datetime, timezone
from uuid import uuid4

from core.settings import MEDIA_ROOT
from django.contrib.humanize.templatetags.humanize import naturaltime
from django.db import models
from django.db.models import DateTimeField
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from pdf.models.collection_models import Collection
from pdf.models.helpers import get_collection_dir
from pdf.models.tag_models import Tag
from pdf.models.workspace_models import Workspace


def get_file_path(instance, _) -> str:
    """
    Get the file path for a PDF inside the media root based on the pdf name. File paths are
    workspace_id/collection_name/some/dir/name.pdf. This function will also replace any "/" in the
    pdf name and will make  sure there are no duplicate file names.
    """

    # replace any space char with _
    file_name = re.sub(r'\s+', '_', instance.name)
    file_name = file_name.replace('/', '_')
    file_name = str.lower(file_name)
    # remove non alphanumerical characters
    file_name = slugify(file_name, allow_unicode=True)

    sub_dir = instance.file_directory

    # make sure file name is not empty
    if not file_name:
        file_name = 'pdf'

    file_name = f'{file_name}.pdf'

    if sub_dir:
        sub_dir.strip()
        file_path = '/'.join(['pdf', sub_dir, file_name])
    else:
        file_path = '/'.join(['pdf', file_name])

    file_path = f'{get_collection_dir(instance.collection)}/{file_path}'
    existing_pdf = Pdf.objects.filter(file=file_path).first()

    # make sure there each file path is unique
    if existing_pdf and str(existing_pdf.id) != str(instance.id):
        file_path = file_path.replace('.pdf', f'_{str(uuid4())[:8]}.pdf')

    return file_path


def delete_empty_dirs_after_rename_or_delete(
    pdf_current_file_name: str, workspace_id: str, collection_name: str
) -> None:
    """
    Delete empty directories in the users media/pdf directory that appear as a result of renaming or deleting pdfs.
    """

    current_path = MEDIA_ROOT / pdf_current_file_name

    pdf_current_file_name_adjusted = pdf_current_file_name.replace(f'{workspace_id}/{collection_name.lower()}/pdf/', '')

    for __ in pdf_current_file_name_adjusted.split('/'):
        current_parent_path = current_path.parent
        sub_paths = [sub_path for sub_path in current_parent_path.iterdir()]

        if not sub_paths:
            current_parent_path.rmdir()
            current_path = current_parent_path
        else:
            break


def get_thumbnail_path(instance, _) -> str:
    """Get the file path for the thumbnail of a PDF."""

    file_name = f'thumbnails/{instance.id}.png'
    file_path = f'{get_collection_dir(instance.collection)}/{file_name}'

    return file_path


def get_preview_path(instance, _) -> str:
    """Get the file path for the preview of a PDF."""

    file_name = f'previews/{instance.id}.png'
    file_path = f'{get_collection_dir(instance.collection)}/{file_name}'

    return file_path


def convert_to_natural_age(creation_date: DateTimeField) -> str:
    """Convert the creation date into a natural age, e.g: 2 minutes, 1 hour,  2 months, etc"""

    natural_time = naturaltime(creation_date)

    if ',' in natural_time:
        natural_time = natural_time.split(sep=', ')[0]
    else:
        natural_time = natural_time.replace(' ago', '')

    # naturaltime will include space characters that will cause failed unit tests
    # splitting and joining fixes that
    return ' '.join(natural_time.split())


class Pdf(models.Model):
    """Model for the pdf files."""

    archived = models.BooleanField(default=False)
    creation_date = models.DateTimeField(blank=False, editable=False, auto_now_add=True)
    collection = models.ForeignKey(Collection, on_delete=models.CASCADE, blank=False)
    current_page = models.IntegerField(default=1)  # deprecated
    description = models.TextField(blank=True, help_text=_('Optional'), default='')
    file_directory = models.CharField(
        max_length=120,
        default='',
        blank=True,
        help_text=_('Optional, save file in a sub directory of the pdf directory, e.g: important/pdfs'),
    )
    file = models.FileField(upload_to=get_file_path, max_length=500, blank=False)
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    last_viewed_date = models.DateTimeField(
        blank=False, editable=False, default=datetime(2000, 1, 1, tzinfo=timezone.utc)
    )  # # deprecated
    name = models.CharField(max_length=512, blank=False)
    number_of_pages = models.IntegerField(default=-1)
    preview = models.FileField(upload_to=get_preview_path, null=True, blank=False)
    revision = models.IntegerField(default=0)
    starred = models.BooleanField(default=False)
    tags = models.ManyToManyField(Tag, blank=True)
    thumbnail = models.FileField(upload_to=get_thumbnail_path, null=True, blank=False)
    views = models.IntegerField(default=0)

    def __str__(self) -> str:
        return self.name  # pragma: no cover

    def delete(self, *args, **kwargs) -> None:
        # clean up file directory if needed
        file_directory = self.file_directory
        file_name = self.file.name
        collection_name = self.collection.name
        workspace_id = self.workspace.id

        # delete pdf, thumbnail and preview files
        for file in [self.file, self.preview, self.thumbnail]:
            try:
                file.close()
                file.delete()
            except FileNotFoundError:  # pragma: no cover
                pass

        super().delete(*args, **kwargs)

        if file_directory:
            delete_empty_dirs_after_rename_or_delete(file_name, workspace_id, collection_name)

    @property
    def natural_age(self) -> str:  # pragma: no cover
        """
        Get the natural age of a file. This converts the creation date to a natural age,
        e.g: 2 minutes, 1 hour,  2 months, etc
        """

        return convert_to_natural_age(self.creation_date)

    @property
    def workspace(self) -> Workspace:
        """Get the workspace the PDF belongs to."""

        return self.collection.workspace


class Metadata(models.Model):
    """Model for the PDF metadata"""

    class ReferenceType(models.TextChoices):
        ARTICLE = 'Article'
        BOOK = 'Book'
        BOOKLET = 'Booklet'
        CONFERENCE = 'Conference'
        INBOOK = 'Inbook'
        INCOLLECTION = 'Incollection'
        INPROCEEDINGS = 'Inproceedings'
        MANUAL = 'Manual'
        MASTERTHESIS = 'Masterthesis'
        MISC = 'Misc'
        PHDTHESIS = 'Phdthesis'
        PROCEEDINGS = 'Proceedings'
        TECHREPORT = 'Techreport'
        UNPUBLISHED = 'Unpublished'

    author = models.CharField(max_length=256, blank=True)
    abstract = models.TextField(default='', blank=True, help_text=_('Optional'))
    doi = models.CharField(max_length=128, blank=True)
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    journal = models.CharField(max_length=128, blank=True)
    keywords = models.TextField(blank=True, help_text=_('Optional'))
    number = models.CharField(max_length=16, blank=True)
    pages = models.CharField(max_length=32, blank=True)
    reference_type = models.CharField(choices=ReferenceType.choices, max_length=32, blank=True)
    pdf = models.OneToOneField(Pdf, on_delete=models.CASCADE, blank=False)
    publisher = models.CharField(max_length=64, blank=True)
    title = models.CharField(max_length=512, blank=False)
    url = models.URLField(max_length=256, blank=True)
    volume = models.CharField(max_length=16, blank=True)
    year = models.CharField(max_length=16, blank=True)


class PdfAnnotation(models.Model):
    """Model for the base pdf annotation"""

    creation_date = models.DateTimeField(blank=False, editable=False)
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    page = models.IntegerField(blank=False)
    pdf = models.ForeignKey(Pdf, on_delete=models.CASCADE, blank=False)
    text = models.TextField(blank=False)

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return self.text  # pragma: no cover

    @property
    def natural_age(self) -> str:  # pragma: no cover
        """
        Get the natural age of a file. This converts the creation date to a natural age,
        e.g: 2 minutes, 1 hour,  2 months, etc
        """

        return convert_to_natural_age(self.creation_date)


class PdfComment(PdfAnnotation):
    """Model for the pdf comments."""


class PdfHighlight(PdfAnnotation):
    """Model for the pdf highlights."""
