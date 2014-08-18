from __future__ import absolute_import

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import get_object_or_404, render_to_response
from django.template import RequestContext
from django.template.response import TemplateResponse
from django.http import Http404, HttpResponse, HttpResponseNotAllowed, HttpResponseRedirect
from django.utils.encoding import force_text
from django.utils.html import escape
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

import comments
from comments import signals
from comments import utils
from comments.views.utils import next_redirect, confirmation_view
from comments.utils import CommentPostBadRequest, lookup_content_object

COMMENT_MODEL = comments.get_model()
COMMENT_FORM = comments.get_form()

def view(request, comment_pk=None, *args, **kwargs):
    comment_url = utils.get_comment_url(comment_pk, request)
    if comment_url:
        return HttpResponseRedirect(comment_url)
    else:
        raise Http404

@csrf_protect
def edit(request, comment_pk=None, parent_pk=None, ctype=None, object_pk=None, next=None, *args, **kwargs):
    """
    Edit or create a comment.
    Displays and processes the comment model form

    If HTTP POST is present it processes and adds / edits comment.
    If ``POST['submit'] == "preview"`` or if there are
    errors a preview template, ``comments/preview.html``, will be rendered.

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

        response = lookup_content_object(COMMENT_MODEL, data)
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

        next = form_data.get("next", next)
        form = COMMENT_FORM(data=form_data, instance=comment, request=request)

        # Make sure user has correct permissions to change the comment,
        # or return a 401 Unauthorized error.
        if new:
            if not form.can_create():
                return HttpResponse("Unauthorized", status=401)
        else:
            if not form.can_edit():
                return HttpResponse("Unauthorized", status=401)

        # Do we want to preview the comment?
        preview = "preview" in form_data

        if form.security_errors():
            # NOTE: security hash fails!
            return CommentPostBadRequest(
                "The comment form failed security verification: %s" % \
                    escape(str(form.security_errors())))

        # If there are errors, or if a preview is requested
        if form.errors or preview:
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
            result = form.save()
            # Get comment url
            if not next:
                next = utils.get_comment_url(result._get_pk_val(), request)
            return next_redirect(request, fallback=next)
            #_get_pk_val()
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

comment_done = confirmation_view(
    template="comments/posted.html",
    doc="""Display a "comment was posted" success page."""
)
