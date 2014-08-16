from django.conf import settings
from django.utils.datastructures import SortedDict
from sorter.sortedset import SortedSet

COMMENTS_ANCHOR = getattr(settings, 'COMMENTS_ANCHOR', 'comments')

class CommentSorter(SortedSet):
    # Defaults, you probably want to specify these when you subclass
    default_sort = 'oldest'
    allowed_sort_fields = SortedDict([
        ('newest', {
            'fields': ['level', '-submit_date'],
            'verbose_name': 'Newest',
        }),
        ('oldest', {
            'fields': ['level', 'submit_date'],
            'verbose_name': 'Oldest',
        }),
    ])

    def __init__(self, queryset, anchor=None, **kwargs):
        if anchor is None:
            anchor = COMMENTS_ANCHOR
        super(CommentSorter, self).__init__(queryset=queryset, anchor=anchor, **kwargs)
