{
    'name': 'Route Planning',
    'version': '1.0',
    'depends': ['sale', 'fleet'],
    'data': [
        'views/route_plan_views.xml',
        'data/cron.xml',
    ],
    'installable': True,
    'application': False,
}
