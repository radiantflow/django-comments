import time
from django import forms
from django.forms.util import ErrorDict
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core import urlresolvers
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models
from django.utils.crypto import salted_hmac, constant_time_compare
from django.utils.encoding import force_text
from django.utils.html import escape
from django.utils.text import get_text_list
from django.utils import timezone
from django.utils.translation import ungettext, ugettext, ugettext_lazy as _

from comments.models import Comment, CommentFlag
from comments import signals
from comments.utils import CommentPostBadRequest

COMMENT_MAX_LENGTH = getattr(settings,'COMMENT_MAX_LENGTH', 3000)

class CommentForm(forms.ModelForm):
    """
    Handles the all aspects of comment forms.
    """
    content_type  = forms.CharField(widget=forms.HiddenInput)
    object_pk     = forms.CharField(widget=forms.HiddenInput)
    timestamp     = forms.IntegerField(widget=forms.HiddenInput)
    security_hash = forms.CharField(min_length=40, max_length=40, widget=forms.HiddenInput)
    parent_pk     = forms.IntegerField(required=False, widget=forms.HiddenInput)

    user          = forms.ModelChoiceField(label=_("User"), required=False, queryset=get_user_model().objects.all())
    user_name     = forms.CharField(label=_("Name"), max_length=50, required=False)
    user_email    = forms.EmailField(label=_("Email address"), required=False)
    user_url      = forms.URLField(label=_("URL"), required=False)
    comment       = forms.CharField(label=_('Comment'), widget=forms.Textarea,
                                    max_length=COMMENT_MAX_LENGTH)
    honeypot      = forms.CharField(required=False,
                                    label=_('If you enter anything in this field '\
                                            'your comment will be treated as spam'))

    class Meta:
        model = Comment
        fields = ( "user", "user_name", "user_email", "user_url", "comment",
                  "timestamp", "security_hash", "honeypot")

    def __init__(self,
                 data=None,
                 request=None,
                 comment_pk=None,
                 parent_pk=None,
                 ctype=None,
                 object_pk=object_pk,
                 **kwargs):
        self.request = request
        self.parent_comment = None
        self.target_object = None
        instance = self.get_comment_object(comment_pk=comment_pk,
                                           parent_pk=parent_pk,
                                           ctype=ctype,
                                           object_pk=object_pk,
                                           **kwargs)
        super(CommentForm, self).__init__(data=data, instance=instance)
        # initiate the form with security data if no data was passed in.
        if not data:
            self.initial.update(self.generate_security_data())

        #self.fields["user_name"].widget.attrs["readonly"] = "readonly"
        #self.fields["user_email"].widget.attrs["readonly"] = "readonly"
        #self.fields["user_url"].widget.attrs["placeholder"] = "Homepage"

    def title(self):
        if self.is_new():
            return _('Post new comment')
        else:
            return _('Edit comment')

    def action_url(self):
        kwargs = {}
        if self.is_new():
            if self.instance.parent:
                kwargs['parent_pk'] = self.instance.parent._get_pk_val()
            else:
                content_type = self.instance.content_type
                kwargs['content_type'] = '%s.%s' % (content_type.app_label, content_type.model)
                kwargs['object_pk'] = self.target_object._get_pk_val()

        else:
            kwargs['comment_pk'] = self.instance._get_pk_val()

        return urlresolvers.reverse("comments.views.comment.edit", kwargs=kwargs)


    def security_errors(self):
        """Return just those errors associated with security"""
        errors = ErrorDict()
        for f in ["honeypot", "timestamp", "security_hash"]:
            if f in self.errors:
                errors[f] = self.errors[f]
        return errors

    def clean_security_hash(self):
        """Check the security hash."""
        security_hash_dict = {
            'content_type' : self.data.get("content_type", ""),
            'object_pk' : self.data.get("object_pk", ""),
            'timestamp' : self.data.get("timestamp", ""),
        }
        expected_hash = self.generate_security_hash(**security_hash_dict)
        actual_hash = self.cleaned_data["security_hash"]
        if not constant_time_compare(expected_hash, actual_hash):
            raise forms.ValidationError("Security hash check failed.")
        return actual_hash

    def clean_timestamp(self):
        """
        When editing comments, make sure timestamp matches the one on the instance, for new comments
        make sure the timestamp isn't too far (> 2 hours) in the past
        """
        ts = self.cleaned_data["timestamp"]
        if self.instance.submit_date:
            if not ts == time.mktime(self.instance.submit_date.timetuple()):
                raise forms.ValidationError("Timestamp check failed")
        elif time.time() - ts > (2 * 60 * 60):
            raise forms.ValidationError("Timestamp check failed")
        return ts

    def generate_security_data(self):
        """Generate a dict of security data for "initial" data."""
        if self.instance.submit_date:
            timestamp = int(time.mktime(self.instance.submit_date.timetuple()))
        else:
            timestamp = int(time.time())
        security_dict =   {
            'content_type'  : str(self.instance.content_type.pk),
            'object_pk'     : str(self.instance.content_object.pk),
            'timestamp'     : str(timestamp),
            'security_hash' : self.initial_security_hash(timestamp),
            'parent_pk'     : self.instance.parent and str(self.instance.parent.pk) or '',
        }

        return security_dict

    def initial_security_hash(self, timestamp):
        """
        Generate the initial security hash from self.content_object
        and a (unix) timestamp.
        """

        initial_security_dict = {
            'content_type' : str(self.instance.content_type.pk),
            'object_pk' : str(self.instance.content_object.pk),
            'timestamp' : str(timestamp),
          }

        return self.generate_security_hash(**initial_security_dict)

    def generate_security_hash(self, content_type, object_pk, timestamp):
        """
        Generate a HMAC security hash from the provided info.
        """
        info = (content_type, object_pk, timestamp)
        key_salt = "django.contrib.forms.CommentForm"
        value = "-".join(info)
        return salted_hmac(key_salt, value).hexdigest()


    def get_comment_object(self, comment_pk=None, parent_pk=None, ctype=None, object_pk=None, **kwargs):
        """
        Return an existing or new (unsaved) comment object based on the information in this
        form.

        """

        #if not self.is_valid():
        #    raise ValueError("get_comment_object may only be called on valid forms")


        COMMENT_MODEL = self.get_comment_model()

        if comment_pk:
            return COMMENT_MODEL.objects.get(pk=comment_pk, site__pk=settings.SITE_ID)

        if parent_pk:
            self.parent_comment = COMMENT_MODEL.objects.get(pk=parent_pk, site__pk=settings.SITE_ID)
            self.target_object = self.parent_comment.content_object

        else:
            if ctype and object_pk:
                try:
                    model = models.get_model(*ctype.split(".", 1))
                    self.target_object = model._default_manager.get(pk=object_pk)
                    # model._default_manager.using(using).get(pk=object_pk)

                except TypeError:
                    raise Exception(
                        "Invalid content_type value: %r" % escape(ctype))
                except AttributeError:
                    raise Exception(
                        "The given content-type %r does not resolve to a valid model." % \
                            escape(ctype))
                except ObjectDoesNotExist:
                    raise Exception(
                        "No object matching content-type %r and object PK %r exists." % \
                            (escape(ctype), escape(object_pk)))
                except (ValueError, ValidationError) as e:
                    raise Exception(
                        "Attempting go get content-type %r and object PK %r exists raised %s" % \
                            (escape(ctype), escape(object_pk), e.__class__.__name__))

        if self.target_object:
            CommentModel = self.get_comment_model()
            return CommentModel(**self.get_comment_create_data(**kwargs))

        else:
            raise Exception("No target found")



    def get_comment_model(self):
        """
        Get the comment model to create with this form. Subclasses in custom
        comment apps should override this, get_comment_create_data, and perhaps
        check_for_duplicate_comment to provide custom comment models.
        """
        return Comment


    def get_comment_create_data(self, **kwargs):
        """
        Returns the dict of data to be used to create a comment. Subclasses in
        custom comment apps that override get_comment_model can override this
        method to add extra fields onto a custom comment model.
        """

        return dict(
            content_type = ContentType.objects.get_for_model(self.target_object),
            object_pk    = force_text(self.target_object._get_pk_val()),
            parent       = self.parent_comment,
            site_id      = settings.SITE_ID,
            is_public    = self.parent_comment and self.parent_comment.is_public or True,
            is_removed   = False,
        )

    def check_for_duplicate_comment(self, new):
        """
        Check that a submitted comment isn't a duplicate. This might be caused
        by someone posting a comment twice. If it is a dup, silently return the *previous* comment.
        """
        possible_duplicates = self.get_comment_model()._default_manager.using(
            self.target_object._state.db
        ).filter(
            content_type = new.content_type,
            object_pk = new.object_pk,
            user = new.user,
            user_name = new.user_name,
            user_email = new.user_email,
            user_url = new.user_url,
        )
        for old in possible_duplicates:
            if old.submit_date.date() == new.submit_date.date() and old.comment == new.comment:
                return old

        return new

    def clean_comment(self):
        """
        If COMMENTS_ALLOW_PROFANITIES is False, check that the comment doesn't
        contain anything in PROFANITIES_LIST.
        """
        comment = self.cleaned_data["comment"]
        if settings.COMMENTS_ALLOW_PROFANITIES == False:
            bad_words = [w for w in settings.PROFANITIES_LIST if w in comment.lower()]
            if bad_words:
                raise forms.ValidationError(ungettext(
                    "Watch your mouth! The word %s is not allowed here.",
                    "Watch your mouth! The words %s are not allowed here.",
                    len(bad_words)) % get_text_list(
                        ['"%s%s%s"' % (i[0], '-'*(len(i)-2), i[-1])
                         for i in bad_words], ugettext('and')))
        return comment

    def clean_honeypot(self):
        """Check that nothing's been entered into the honeypot."""
        value = self.cleaned_data["honeypot"]
        if value:
            raise forms.ValidationError(self.fields["honeypot"].label)
        return value


    def is_new(self):
        if self.instance:
            return self.instance._get_pk_val() == None
        else:
            return True

    def is_owner(self):
        try:
            return self.instance.user == self.request.user
        except:
            return False

    def has_owner(self):
        try:
            return self.instance.user is None
        except:
            return False

    def is_authenticated(self):
        try:
            return self.request.user.is_authenticated()
        except:
            return False

    def is_moderator(self):
        try:
            return self.request.user.has_perm("comments.can_moderate")
        except:
            return False

    def can_create(self):
        try:
            return self.request.user.has_perm("comments.add_comment")
        except:
            return False

    def can_change(self):
        try:
            return self.request.user.has_perm("comments.change_comment")
        except:
            return False

    def can_edit(self):
        try:
            return (self.is_owner and self.can_change) or self.is_moderator()
        except:
            return False


    def visible_fields(self):
        """
        Returns a list of BoundField objects that aren't hidden fields.
        The opposite of the hidden_fields() method.
        """
        fields = []
        for field in self:
            if field.name == 'user':
                if not self.is_moderator():
                    continue

            elif field.name in ['user_name', 'user_email', 'user_url']:
                if self.is_moderator():
                    if self.is_new() or not self.has_owner():
                        continue
                elif self.is_authenticated():
                    continue

            if not field.is_hidden:
                fields.append(field)

        return fields

    def save(self, commit=True, send_signals=True):
        """Save the comment, adding extra fields if required."""

        if not self.request:
            return super(CommentForm, self).save(commit=commit)

        new = self.instance.pk is None
        flag = None
        created = None

        if new:
            self.instance.ip_address = self.request.META.get("REMOTE_ADDR", None)
            if self.request.user.is_authenticated():
                self.instance.user = self.request.user

        # Signal that the comment is about to be saved
        if send_signals:
            if new:
                signal_responses = signals.comment_will_be_posted.send(
                    sender=self.instance.__class__,
                    comment=self.instance,
                    request=self.request
                )

                for (receiver, response) in signal_responses:
                    if response == False:
                        return CommentPostBadRequest(
                        "comment_will_be_posted receiver %r killed the comment" % receiver.__name__)
            else:
                flag_label = "comment edited"
                flag, created = CommentFlag.objects.get_or_create(
                    comment = self.instance,
                    user = self.request.user,
                    flag = flag_label
                )


        comment = super(CommentForm, self).save(commit=commit)

        if send_signals:
            if new:
                signals.comment_was_posted.send(
                    sender=comment.__class__,
                    comment=comment,
                    request=self.request
                )
            else:
                signals.comment_was_flagged.send(
                    sender = comment.__class__,
                    comment = comment,
                    flag = flag,
                    created = created,
                    request = self.request
            )

        return comment

