from __future__ import absolute_import

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import get_object_or_404, render_to_response
from django.template import RequestContext
from django.template.response import TemplateResponse
from django.http import Http404, HttpResponse, HttpResponseNotAllowed
from django.utils.encoding import force_text
from django.utils.html import escape
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

import comments
from comments import signals
from comments.views.utils import next_redirect, confirmation_view
from comments.utils import CommentPostBadRequest

COMMENT_MODEL = comments.get_model()
COMMENT_FORM = comments.get_form()

def _lookup_content_object(data):
    # Look up the object we're trying to comment about
    ctype = data.get("content_type")
    object_pk = data.get("object_pk")
    parent_pk = data.get("parent_pk")

    if parent_pk:
        try:
            parent_comment = COMMENT_MODEL.objects.get(pk=parent_pk)
            target = parent_comment.content_object
            model = target.__class__
        except COMMENT_MODEL.DoesNotExist:
            return CommentPostBadRequest(
                "Parent comment with PK %r does not exist." % \
                    escape(parent_pk))
    elif ctype and object_pk:
        try:
            parent_comment = None
            model = models.get_model(*ctype.split(".", 1))
            target = model._default_manager.get(pk=object_pk)
        except TypeError:
            return CommentPostBadRequest(
                "Invalid content_type value: %r" % escape(ctype))
        except AttributeError:
            return CommentPostBadRequest(
                "The given content-type %r does not resolve to a valid model." % \
                    escape(ctype))
        except ObjectDoesNotExist:
            return CommentPostBadRequest(
                "No object matching content-type %r and object PK %r exists." % \
                    (escape(ctype), escape(object_pk)))
    else:
        return CommentPostBadRequest("Missing content_type or object_pk field.")

    return (target, parent_comment, model)

@csrf_protect
@require_POST
def post_comment(request, next=None, using=None):
    """
    Post a comment.

    HTTP POST is required. If ``POST['submit'] == "preview"`` or if there are
    errors a preview template, ``comments/preview.html``, will be rendered.
    """
    # Fill out some initial data fields from an authenticated user, if present
    data = request.POST.copy()
    if request.user.is_authenticated():
        if not data.get('user_name', ''):
            data["user_name"] = request.user.get_full_name() or request.user.get_username()
        if not data.get('user_email', ''):
            data["user_email"] = request.user.email

    # Look up the object we're trying to comment about
    ctype = data.get("content_type")
    object_pk = data.get("object_pk")
    if ctype is None or object_pk is None:
        return CommentPostBadRequest("Missing content_type or object_pk field.")
    try:
        model = models.get_model(*ctype.split(".", 1))
        target = model._default_manager.using(using).get(pk=object_pk)
    except TypeError:
        return CommentPostBadRequest(
            "Invalid content_type value: %r" % escape(ctype))
    except AttributeError:
        return CommentPostBadRequest(
            "The given content-type %r does not resolve to a valid model." % \
                escape(ctype))
    except ObjectDoesNotExist:
        return CommentPostBadRequest(
            "No object matching content-type %r and object PK %r exists." % \
                (escape(ctype), escape(object_pk)))
    except (ValueError, ValidationError) as e:
        return CommentPostBadRequest(
            "Attempting go get content-type %r and object PK %r exists raised %s" % \
                (escape(ctype), escape(object_pk), e.__class__.__name__))

    # Do we want to preview the comment?
    preview = "preview" in data

    # Construct the comment form
    form = comments.get_form()(target, data=data)

    # Check security information
    if form.security_errors():
        return CommentPostBadRequest(
            "The comment form failed security verification: %s" % \
                escape(str(form.security_errors())))

    # If there are errors or if we requested a preview show the comment
    if form.errors or preview:
        template_list = [
            # These first two exist for purely historical reasons.
            # Django v1.0 and v1.1 allowed the underscore format for
            # preview templates, so we have to preserve that format.
            "comments/%s_%s_preview.html" % (model._meta.app_label, model._meta.module_name),
            "comments/%s_preview.html" % model._meta.app_label,
            # Now the usual directory based template hierarchy.
            "comments/%s/%s/preview.html" % (model._meta.app_label, model._meta.module_name),
            "comments/%s/preview.html" % model._meta.app_label,
            "comments/preview.html",
        ]
        return render_to_response(
            template_list, {
                "comment": form.data.get("comment", ""),
                "form": form,
                "next": data.get("next", next),
            },
            RequestContext(request, {})
        )

    # Otherwise create the comment
    comment = form.get_comment_object()
    comment.ip_address = request.META.get("REMOTE_ADDR", None)
    if request.user.is_authenticated():
        comment.user = request.user

    # Signal that the comment is about to be saved
    responses = signals.comment_will_be_posted.send(
        sender=comment.__class__,
        comment=comment,
        request=request
    )

    for (receiver, response) in responses:
        if response == False:
            return CommentPostBadRequest(
                "comment_will_be_posted receiver %r killed the comment" % receiver.__name__)

    # Save the comment and signal that it was saved
    comment.save()
    signals.comment_was_posted.send(
        sender=comment.__class__,
        comment=comment,
        request=request
    )

    return next_redirect(request, fallback=next or 'comments-comment-done',
        c=comment._get_pk_val())

comment_done = confirmation_view(
    template="comments/posted.html",
    doc="""Display a "comment was posted" success page."""
)


def edit(request, comment_pk=None, parent_pk=None, ctype=None, object_pk=None, next=None, *args, **kwargs):
    """
    Edit or create a comment.
    Displays and processes the comment model form

    """

    is_ajax = request.GET.get('is_ajax') and '_ajax' or ''

    if comment_pk:
        try:
            comment =  COMMENT_MODEL.objects.get(pk=comment_pk, site__pk=settings.SITE_ID)
            target = comment.content_object
            model = target.__class__
            new = False
        except COMMENT_MODEL.DoesNotExist:
            return CommentPostBadRequest(
                "Comment with PK %r does not exist." % \
                    escape(comment_pk))

    else:
        data = {
            'parent_pk': parent_pk,
            'content_type': ctype,
            'object_pk': object_pk,
        }

        response = _lookup_content_object(data)
        if isinstance(response, HttpResponse):
            return response
        else:
            target, parent_comment, model = response

        new = True
        content_type = ContentType.objects.get_for_model(target)
        object_pk = force_text(target._get_pk_val())

        if content_type is None or object_pk is None:
            return CommentPostBadRequest("Missing content_type or object_pk field.")

        comment = COMMENT_MODEL(
            content_type=content_type,
            object_pk=object_pk,
            parent=parent_comment,
            site_id=settings.SITE_ID,
        )


    if request.POST:
        form_data = request.POST.copy()

        if not form_data.get("user_name", ""):
            form_data["user_name"] = request.user.get_full_name() or request.user.username
        if not form_data.get("user_email"):
            form_data["user_email"] = request.user.email

        next = form_data.get("next", next)
        form = COMMENT_FORM(data=form_data, instance=comment, request=request)

        # Make sure user has correct permissions to change the comment,
        # or return a 401 Unauthorized error.
        if new:
            if not (request.user.has_perm("comments.add_comment")):
                return HttpResponse("Unauthorized", status=401)
        else:
            if not (request.user == comment.user and request.user.has_perm("comments.change_comment")
                 or request.user.has_perm("comments.can_moderate")):
                return HttpResponse("Unauthorized", status=401)


        if form.security_errors():
            # NOTE: security hash fails!
            return CommentPostBadRequest(
                "The comment form failed security verification: %s" % \
                    escape(str(form.security_errors())))

        # If there are errors, or if a preview is requested
        if form.errors or "preview" in form_data:
            app_label, model_name = (form.instance.content_type.app_label, form.instance.content_type.model)
            template_list = [
                # These first two exist for purely historical reasons.
                # Django v1.0 and v1.1 allowed the underscore format for
                # preview templates, so we have to preserve that format.
                "comments/%s_%s_preview.html" % (app_label, model_name),
                "comments/%s_preview.html" % app_label,
                # Now the usual directory based template hierarchy.
                "comments/%s/%s/preview.html" % (app_label, model_name),
                "comments/%s/preview.html" % model_name,
                "comments/preview.html",
            ]

            return render_to_response(
                template_list, {
                    "comment_obj": comment,
                    "comment": form.data.get("comment", ""),
                    "form": form,
                    "next": next,
                },
                RequestContext(request, {})
            )

        if form.is_valid():
            # Save the comment and signal that it was saved
            form.save()
            return next_redirect(request, fallback= next or comment_done, c=comment.pk)
        else:
            # If we got here, raise Bad Request error.
            return CommentPostBadRequest("Could not complete request!")

    else:
        title = 'Post a reply'
        # Construct the initial comment form
        form = COMMENT_FORM(instance=comment, request=request)

        template_list = [
            "comments/%s_%s_edit_form%s.html" % tuple(str(model._meta).split(".") + [is_ajax]),
            "comments/%s_edit_form%s.html" % (model._meta.app_label, is_ajax),
            "comments/edit_form%s.html" % is_ajax,
        ]
        return TemplateResponse(request, template_list, {
            "form" : form,
            "title" : title
        })
