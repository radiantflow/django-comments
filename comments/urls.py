from django.conf.urls import patterns, url

urlpatterns = patterns('comments.views',
    url(r'^list/(\w+\.\w+)/(\d+)/$',    'list.list_comments',           name='comments-list-comments'),
    url(r'^view/(?P<comment_pk>\d+)/$', 'comment.view',                 name='comment-view'),
    url(r'^edit/(?P<comment_pk>\d+)/$', 'comment.edit',                 name='comment-edit'),
    url(r'^reply/(?P<parent_pk>\d+)/$', 'comment.edit',                 name='comment-reply'),
    url(r'^new/(?P<content_type>[\w.]+)/(?P<object_pk>\d+)/$',
                                        'comment.edit',                 name='comment-new'),
    url(r'^posted/$',                   'comment.comment_done',         name='comments-comment-done'),
    url(r'^flag/(\d+)/$',               'moderation.flag',              name='comments-flag'),
    url(r'^flagged/$',                  'moderation.flag_done',         name='comments-flag-done'),
    url(r'^delete/(\d+)/$',             'moderation.delete',            name='comments-delete'),
    url(r'^deleted/$',                  'moderation.delete_done',       name='comments-delete-done'),
    url(r'^approve/(\d+)/$',            'moderation.approve',           name='comments-approve'),
    url(r'^approved/$',                 'moderation.approve_done',      name='comments-approve-done'),
)

urlpatterns += patterns('',
    url(r'^cr/(\d+)/(.+)/$', 'django.contrib.contenttypes.views.shortcut', name='comments-url-redirect'),
)
