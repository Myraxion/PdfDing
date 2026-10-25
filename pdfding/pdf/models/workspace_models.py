from shutil import rmtree
from uuid import uuid4

from django.contrib.auth.models import User
from django.db import models
from django.utils.translation import gettext_lazy as _
from pdf.models.helpers import get_workspace_path


def get_uuid4_str() -> str:
    return str(uuid4())


class WorkspaceError(Exception):
    """Exceptions for workspace related problems"""


class WorkspaceRoles(models.TextChoices):
    GUEST = 'Guest'
    MEMBER = 'Member'
    OWNER = 'Owner'


class Workspace(models.Model):
    """The workspace model. Workspaces are the top level hierarchy."""

    id = models.CharField(primary_key=True, default=get_uuid4_str, max_length=36, editable=False, blank=False)
    creation_date = models.DateTimeField(blank=False, editable=False, auto_now_add=True)
    description = models.TextField(default='', blank=True)
    name = models.CharField(max_length=50, blank=False)
    personal_workspace = models.BooleanField(blank=False, editable=False)

    def __str__(self):  # pragma: no cover
        return str(self.name)

    def delete(self, *args, **kwargs) -> None:
        """
        Override default delete method so that workspace directory gets deleted after the workspace is deleted.
        """

        ws_path = get_workspace_path(self)

        # adjust current workspace for all workspace users if necessary
        for user in self.users:
            if user.profile.current_workspace_id == self.id:
                # set to personal workspace
                user.profile.current_workspace_id = user.id
                user.profile.save()

        super().delete(*args, **kwargs)

        try:
            rmtree(ws_path)
        except Exception:  # pragma: no cover # nosec B110
            pass

    @property
    def users(self) -> models.QuerySet[User]:
        """Get the users of the workspace."""

        return User.objects.filter(workspaceuser__in=self.workspaceuser_set.all())

    @property
    def workspace_users_ordered(self) -> models.QuerySet:
        """Get the users of the workspace."""

        workspace_users = self.workspaceuser_set.all()
        workspace_users = workspace_users.order_by(
            models.Case(
                models.When(role="Owner", then=models.Value(0)),
                models.When(role="Member", then=models.Value(2)),
                models.When(role="Guest", then=models.Value(3)),
                default=models.Value(4),
            ),
            'user__email',
        )

        return workspace_users

    @property
    def owners(self) -> models.QuerySet[User]:
        """Get the owners of the workspace."""

        owners = self.workspaceuser_set.filter(role=WorkspaceRoles.OWNER)
        owner_users = User.objects.filter(workspaceuser__in=owners)

        return owner_users

    @property
    def members(self) -> models.QuerySet[User]:
        """Get the members of the workspace."""

        members = self.workspaceuser_set.filter(role=WorkspaceRoles.MEMBER)
        member_users = User.objects.filter(workspaceuser__in=members)

        return member_users

    @property
    def guests(self) -> models.QuerySet[User]:
        """Get the guests of the workspace."""

        guests = self.workspaceuser_set.filter(role=WorkspaceRoles.GUEST)
        guest_users = User.objects.filter(workspaceuser__in=guests)

        return guest_users

    @property
    def collections(self) -> models.QuerySet:
        """Get the collections of the workspace."""

        return self.collection_set.all()

    def add_user_to_workspace(self, user: User, role: WorkspaceRoles) -> None:
        """Add a user to the workspace."""

        if self.personal_workspace:
            raise WorkspaceError(_('Cannot add other users to personal workspaces!'))
        elif user in self.users:
            raise WorkspaceError(_('User is already a user of the workspace!'))
        else:
            WorkspaceUser.objects.create(workspace=self, user=user, role=role)


class WorkspaceUser(models.Model):
    """
    The workspace user model. It is linked to both a workspace and a user profile.
    Workspace users can have the roles owner, member and guest.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False, blank=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, blank=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, blank=False)
    role = models.CharField(choices=WorkspaceRoles.choices, max_length=6, blank=False)
