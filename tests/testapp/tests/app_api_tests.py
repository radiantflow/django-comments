from __future__ import absolute_import

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test.utils import override_settings
from django.utils import six

import comments
from comments.models import Comment
from comments.forms import CommentForm

from . import CommentTestCase


class CommentAppAPITests(CommentTestCase):
    """Tests for the "comment app" API"""

    def testGetCommentApp(self):
        self.assertEqual(comments.get_comment_app(), comments)

    @override_settings(
        COMMENTS_APP='missing_app',
        INSTALLED_APPS=list(settings.INSTALLED_APPS) + ['missing_app'],
    )
    def testGetMissingCommentApp(self):
        with six.assertRaisesRegex(self, ImproperlyConfigured, 'missing_app'):
            _ = comments.get_comment_app()

    def testGetForm(self):
        self.assertEqual(comments.get_form(), CommentForm)

    def testGetFormTarget(self):
        self.assertEqual(comments.get_form_target(), "/post/")

    def testGetFlagURL(self):
        c = Comment(id=12345)
        self.assertEqual(comments.get_flag_url(c), "/flag/12345/")

    def getGetDeleteURL(self):
        c = Comment(id=12345)
        self.assertEqual(comments.get_delete_url(c), "/delete/12345/")

    def getGetApproveURL(self):
        c = Comment(id=12345)
        self.assertEqual(comments.get_approve_url(c), "/approve/12345/")


@override_settings(
    COMMENTS_APP='custom_comments',
    INSTALLED_APPS=list(settings.INSTALLED_APPS) + [
        'custom_comments'],
)
class CustomCommentTest(CommentTestCase):
    urls = 'testapp.urls'

    def testGetCommentApp(self):
        import custom_comments
        self.assertEqual(comments.get_comment_app(), custom_comments)

    def testGetModel(self):
        from custom_comments.models import CustomComment
        self.assertEqual(comments.get_model(), CustomComment)

    def testGetForm(self):
        from custom_comments.forms import CustomCommentForm
        self.assertEqual(comments.get_form(), CustomCommentForm)

    def testGetFormTarget(self):
        self.assertEqual(comments.get_form_target(), "/post/")

    def testGetFlagURL(self):
        c = Comment(id=12345)
        self.assertEqual(comments.get_flag_url(c), "/flag/12345/")

    def getGetDeleteURL(self):
        c = Comment(id=12345)
        self.assertEqual(comments.get_delete_url(c), "/delete/12345/")

    def getGetApproveURL(self):
        c = Comment(id=12345)
        self.assertEqual(comments.get_approve_url(c), "/approve/12345/")
