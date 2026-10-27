import pytest
from django.contrib.auth.models import User
from django.test import TestCase
from pdf.models.helpers import get_workspace_path
from pdf.models.workspace_models import WorkspaceError, WorkspaceRoles, WorkspaceUser
from pdf.services.workspace_services import create_collection, create_workspace


class TestWorkspace(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='user_1', password='password')
        self.ws = create_workspace(name='ws', creator=self.user)
        self.other_user = User.objects.create_user(username='other_user', password='password')

    def test_delete(self):
        self.ws.add_user_to_workspace(self.other_user, WorkspaceRoles.MEMBER)
        self.other_user.profile.current_workspace_id = self.ws.id
        self.other_user.profile.current_collection_id = self.ws.id
        self.other_user.profile.save()

        ws_path = get_workspace_path(self.ws)
        pdfs_path = ws_path / 'some_collection' / 'pdf'
        pdfs_path.mkdir(parents=True)

        dummy_file_path = pdfs_path / 'dummy.pdf'
        dummy_file_path.touch()

        assert self.other_user.profile.current_workspace_id == self.ws.id
        assert self.other_user.profile.current_collection_id == self.ws.id

        self.ws.delete()

        other_user = User.objects.get(id=self.other_user.id)
        assert not ws_path.exists()
        assert other_user.profile.current_workspace_id == str(self.other_user.id)
        assert other_user.profile.current_collection_id == 'all'

    def test_user_property(self):
        self.assertEqual(self.ws.users.count(), 1)

        user_2 = User.objects.create_user(username='user_2', password='password')
        user_3 = User.objects.create_user(username='user_3', password='password')

        WorkspaceUser.objects.create(workspace=self.ws, user=user_2, role=WorkspaceRoles.MEMBER)
        WorkspaceUser.objects.create(workspace=self.ws, user=user_3, role=WorkspaceRoles.MEMBER)

        self.assertEqual(self.ws.users.count(), 3)

        for expected_user, user in zip([self.user, user_2, user_3], self.ws.users.order_by('username')):
            self.assertEqual(expected_user, user)

    def test_owners_property(self):
        self.assertEqual(self.ws.owners.count(), 1)
        self.assertEqual(self.ws.members.count(), 0)
        self.assertEqual(self.ws.guests.count(), 0)

        user_2 = User.objects.create_user(username='user_2', password='password')
        WorkspaceUser.objects.create(workspace=self.ws, user=user_2, role=WorkspaceRoles.OWNER)

        self.assertEqual(self.ws.owners.count(), 2)
        self.assertEqual(self.ws.members.count(), 0)
        self.assertEqual(self.ws.guests.count(), 0)

        for expected_user, user in zip([self.user, user_2], self.ws.users.order_by('username')):
            self.assertEqual(expected_user, user)

    def test_members_property(self):
        self.assertEqual(self.ws.owners.count(), 1)
        self.assertEqual(self.ws.members.count(), 0)
        self.assertEqual(self.ws.guests.count(), 0)

        user_2 = User.objects.create_user(username='user_2', password='password')
        WorkspaceUser.objects.create(workspace=self.ws, user=user_2, role=WorkspaceRoles.MEMBER)

        self.assertEqual(self.ws.owners.count(), 1)
        self.assertEqual(self.ws.members.count(), 1)
        self.assertEqual(self.ws.guests.count(), 0)

        self.assertEqual(self.ws.members[0], user_2)

    def test_guests_property(self):
        self.assertEqual(self.ws.owners.count(), 1)
        self.assertEqual(self.ws.members.count(), 0)
        self.assertEqual(self.ws.guests.count(), 0)

        user_2 = User.objects.create_user(username='user_2', password='password')
        WorkspaceUser.objects.create(workspace=self.ws, user=user_2, role=WorkspaceRoles.GUEST)

        self.assertEqual(self.ws.owners.count(), 1)
        self.assertEqual(self.ws.members.count(), 0)
        self.assertEqual(self.ws.guests.count(), 1)

        self.assertEqual(self.ws.guests[0], user_2)

    def test_collections_property(self):
        self.assertEqual(self.ws.collections.count(), 1)

        created_collection = create_collection(self.ws, 'some_collection')

        self.assertEqual(self.ws.collections.count(), 2)

        self.assertEqual(self.ws.collections.order_by('name')[1], created_collection)

    def test_workspace_users_ordered(self):
        user_2 = User.objects.create_user(username='some_guest', password='password')
        user_3 = User.objects.create_user(username='some_member', email='some@a.com', password='password')
        user_4 = User.objects.create_user(username='other_member', email='other@a.com', password='password')
        WorkspaceUser.objects.create(workspace=self.ws, user=user_2, role=WorkspaceRoles.GUEST)
        WorkspaceUser.objects.create(workspace=self.ws, user=user_3, role=WorkspaceRoles.MEMBER)
        WorkspaceUser.objects.create(workspace=self.ws, user=user_4, role=WorkspaceRoles.MEMBER)

        ordered_users = self.ws.workspace_users_ordered
        assert ordered_users.count() == 4

        # users need to be sorted by role and name
        assert ordered_users[0].user == self.user
        assert ordered_users[1].user == user_4
        assert ordered_users[2].user == user_3
        assert ordered_users[3].user == user_2

    def test_add_workspace_user(self):
        user_2 = User.objects.create_user(username='user_2', password='password')

        self.assertEqual(self.ws.users.count(), 1)
        self.assertEqual(self.ws.members.count(), 0)

        self.ws.add_user_to_workspace(user_2, WorkspaceRoles.MEMBER)

        self.assertEqual(self.ws.users.count(), 2)
        self.assertEqual(self.ws.members.count(), 1)
        self.assertEqual(self.ws.members[0], user_2)

    def test_add_workspace_user_personal_workspace(self):
        personal_ws = self.user.profile.workspaces[0]
        user_2 = User.objects.create_user(username='user_2', password='password')

        with self.assertRaisesMessage(
            WorkspaceError, expected_message='Cannot add other users to personal workspaces!'
        ):
            personal_ws.add_user_to_workspace(user_2, WorkspaceRoles.MEMBER)

    def test_add_workspace_user_user_present(self):
        with self.assertRaisesMessage(WorkspaceError, expected_message='User is already a user of the workspace!'):
            self.ws.add_user_to_workspace(self.user, WorkspaceRoles.MEMBER)

    def test_is_owner(self):
        user_2 = User.objects.create_user(username='user_2', password='password')
        user_3 = User.objects.create_user(username='user_3', password='password')
        self.ws.add_user_to_workspace(user_2, WorkspaceRoles.MEMBER)
        self.ws.add_user_to_workspace(user_3, WorkspaceRoles.GUEST)

        assert self.ws.is_owner(self.user)
        assert not self.ws.is_owner(user_2)
        assert not self.ws.is_owner(user_3)

    def test_can_edit(self):
        user_2 = User.objects.create_user(username='user_2', password='password')
        user_3 = User.objects.create_user(username='user_3', password='password')
        self.ws.add_user_to_workspace(user_2, WorkspaceRoles.MEMBER)
        self.ws.add_user_to_workspace(user_3, WorkspaceRoles.GUEST)

        assert self.ws.can_edit(self.user)
        assert self.ws.can_edit(user_2)
        assert not self.ws.can_edit(user_3)

    def test_remove_workspace_user(self):
        other_ws = create_workspace('other_ws', self.other_user)
        self.other_user.profile.current_workspace_id = other_ws.id
        self.other_user.profile.save()

        self.other_user.profile.current_workspace.add_user_to_workspace(self.user, WorkspaceRoles.MEMBER)
        self.user.profile.current_workspace_id = other_ws.id
        self.user.profile.current_collection_id = other_ws.id
        self.user.profile.save()

        assert other_ws.members.filter(id=self.user.id).exists()

        other_ws.remove_workspace_user(self.user)

        assert not other_ws.members.filter(id=self.user.id).exists()

        # get user again
        user = User.objects.get(id=self.user.id)
        assert user.profile.current_workspace_id == str(self.user.id)
        assert user.profile.current_collection_id == 'all'

    def test_remove_workspace_user_personal_ws(self):
        ws = self.user.profile.current_workspace

        with pytest.raises(WorkspaceError, match='Action not possible for personal workspaces!'):
            ws.remove_workspace_user(self.user)

    def test_post_only_owner(self):
        other_ws = create_workspace('other_ws', self.user)
        self.user.profile.current_workspace_id = other_ws.id
        self.user.profile.save()

        with pytest.raises(WorkspaceError, match='Action not possible as there is only one workspace owner!'):
            other_ws.remove_workspace_user(self.user)
