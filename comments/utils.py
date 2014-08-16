from django.conf import settings
from django import http
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models
from django.template.loader import render_to_string
from django.utils.encoding import smart_text
from django.utils.html import escape
from django.utils.safestring import mark_safe



class CommentPostBadRequest(http.HttpResponseBadRequest):
    """
    Response returned when a comment post is invalid. If ``DEBUG`` is on a
    nice-ish error message will be displayed (for debugging purposes), but in
    production mode a simple opaque 400 page will be displayed.
    """
    def __init__(self, why):
        super(CommentPostBadRequest, self).__init__()
        if settings.DEBUG:
            self.content = render_to_string("comments/400-debug.html", {"why": why})


def lookup_content_object(comment_model, data):
    # Look up the object we're trying to comment about
    ctype = data.get("content_type")
    object_pk = data.get("object_pk")
    parent_pk = data.get("parent_pk")

    if parent_pk:
        try:
            parent_comment = comment_model.objects.get(pk=parent_pk)
            target = parent_comment.content_object
            model = target.__class__
        except comment_model.DoesNotExist:
            return CommentPostBadRequest(
                "Parent comment with PK %r does not exist." % \
                    escape(parent_pk))
    elif ctype and object_pk:
        try:
            parent_comment = None
            model = models.get_model(*ctype.split(".", 1))
            target = model._default_manager.get(pk=object_pk)
            # model._default_manager.using(using).get(pk=object_pk)
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

    else:
        return CommentPostBadRequest("Missing content_type or object_pk field.")

    return (target, parent_comment, model)



def get_query_set(ctype=None, object_pk=None, target=None, root_only=False, except_root=False, tree_ids=None):

    if target:
        ctype = ContentType.objects.get_for_model(target)
        object_pk = force_text(target._get_pk_val())

    if ctype is None or object_pk is None:
        raise Exception('No ctype or object_pk supplied')

    import comments
    COMMENT_MODEL = comments.get_model()

    qs = COMMENT_MODEL.objects.filter(
        content_type=ctype,
        object_pk=smart_text(object_pk),
        site__pk=settings.SITE_ID,
    )

    # Only return the root level items?
    if root_only:
        qs = qs.exclude(parent__isnull=False)

    if except_root:
        qs = qs.exclude(parent__isnull=True)

    # Get tree ids.
    if tree_ids:
        qs = qs.filter(tree_id__in = tree_ids)

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


def get_root_children(root_qs, ctype, object_pk):
    tree_ids = []
    root_level = None

    if root_qs:
        # Get the model's parent-attribute name
        #parent_attr = root_qs[0]._mptt_meta.parent_attr
        root_level = None

        for obj in root_qs:
            # Get the current mptt node level
            node_level = obj.get_level()

            if root_level is None:
                # First iteration, so set the root level to the top node level
                root_level = node_level

            elif node_level < root_level:
                root_level = node_level

            tree_ids.append(obj.tree_id)

    if tree_ids:
        return get_query_set(ctype=ctype, object_pk=object_pk, tree_ids=tree_ids, except_root=True)

    return None


def cache_comment_children(root_qs, child_qs):
    """
    Takes a list/queryset of model objects in MPTT left (depth-first) order,
    caches the children on each node, as well as the parent of each child node,
    allowing up and down traversal through the tree without the need for
    further queries. This makes it possible to have a recursively included
    template without worrying about database queries.

    Returns a list of top-level nodes. If a single tree was provided in its
    entirety, the list will of course consist of just the tree's root node.

    """

    all_nodes = {}

    if root_qs:
        # Get the model's parent-attribute name

        root_level = None

        for obj in root_qs:
            # Set up the attribute on the node that will store cached children,
            # which is used by ``MPTTModel.get_children``
            obj._cached_children = []

            # Add node to all nodes dict.
            all_nodes[obj.pk] = obj

        if child_qs:

            parent_attr = child_qs[0]._mptt_meta.parent_attr

            for obj in child_qs:
                all_nodes[obj.pk] = obj

                # Set up the attribute on the node that will store cached children,
                # which is used by ``MPTTModel.get_children``
                obj._cached_children = []

                parent_id = obj.parent_id
                parent = all_nodes.get(parent_id)
                if parent:
                    parent._cached_children.append(obj)
                # Cache the parent on the current node, and attach the current
                # node to the parent's list of children
                #_parent = all_nodes[]
                #setattr(obj, parent_attr, _parent)
                #_parent._cached_children.append(obj)
                #


    return root_qs

