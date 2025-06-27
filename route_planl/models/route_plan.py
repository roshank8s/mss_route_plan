from datetime import datetime
from odoo import api, fields, models, _


WEEKDAY_SELECTION = [
    ('mon', 'Monday'),
    ('tue', 'Tuesday'),
    ('wed', 'Wednesday'),
    ('thu', 'Thursday'),
    ('fri', 'Friday'),
    ('sat', 'Saturday'),
    ('sun', 'Sunday'),
]


class ResPartner(models.Model):
    _inherit = 'res.partner'

    delivery_day = fields.Selection(
        selection=WEEKDAY_SELECTION,
        string='Delivery Day'
    )


class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'

    delivery_days = fields.Selection(
        selection=WEEKDAY_SELECTION,
        string='Delivery Days',
        multiple=True
    )


class RoutePlan(models.Model):
    _name = 'route.plan'
    _description = 'Route Plan'

    name = fields.Char(default=lambda self: _('Route Plan for %s') % fields.Date.today())
    date = fields.Date(default=lambda self: fields.Date.context_today(self))
    line_ids = fields.One2many('route.plan.line', 'route_plan_id', string='Lines')

    def _today_weekday_value(self):
        weekday_index = fields.Date.from_string(fields.Date.context_today(self)).weekday()
        return WEEKDAY_SELECTION[weekday_index][0]

    def action_populate_lines(self):
        today = fields.Date.context_today(self)
        weekday_val = self._today_weekday_value()
        partners = self.env['res.partner'].search([('delivery_day', '=', weekday_val)])
        SaleOrder = self.env['sale.order']
        for partner in partners:
            sale_order = SaleOrder.search([
                ('partner_id', '=', partner.id),
                ('state', 'in', ['sale', 'done']),
                ('commitment_date', '>=', datetime.combine(today, datetime.min.time())),
                ('commitment_date', '<', datetime.combine(today, datetime.max.time())),
            ], limit=1)
            if sale_order:
                self.env['route.plan.line'].create({
                    'route_plan_id': self.id,
                    'partner_id': partner.id,
                    'sale_order_id': sale_order.id,
                })

    def action_assign_vehicles(self):
        weekday_val = self._today_weekday_value()
        vehicles = self.env['fleet.vehicle'].search([('delivery_days', 'in', [weekday_val])])
        for line in self.line_ids:
            for vehicle in vehicles:
                line.vehicle_id = vehicle
                break

    @api.model
    def cron_create_and_populate(self):
        today = fields.Date.context_today(self)
        plan = self.search([('date', '=', today)], limit=1)
        if not plan:
            plan = self.create({'date': today})
        plan.action_populate_lines()


class RoutePlanLine(models.Model):
    _name = 'route.plan.line'
    _description = 'Route Plan Line'

    route_plan_id = fields.Many2one('route.plan', string='Route Plan', ondelete='cascade')
    partner_id = fields.Many2one('res.partner', string='Customer')
    sale_order_id = fields.Many2one('sale.order', string='Sale Order')
    vehicle_id = fields.Many2one('fleet.vehicle', string='Vehicle')

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    route_plan_line_id = fields.Many2one('route.plan.line', compute='_compute_route_plan_line', string='Route Plan Line', store=False)
    route_plan_id = fields.Many2one('route.plan', related='route_plan_line_id.route_plan_id', string='Route Plan', store=False)
    vehicle_id = fields.Many2one('fleet.vehicle', related='route_plan_line_id.vehicle_id', string='Vehicle', store=False)

    def _compute_route_plan_line(self):
        for order in self:
            line = self.env['route.plan.line'].search([('sale_order_id', '=', order.id)], limit=1)
            order.route_plan_line_id = line
