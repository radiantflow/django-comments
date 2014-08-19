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
from comments.utils import CommentPostBadRequest

COMMENT_MODEL = comments.get_model()
COMMENT_FORM = comments.get_form()

def view(request, comment_pk=None, *args, **kwargs):
    comment_url = utils.get_comment_url(comment_pk=comment_pk, request=request)
    if comment_url:
        return HttpResponseRedirect(comment_url)
    else:
        raise Http404

@csrf_protect
def edit(request, comment_pk=None, parent_pk=None, content_type=None, object_pk=None, next=None, *args, **kwargs):
    """
    Edit or create a comment.
    Displays and processes the comment model form

    If HTTP POST is present it processes and adds / edits comment.
    If ``POST['submit'] == "preview"`` or if there are
    errors a preview template, ``comments/preview.html``, will be rendered.

    """

    is_ajax = request.GET.get('is_ajax') and '_ajax' or ''

    if request.POST:
        form_data = request.POST.copy()

        next = form_data.get("next", next)

        try:
            form = COMMENT_FORM(data=form_data,
                                comment_pk=comment_pk,
                                parent_pk=parent_pk,
                                ctype=content_type,
                                object_pk=object_pk,
                                request=request,
                                **kwargs)
        except COMMENT_MODEL.DoesNotExist:
               return HttpResponse("Comment does not exist", status=404)

        # Make sure user has correct permissions to change the comment,
        # or return a 401 Unauthorized error.
        if form.is_new():
            if not form.can_create():
                return HttpResponse("Unauthorized", status=401)
        else:
            if not form.can_edit():
                return HttpResponse("Unauthorized", status=401)

        if form.security_errors():
            # NOTE: security hash fails!
            return CommentPostBadRequest(
                "The comment form failed security verification: %s" % \
                    escape(str(form.security_errors())))

        # If there are errors, or if a preview is requested
        if form.errors:
            app_label, model_name = (form.instance.content_type.app_label, form.instance.content_type.model)
            template_list = [
                "comments/%s_%s_edit_form%s.html" % (app_label, model_name, is_ajax),
                "comments/%s_edit_form%s.html" % (app_label, is_ajax),
                "comments/edit_form%s.html" % is_ajax,
            ]

            return render_to_response(
                template_list, {
                    "comment_obj": form.instance,
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
                next = utils.get_comment_url(comment_pk=result._get_pk_val(), request=request)
            return next_redirect(request, fallback=next)
            #_get_pk_val()
        else:
            # If we got here, raise Bad Request error.
            return CommentPostBadRequest("Could not complete request!")

    else:
        title = 'Post a reply'
        # Construct the initial comment form
        try:
            form = COMMENT_FORM(request=request,
                                comment_pk=comment_pk,
                                parent_pk=parent_pk,
                                ctype=content_type,
                                object_pk=object_pk,
                                **kwargs)
        except COMMENT_MODEL.DoesNotExist:
               return HttpResponse("Comment does not exist", status=404)


        app_label, model_name = (form.instance.content_type.app_label, form.instance.content_type.model)
        template_list = [
            "comments/%s_%s_edit_form%s.html" % (app_label, model_name, is_ajax),
            "comments/%s_edit_form%s.html" % (app_label, is_ajax),
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
