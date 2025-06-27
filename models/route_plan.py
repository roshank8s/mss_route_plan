from odoo import api, fields, models, _
from datetime import date


class RoutePlan(models.Model):
    _name = 'route.plan'
    _description = 'Route Plan'

    name = fields.Char(default=lambda self: fields.Date.today().strftime('%Y-%m-%d'))
    date = fields.Date(default=fields.Date.today)
    line_ids = fields.One2many('route.plan.line', 'plan_id', string='Lines')

    def action_generate_lines(self):
        today = fields.Date.today()
        weekday = today.strftime('%a').lower()[:3]
        partners = self.env['res.partner'].search([
            ('delivery_day', '=', weekday)
        ])
        orders = self.env['sale.order'].search([
            ('partner_shipping_id', 'in', partners.ids),
            ('state', 'in', ['sale', 'done']),
            ('commitment_date', '>=', today)
        ])
        for order in orders:
            line = self.env['route.plan.line'].search([
                ('plan_id', '=', self.id),
                ('order_id', '=', order.id)
            ], limit=1)
            if not line:
                self.env['route.plan.line'].create({
                    'plan_id': self.id,
                    'order_id': order.id,
                    'partner_id': order.partner_shipping_id.id,
                })
        return True

    def action_assign_routes(self):
        optimizer = self.env['unified.route.optimizer']
        optimizer.action_run_unified_optimization()
        return True

    @api.model
    def create_daily_plan(self):
        today = fields.Date.today()
        plan = self.search([('date', '=', today)], limit=1)
        if not plan:
            plan = self.create({'date': today, 'name': today})
        plan.action_generate_lines()
        return plan


class RoutePlanLine(models.Model):
    _name = 'route.plan.line'
    _description = 'Route Plan Line'

    plan_id = fields.Many2one('route.plan', string='Plan')
    order_id = fields.Many2one('sale.order', string='Sale Order')
    partner_id = fields.Many2one('res.partner', string='Customer')


class ResPartner(models.Model):
    _inherit = 'res.partner'
    delivery_day = fields.Selection([
        ('mon', 'Monday'),
        ('tue', 'Tuesday'),
        ('wed', 'Wednesday'),
        ('thu', 'Thursday'),
        ('fri', 'Friday'),
        ('sat', 'Saturday'),
        ('sun', 'Sunday'),
    ], string='Delivery Day')


class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'
    delivery_days = fields.Selection([
        ('mon', 'Monday'),
        ('tue', 'Tuesday'),
        ('wed', 'Wednesday'),
        ('thu', 'Thursday'),
        ('fri', 'Friday'),
        ('sat', 'Saturday'),
        ('sun', 'Sunday'),
    ], string='Delivery Days')
