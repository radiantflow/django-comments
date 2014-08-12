from django.utils.datastructures import SortedDict
from sorter.sortedset import SortedSet

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
