# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.


{
    'name': 'Route Planing',
    'version': '1.0',
    'category': '',
    'sequence': 200,
    'summary': 'Route optimization in Odoo refers to enhancing the delivery and logistics process by minimizing travel distances, time, and costs                          .',
    'description': """
Route optimization in Odoo refers to enhancing the delivery and logistics process by minimizing travel distances, time, and costs associated with managing deliveries or transportation. This feature is critical for businesses with delivery fleets or field services, as it improves efficiency and reduces operational expenses.
""",
    'live_test_url': 'https://localhost:8069/live_preview',
    'author': 'Master Software Solutions',
    'website': 'https://www.mastersoftwaresolutions.com/',
    'depends': [
        'base', 'sale', 'mail', 'web','fleet','base_geolocalize','stock', 'contacts','mss_timepicker','project',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/traktop.xml',
        'views/sale_order_build_time_views.xml',
        'views/res_partner_gmap.xml',
        'views/res_config_settings_view.xml',
        'views/fleet.xml',
        'security/traktop_record_rules.xml',
        'views/user_registration.xml',
        'views/reporting_view.xml',
        # 'data/cron.xml',
    ],
    'demo': [
    ],
    'images': ['static/description/main_screenshot.png', 'static/description/icon.png'],
    'installable': True,
    'application': True,
    'pre_init_hook': '',
    'license': 'LGPL-3',
    'assets': {
        'web.assets_backend': [
            'mss_route_plan/static/src/**/*',
        ],
        'web.assets_frontend': [
        ],
        'web.assets_tests': [
        ],
    }
}
