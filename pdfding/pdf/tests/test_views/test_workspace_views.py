from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from pdf.forms import WorkspaceDescriptionForm, WorkspaceForm, WorkspaceNameForm
from pdf.models.pdf_models import Pdf
from pdf.models.workspace_models import WorkspaceError, WorkspaceRoles, WorkspaceUser
from pdf.services.workspace_services import create_workspace
from pdf.views import workspace_views
from users.service import get_demo_pdf


class WorkspaceTestCase(TestCase):
    username = 'user'
    password = '12345'

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username=self.username, password=self.password, email='a@a.com')
        self.client.login(username=self.username, password=self.password)


class TestCreateWorkspaceMixing(WorkspaceTestCase):
    @patch('pdf.views.workspace_views.CreateWorkspaceMixin.form')
    def test_get_context_get(self, mock_add_form):
        # do a dummy request so we can get a request object
        response = self.client.get(reverse('pdf_overview'))

        create_ws_mixin = workspace_views.CreateWorkspaceMixin()
        generated_context = create_ws_mixin.get_context_get(response.wsgi_request, None)

        mock_add_form.assert_called_once_with(profile=self.user.profile)
        self.assertIsInstance(generated_context['form'], MagicMock)

    def test_obj_save(self):
        self.assertEqual(self.user.profile.current_workspace_id, str(self.user.id))
        # do a dummy request so we can get a request object
        response = self.client.get(reverse('pdf_overview'))
        form = WorkspaceForm(
            data={
                'name': 'some_workspace',
                'description': 'some_description',
            },
            profile=self.user.profile,
        )

        # need to call this, so cleaned_data can be accessed
        form.is_valid()

        workspace_views.CreateWorkspaceMixin.obj_save(form, response.wsgi_request, None)

        changed_user = User.objects.get(id=self.user.id)
        created_ws = changed_user.profile.current_workspace

        self.assertNotEqual(str(self.user.id), changed_user.profile.current_workspace_id)
        self.assertEqual(created_ws.name, 'some_workspace')
        self.assertEqual(created_ws.description, 'some_description')
        self.assertEqual('all', changed_user.profile.current_collection_id)
        self.assertFalse(created_ws.personal_workspace)


class TestWorkspaceMixin(WorkspaceTestCase):
    def test_get_object(self):
        # we need to create a request so get_pdf can access the user profile
        response = self.client.get(reverse('pdf_overview'))

        ws = self.user.profile.current_workspace

        assert ws == workspace_views.WorkspaceMixin.get_object(response.wsgi_request, ws.id)


class TestWorkspaceDetails(WorkspaceTestCase):
    def test_details_get(self):
        default_collection = self.user.profile.current_collection
        Pdf.objects.create(name='pdf_1', collection=default_collection, file=get_demo_pdf())
        Pdf.objects.create(name='pdf_2', collection=default_collection, file=get_demo_pdf())
        response = self.client.get(reverse('workspace_details', kwargs={'identifier': default_collection.id}))

        self.assertTemplateUsed(response, 'workspace_details.html')
        assert response.context['workspace'] == self.user.profile.current_workspace
        assert response.context['number_of_pdfs'] == 2
        assert response.context['sidebar_name'] == 'includes/workspace_sidebar.html'
        assert response.context['page'] == 'workspace_details'
        # size of two demo files
        assert response.context['pdfs_total_size'] == '58.9 KB'


class TestCollectionDetails(WorkspaceTestCase):
    def test_get(self):
        default_collection = self.user.profile.current_collection

        response = self.client.get(reverse('collection_details', kwargs={'identifier': default_collection.id}))

        self.assertTemplateUsed(response, 'collection_details.html')

        assert response.context['workspace'] == self.user.profile.current_workspace
        assert response.context['collection'] == default_collection
        assert response.context['current_collection_id'] == default_collection.id
        assert response.context['current_collection_name'] == default_collection.name
        assert response.context['sidebar_name'] == 'includes/workspace_sidebar.html'
        assert response.context['page'] == 'collection_details'


class TestEditWorkspaceMixin(WorkspaceTestCase):
    def test_get_edit_form_get(self):
        ws = self.user.profile.current_workspace
        edit_workspace_mixin_object = workspace_views.EditWorkspaceMixin()

        for field, form_class, field_value in zip(
            ['name', 'description'],
            [WorkspaceNameForm, WorkspaceDescriptionForm],
            ['Personal', 'Personal Workspace'],
        ):
            form = edit_workspace_mixin_object.get_edit_form_get(field, ws)
            self.assertIsInstance(form, form_class)
            self.assertEqual(form.initial, {field: field_value})


class TestDelete(WorkspaceTestCase):
    def test_delete_get_no_htmx(self):
        created_ws = create_workspace('created_ws', self.user)

        response = self.client.get(reverse('delete_workspace', kwargs={'identifier': created_ws.id}))
        self.assertRedirects(response, reverse('pdf_overview'), status_code=302)

    def test_delete_get(self):
        created_ws = create_workspace('created_ws', self.user)
        headers = {'HTTP_HX-Request': 'true'}

        response = self.client.get(reverse('delete_workspace', kwargs={'identifier': created_ws.id}), **headers)

        self.assertEqual(response.context['workspace_name'], 'created_ws')
        self.assertEqual(response.context['workspace_id'], str(created_ws.id))
        self.assertTemplateUsed(response, 'partials/delete_workspace.html')

    def test_pre_delete(self):
        headers = {'HTTP_HX-Request': 'true'}

        with pytest.raises(WorkspaceError, match='Personal workspaces cannot be deleted!'):
            self.client.delete(
                reverse('delete_workspace', kwargs={'identifier': self.user.profile.current_workspace.id}), **headers
            )

    def test_post_delete_current_ws_adjusted(self):
        created_ws = create_workspace('created_ws', self.user)
        headers = {'HTTP_HX-Request': 'true'}

        profile = self.user.profile
        profile.current_workspace_id = created_ws.id
        profile.current_collection_id = created_ws.id
        profile.save()

        changed_user = User.objects.get(id=self.user.id)
        assert changed_user.profile.current_workspace_id == created_ws.id
        assert changed_user.profile.current_collection_id != 'all'

        self.client.delete(reverse('delete_workspace', kwargs={'identifier': created_ws.id}), **headers)

        changed_user = User.objects.get(id=self.user.id)
        assert changed_user.profile.current_workspace_id == str(changed_user.id)
        assert changed_user.profile.current_collection_id == 'all'


class TestAddUser(WorkspaceTestCase):
    def test_add_user(self):
        created_ws = create_workspace('created_ws', self.user)
        self.user.profile.current_workspace_id = created_ws.id
        self.user.profile.save()

        some_user = User.objects.create_user(username='bla', password=self.password, email='a@b.com')

        assert not created_ws.members.filter(id=some_user.id).exists()

        response = self.client.post(
            reverse('workspace_add_user'),
            data={'email': some_user.email, 'role': 'Member'},
        )

        self.assertRedirects(response, reverse('workspace_users'), status_code=302)
        assert created_ws.members.filter(id=some_user.id).exists()

    def test_add_user_personal_ws(self):
        some_user = User.objects.create_user(username='bla', password=self.password, email='a@b.com')
        response = self.client.post(
            reverse('workspace_add_user'),
            data={'email': some_user.email, 'role': 'Member'},
            follow=True,
        )
        message = list(response.context['messages'])[0]

        assert message.message == 'Cannot add other users to personal workspaces!'

    def test_add_user_already_part_of_workspace(self):
        created_ws = create_workspace('created_ws', self.user)
        self.user.profile.current_workspace_id = created_ws.id
        self.user.profile.save()

        some_user = User.objects.create_user(username='bla', password=self.password, email='a@b.com')
        WorkspaceUser.objects.create(workspace=created_ws, user=some_user, role=WorkspaceRoles.MEMBER)

        response = self.client.post(
            reverse('workspace_add_user'),
            data={'email': some_user.email, 'role': 'Member'},
            follow=True,
        )
        message = list(response.context['messages'])[0]

        assert message.message == 'User is already a user of the workspace!'

    def test_add_user_user_not_existing(self):
        response = self.client.post(
            reverse('workspace_add_user'),
            data={'email': 'a@b.com', 'role': 'Member'},
            follow=True,
        )

        message = list(response.context['messages'])[0]

        assert message.message == 'Specified user does not exist!'

    def test_add_user_not_owner(self):
        other_user = User.objects.create_user(username='bla', password=self.password, email='a@b.com')
        other_user_ws = create_workspace('created_ws', other_user)
        other_user_ws.add_user_to_workspace(self.user, WorkspaceRoles.MEMBER)

        self.user.profile.current_workspace_id = other_user_ws.id
        self.user.profile.save()

        further_user = User.objects.create_user(username='blaaa', password=self.password, email='a@c.com')
        response = self.client.post(
            reverse('workspace_add_user'),
            data={'email': further_user.email, 'role': 'Member'},
        )

        assert response.status_code == 404


class Other(WorkspaceTestCase):
    def setUp(self):
        super().setUp()

        self.other_user = User.objects.create_user(username='other_user', password='pw')
        self.other_ws = create_workspace('other_ws', self.other_user)
        self.other_user.profile.current_workspace_id = self.other_ws.id
        self.other_user.profile.save()

    @staticmethod
    @workspace_views.check_workspace_owner_redirect
    def dummy_function(self, request, other):
        return 'return_value'

    def test_check_workspace_owner_no_redirect(self):
        self.other_user.profile.current_workspace.add_user_to_workspace(self.user, WorkspaceRoles.OWNER)
        self.user.profile.current_workspace_id = self.other_ws.id
        self.user.profile.current_collection_id = self.other_ws.id
        self.user.profile.save()

        mock = MagicMock()

        # get dummy request
        response = self.client.get(reverse('pdf_overview'))
        request = response.wsgi_request

        assert self.dummy_function(mock, request, 'asd') == 'return_value'

    def test_check_workspace_owner_redirect(self):
        self.other_user.profile.current_workspace.add_user_to_workspace(self.user, WorkspaceRoles.MEMBER)
        self.user.profile.current_workspace_id = self.other_ws.id
        self.user.profile.current_collection_id = self.other_ws.id
        self.user.profile.save()

        mock = MagicMock()

        # get dummy request
        response = self.client.get(reverse('pdf_overview'))
        request = response.wsgi_request

        return_value = self.dummy_function(mock, request, 'asd')
        assert return_value.status_code == 302
        assert return_value.url == reverse('pdf_overview')
