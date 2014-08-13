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
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext as _
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST
from django.http import HttpResponse, Http404
from pure_pagination.paginator import Paginator, EmptyPage, PageNotAnInteger

import comments
from comments import signals
from comments.sorters import CommentSorter
from comments.views.utils import next_redirect, confirmation_view
from comments import utils

COMMENT_MODEL = comments.get_model()
COMMENTS_PER_PAGE = getattr(settings, 'COMMENTS_PER_PAGE', 10)
COMMENTS_ANCHOR = getattr(settings, 'COMMENTS_ANCHOR', 'comments')

def _lookup_content_type(token):
    try:
        app, model = token.split('.')
        return ContentType.objects.get_by_natural_key(app, model)
    except ValueError:
        raise Exception("Third argument in must be in the format 'app.model'")
    except ContentType.DoesNotExist:
        raise Exception("non-existant content-type: '%s.%s'" % (app, model))



#def get_root_comments(ctype=None, object_pk=None, order_by='submit_date'):

def list_comments(request, ctype=None, object_pk=None, root_only=True):

    try:
        page = request.GET.get('page', 1)
        sort = request.GET.get('sort', 'oldest')

    except PageNotAnInteger:
        page = 1
        sort = 'oldest'

    if isinstance(ctype, basestring):
        ctype = _lookup_content_type(ctype)
    if isinstance(ctype, ContentType) and object_pk:

        try:
            root_qs = utils.get_query_set(ctype, object_pk, root_only=True)
            sorter = CommentSorter(root_qs, request=request, anchor=COMMENTS_ANCHOR)
            paginator = Paginator(sorter.sort(), COMMENTS_PER_PAGE, request=request, anchor=COMMENTS_ANCHOR)
            root_qs = paginator.page(page)

            child_qs = utils.get_root_children(root_qs, ctype, object_pk)
            if child_qs:
                child_sorter = CommentSorter(child_qs, request=request, anchor=COMMENTS_ANCHOR)
                child_qs = child_sorter.sort()

            tree = utils.cache_comment_children(root_qs, child_qs)
        except Exception as e:
             e = e
             raise Http404


        try:
            comments = tree
            #sorter.group(comments)

        except EmptyPage:
            raise Http404

        #if sorter.grouped:
        #   template_file = 'teaser_list_grouped.html'
        #else:
        #    template_file = 'teaser_list.html'


        template_search_list = [
            "comments/%s/%s/list.html" % (ctype.app_label, ctype.model),
            "comments/%s/list.html" % ctype.app_label,
            "comments/list.html"
        ]
        return render_to_response(template_search_list, {
            "comment_list" : comments,
            'request': request,
            'sort_dropdown': sorter.sort_dropdown,

        })

        #posts_output = render_to_string('posts/includes/' + template_file, {
        #'posts': posts,
        #'request': request,
        #'sorter' : sorter,
        #'sort_dropdown': sorter.sort_dropdown,
        #'subsort_dropdown': sorter.subsort_dropdown
        #})

    else:
        return HttpResponse('')
