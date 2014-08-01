from __future__ import absolute_import

from django import http
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.shortcuts import render_to_response
from django.template import RequestContext
from django.template.loader import render_to_string
from django.utils.html import escape
from django.utils.encoding import smart_text
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST
from django.http import HttpResponse, Http404

import comments
from comments import signals
from comments.views.utils import next_redirect, confirmation_view

COMMENT_MODEL = comments.get_model()

def _lookup_content_type(token):
    try:
        app, model = token.split('.')
        return ContentType.objects.get_by_natural_key(app, model)
    except ValueError:
        raise Exception("Third argument in must be in the format 'app.model'")
    except ContentType.DoesNotExist:
        raise Exception("non-existant content-type: '%s.%s'" % (app, model))


def _get_query_set(ctype, object_pk, root_only=True):

    qs = COMMENT_MODEL.objects.filter(
        content_type=ctype,
        object_pk=smart_text(object_pk),
        site__pk=settings.SITE_ID,
    )

    if root_only:
        qs = qs.exclude(parent__isnull=False)

    # The is_public and is_removed fields are implementation details of the
    # built-in comment model's spam filtering system, so they might not
    # be present on a custom comment model subclass. If they exist, we
    # should filter on them.
    field_names = [f.name for f in COMMENT_MODEL._meta.fields]
    if 'is_public' in field_names:
        qs = qs.filter(is_public=True)
    if getattr(settings, 'COMMENTS_HIDE_REMOVED', True) and 'is_removed' in field_names:
        qs = qs.filter(is_removed=False)

    return qs


def list_comments(request, ctype=None, object_pk=None, root_only=True):

    if isinstance(ctype, basestring):
        ctype = _lookup_content_type(ctype)
    if isinstance(ctype, ContentType) and object_pk:
        template_search_list = [
            "comments/%s/%s/list.html" % (ctype.app_label, ctype.model),
            "comments/%s/list.html" % ctype.app_label,
            "comments/list.html"
        ]
        qs = _get_query_set(ctype, object_pk, root_only)
        return render_to_response(template_search_list, {
            "comment_list" : list(qs)
        })
    else:
        return HttpResponse('')
