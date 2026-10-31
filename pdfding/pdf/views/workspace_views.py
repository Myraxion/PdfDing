from base import base_views
from base.base_views import PermissionLevel, check_workspace_permissions
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpRequest
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _
from django.views import View
from django_htmx.http import HttpResponseClientRefresh
from pdf.forms import (
    WorkspaceDescriptionForm,
    WorkspaceForm,
    WorkspaceNameForm,
    WorkspaceUserForm,
    WorkspaceUserRoleForm,
)
from pdf.models.collection_models import Collection
from pdf.models.workspace_models import Workspace, WorkspaceError, WorkspaceRoles
from pdf.services.pdf_services import check_object_access_allowed
from pdf.services.workspace_services import create_workspace, get_pdfs_of_workspace, get_size_of_all_workspace_pdfs


class BaseWorkspaceMixin:
    obj_name = 'workspace'


class CreateWorkspaceMixin(BaseWorkspaceMixin):
    form = WorkspaceForm
    template_name = 'create_workspace.html'
    permission_level = PermissionLevel.ALL

    def get_context_get(self, request: HttpRequest, __):
        """Get the context needed to be passed to the template containing the form for creating a workspace."""

        form = self.form

        context = {'form': form(profile=request.user.profile)}

        return context

    @classmethod
    def obj_save(cls, form: WorkspaceForm, request: HttpRequest, _):
        """Save the workspace based on the submitted form."""

        created_ws = create_workspace(
            name=form.cleaned_data['name'], description=form.cleaned_data['description'], creator=request.user
        )

        profile = request.user.profile
        profile.current_workspace_id = created_ws.id
        profile.current_collection_id = 'all'
        profile.save()


class WorkspaceMixin(BaseWorkspaceMixin):
    permission_level = PermissionLevel.OWNER

    @staticmethod
    @check_object_access_allowed
    def get_object(request: HttpRequest, ws_id: str) -> Workspace:
        """Get the current workspace."""

        user_profile = request.user.profile
        ws = user_profile.workspaces.get(id=ws_id)

        return ws


class EditWorkspaceMixin(WorkspaceMixin):
    fields_requiring_extra_processing = []

    @staticmethod
    def get_edit_form_dict():
        """Get the forms of the fields that can be edited as a dict."""

        form_dict = {
            'description': WorkspaceDescriptionForm,
            'name': WorkspaceNameForm,
        }

        return form_dict

    def get_edit_form_get(self, field_name: str, workspace: Workspace):
        """Get the form belonging to the specified field."""

        form_dict = self.get_edit_form_dict()

        initial_dict = {
            'name': {'name': workspace.name},
            'description': {'description': workspace.description},
        }

        form = form_dict[field_name](initial=initial_dict[field_name])

        return form


class Delete(WorkspaceMixin, base_views.BaseDelete):
    """View for deleting the workspace specified by its ID."""

    @check_workspace_permissions
    def get(self, request: HttpRequest, identifier: str):
        """Triggered by htmx. Display an inline form for deleting the workspace."""

        if request.htmx:
            workspace = self.get_object(request, identifier)

            return render(
                request,
                'partials/delete_workspace.html',
                {'workspace_id': identifier, 'workspace_name': workspace.name},
            )

        return redirect('pdf_overview')

    def pre_delete(self, obj: Workspace, request: HttpRequest):
        """Execute before deleting object."""

        if obj.personal_workspace:
            raise WorkspaceError('Personal workspaces cannot be deleted!')

    def post_delete(self, identifier: str, request: HttpRequest):
        """Execute after deleting object."""

        if identifier == request.user.profile.current_workspace_id:
            profile = request.user.profile
            profile.current_workspace_id = str(request.user.id)
            profile.current_collection_id = 'all'
            profile.save()


class Leave(WorkspaceMixin, View):
    """View for leaving a workspace."""

    def get(self, request: HttpRequest, identifier: str):  # pragma: no cover
        """Triggered by htmx. Display an inline form for deleting the workspace."""

        if request.htmx:
            workspace = self.get_object(request, identifier)

            return render(
                request,
                'partials/leave_workspace.html',
                {'workspace_id': identifier, 'workspace_name': workspace.name},
            )

        return redirect('pdf_overview')

    def post(self, request: HttpRequest, identifier: str):
        """Leave the workspace."""

        if request.htmx:
            workspace = self.get_object(request, identifier)
            user = request.user

            try:
                workspace.remove_workspace_user(user)
            except WorkspaceError as exception:  # pragma: no cover
                messages.warning(request, str(exception))

            return HttpResponseClientRefresh()

        return redirect('pdf_overview')  # pragma: no cover


class RemoveUser(WorkspaceMixin, View):
    """View for removing a user from a workspace."""

    @check_workspace_permissions
    def get(self, request: HttpRequest, identifier: str, user_id: str):  # pragma: no cover
        """Triggered by htmx. Display an inline form for removing a user from the workspace."""

        if request.htmx:
            user = User.objects.get(id=user_id)

            return render(
                request,
                'partials/remove_workspace_user.html',
                {'workspace_id': identifier, 'user_id': user_id, 'user_email': user.email},
            )

        return redirect('pdf_overview')

    @check_workspace_permissions
    def post(self, request: HttpRequest, identifier: str, user_id: str):
        """Remove user from the workspace."""

        if request.htmx:
            workspace = self.get_object(request, identifier)
            user = User.objects.get(id=user_id)

            try:
                workspace.remove_workspace_user(user)
                messages.info(request, _('Successfully remove user from workspace.'))
            except WorkspaceError as exception:  # pragma: no cover
                messages.warning(request, str(exception))
            except ObjectDoesNotExist:  # pragma: no cover
                pass

            return HttpResponseClientRefresh()

        return redirect('pdf_overview')  # pragma: no cover


class ChangeUserRole(WorkspaceMixin, View):
    """View for changing the role of a user."""

    @check_workspace_permissions
    def get(self, request: HttpRequest, identifier: str, user_id: str):  # pragma: no cover
        if request.htmx:
            user = User.objects.get(id=user_id)

            return render(
                request,
                'partials/adjust_user_role.html',
                {
                    'workspace_id': identifier,
                    'user_id': user_id,
                    'user_email': user.email,
                    'form': WorkspaceUserRoleForm(),
                },
            )

        return redirect('pdf_overview')

    @check_workspace_permissions
    def post(self, request: HttpRequest, identifier: str, user_id: str):
        """Change the role of a user from the workspace."""

        workspace = self.get_object(request, identifier)
        user = User.objects.get(id=user_id)

        if workspace.personal_workspace:
            messages.warning(request, _('Action not possible for personal workspaces!'))
        elif workspace.is_owner(user) and workspace.owners.count() == 1:
            messages.warning(request, _('Action not possible as there is only one workspace owner!'))
        else:
            role = WorkspaceRoles(request.POST.get('role'))
            workspace_user = workspace.workspaceuser_set.get(user__id=user.id)
            workspace_user.role = role
            workspace_user.save()

            messages.info(request, _('Successfully adjusted user role.'))

        return redirect('workspace_users')  # pragma: no cover


def check_workspace_owner_redirect(some_function):
    """Return a Http404 exception if user is not the owner of a workspace."""

    def inner(*args, **kwargs):
        request = args[1]  # first argument is self
        ws = request.user.profile.current_workspace

        if not ws.is_owner(request.user):
            return redirect('pdf_overview')

        return some_function(*args, **kwargs)

    return inner


class Create(CreateWorkspaceMixin, base_views.BaseAdd):
    """View for creating new workspaces."""


class Details(WorkspaceMixin, base_views.BaseDetails):
    """View for displaying the details page of a workspace."""

    # returns the current workspace, needs to be adjusted in the future
    def get(self, request: HttpRequest, identifier: str | None = None):  # pragma: no cover
        """Display the details page."""

        workspace = request.user.profile.current_workspace

        ws_pdfs = get_pdfs_of_workspace(workspace)

        context = {
            'workspace': workspace,
            'number_of_pdfs': ws_pdfs.count(),
            'sidebar_name': 'includes/workspace_sidebar.html',
            'page': 'workspace_details',
            'pdfs_total_size': get_size_of_all_workspace_pdfs(workspace),
        }

        return render(request, 'workspace_details.html', context)


class Users(WorkspaceMixin, base_views.BaseDetails):
    """View for displaying the users page of a workspace."""

    # returns the current workspace, needs to be adjusted in the future
    @check_workspace_owner_redirect
    def get(self, request: HttpRequest, identifier: str | None = None):  # pragma: no cover
        """Display the details page."""

        ws = request.user.profile.current_workspace

        context = {
            'workspace': ws,
            'sidebar_name': 'includes/workspace_sidebar.html',
            'page': 'workspace_users',
            'form': WorkspaceUserForm(),
        }

        return render(request, 'workspace_users.html', context)


class AddUser(WorkspaceMixin, base_views.BaseDetails):
    """View for adding a user to a workspace."""

    @check_workspace_permissions
    def post(self, request: HttpRequest):
        workspace = request.user.profile.current_workspace

        try:
            email = request.POST.get('email')
            user = User.objects.get(email=email)
            role = WorkspaceRoles(request.POST.get('role'))

            workspace.add_user_to_workspace(user, role)
            messages.info(request, _('Added user to workspace.'))

        except ObjectDoesNotExist:
            messages.warning(request, _('Specified user does not exist!'))
        except WorkspaceError as workspace_error:
            messages.info(request, str(workspace_error))

        return redirect('workspace_users')


class CollectionDetails(WorkspaceMixin, base_views.BaseDetails):
    """View for displaying the collections page of a workspace."""

    @check_workspace_owner_redirect
    def get(self, request: HttpRequest, identifier: str):
        """Display the collection page."""

        workspace = request.user.profile.current_workspace
        collection = self.get_collection(request, identifier=identifier)
        context = {
            'workspace': workspace,
            'current_collection_id': identifier,
            'collection': collection,
            'current_collection_name': collection.name,
            'sidebar_name': 'includes/workspace_sidebar.html',
            'page': 'collection_details',
        }

        return render(request, 'collection_details.html', context)

    @staticmethod
    @check_object_access_allowed
    def get_collection(request: HttpRequest, identifier: str) -> Collection:
        collection = request.user.profile.collections.get(id=identifier)

        return collection


class Edit(EditWorkspaceMixin, base_views.BaseDetailsEdit):
    """
    The view for editing a workspace's name and description. The field, that is to be changed, is specified by the
    'field' argument.
    """
