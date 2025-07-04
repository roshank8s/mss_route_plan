# -*- coding: utf-8 -*-
from datetime import date, timedelta
from odoo import api, fields, models
import logging
_logger = logging.getLogger(__name__)

class FleetVehicleWeeklyOrders(models.Model):
    _inherit = 'fleet.vehicle'

    weight_fill_pct = fields.Float(
        string="Weight Fill",
        digits=(5, 2),
        compute="_compute_capacity_fill_pct",
        store=True,
    )
    volume_fill_pct = fields.Float(
        string="Volume Fill",
        digits=(5, 2),
        compute="_compute_capacity_fill_pct",
        store=True,
    )
    is_today_delivery = fields.Boolean(
        string="Delivering Today",
        compute='_compute_is_today_delivery',
        store=True,
    )
         # 1) One2many back to your route.planing stops
    route_planning_ids = fields.One2many(
        'route.planing', 'vehicle_id',
        string="Assigned Route Stops",
    )
 
    # 2a) Total assigned jobs
    total_job_count = fields.Integer(
        string="Total Jobs Assigned",
        compute='_compute_total_job_count',
        store=True,
    )
    # 2b) Today’s assigned jobs
    today_job_count = fields.Integer(
        string="Jobs Assigned Today",
        compute='_compute_today_job_count',
        store=True,
    )
    # 2c) This week’s assigned jobs
    week_job_count = fields.Integer(
        string="Jobs Assigned This Week",
        compute='_compute_week_job_count',
        store=True,
    )

    job_action_html = fields.Html(
        string="Action",
        compute="_compute_job_action_html",
        sanitize=False,
    )
    weight_fill_display = fields.Char(
        string="Weight(%)",
        compute="_compute_capacity_fill_display",
        store=False,
    )
    volume_fill_display = fields.Char(
        string="Volume(%)",
        compute="_compute_capacity_fill_display",
        store=False,
    )

    @api.depends('weight_fill_pct', 'volume_fill_pct')
    def _compute_capacity_fill_display(self):
        for rec in self:
            rec.weight_fill_display = f"{rec.weight_fill_pct:.2f}%"
        rec.volume_fill_display = f"{rec.volume_fill_pct:.2f}%"
    @api.depends('route_planning_ids', 'route_planning_ids.delivery_order_id')  # you can narrow that to only delivery_date if you like
    def _compute_capacity_fill_pct(self):
        for vehicle in self:
            # collect all the picking IDs you care about – here we just use your assigned stops
            picking_ids = vehicle.route_planning_ids.mapped('delivery_order_id').ids
            # compute_capacity_fill returns a dict with weight_pct and volume_pct
            res = vehicle.compute_capacity_fill(picking_ids)
            vehicle.weight_fill_pct = res['weight_pct']
            vehicle.volume_fill_pct = res['volume_pct']

    @api.depends('route_planning_ids')
    def _compute_total_job_count(self):
        for vehicle in self:
            vehicle.total_job_count = len(vehicle.route_planning_ids)
    @api.depends('total_job_count')
    def _compute_job_action_html(self):
        for rec in self:
            if rec.total_job_count == 0:
                url = f"/web#action=mss_route_plan.action_assign_route_wizard&active_id={rec.id}&model=fleet.vehicle&view_type=form&view_mode=form"
                rec.job_action_html = (
                    f'<a href="{url}"><strong style="color:#17a2b8;">Assign Jobs</strong></a>'
                )
            else:
                url = f"/web#action=mss_route_plan.action_see_jobs&active_id={rec.id}&model=fleet.vehicle"
                rec.job_action_html = (
                    f'<a href="{url}"><strong style="color:#17a2b8;">{rec.total_job_count} jobs</strong></a>'
                )
 
    @api.depends('route_planning_ids.delivery_date')
    def _compute_today_job_count(self):
        today = fields.Date.context_today(self)
        for vehicle in self:
            vehicle.today_job_count = sum(
                1 for stop in vehicle.route_planning_ids
                if stop.delivery_date and
                   fields.Datetime.from_string(stop.delivery_date).date() == today
            )
 
    @api.depends('route_planning_ids.delivery_date')
    def _compute_week_job_count(self):
        today = fields.Date.context_today(self)
        week_end = today + timedelta(days=6)
        for vehicle in self:
            vehicle.week_job_count = sum(
                1 for stop in vehicle.route_planning_ids
                if stop.delivery_date and
                   today <= fields.Datetime.from_string(stop.delivery_date).date() <= week_end
            )
    
    @api.depends('delivery_days')
    def _compute_is_today_delivery(self):
        """True if this vehicle’s delivery_days include today’s weekday."""
        today = date.today().strftime('%A').lower()
        for vehicle in self:
            vehicle.is_today_delivery = bool(
                vehicle.delivery_days.filtered(lambda d: d.name == today)
            )
    def action_open_assign_wizard(self):
        self.ensure_one()
        return {
            'name': 'Assign Orders',
            'type': 'ir.actions.act_window',
            'res_model': 'assign.route.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_vehicle_id': self.id},
        }

    def action_see_jobs(self):
        self.ensure_one()
        return {
            'name': 'Assigned Jobs',
            'type': 'ir.actions.act_window',
            'res_model': 'route.planing',
            'view_mode': 'list,form',
            'domain': [('vehicle_id', '=', self.id)],
            'context': {'default_vehicle_id': self.id},
            'target': 'current',
        }
    def get_weekly_orders(self):
        """
        For this vehicle, return for each of the next 7 days
        all outgoing pickings whose customer’s delivery_day matches.
        """
        self.ensure_one()
        today = fields.Date.context_today(self)
        result = []
        for offset in range(7):
            day = today + timedelta(days=offset)
            weekday = day.strftime('%A').lower()
            pickings = self.env['stock.picking'].search([
                ('state', '=', 'assigned'),
                ('picking_type_id.code', '=', 'outgoing'),
                ('partner_id.delivery_day', '=', weekday),
            ])
            result.append({
                'date':    day,
                'weekday': weekday,
                'orders':  pickings,
                'count':   len(pickings),
            })
        return result

    def calculate_fill_percentage(self, picking_ids):
        """
        Given a list or recordset of pickings, compute
        fill % based on vehicle.max_tasks capacity.
        """
        self.ensure_one()
        capacity = self.max_tasks or 1
        selected = self.env['stock.picking'].browse(picking_ids)
        num = len(selected)
        pct = (num / float(capacity)) * 100 if capacity else 0.0
        return min(100.0, pct)

    @api.model
    def _sum_picking_capacity(self, pickings):
        """
        Sum up total weight and volume from each picking's moves.
        """
        total_w = total_v = 0.0
        for pick in pickings:
            for move in pick.move_ids_without_package:
                # weight in kg, volume in m³
                total_w += (move.product_id.weight or 0.0) * move.product_uom_qty
                total_v += (move.product_id.volume or 0.0) * move.product_uom_qty
        return total_w, total_v

    def compute_capacity_fill(self, picking_ids):
        """
        Returns a dict with total weight/volume and fill % against
        the vehicle’s category max_weight and max_volume.
        """
        self.ensure_one()
        picks = self.env['stock.picking'].browse(picking_ids)
        total_w, total_v = self._sum_picking_capacity(picks)

        max_w = float(self.category_id.weight_capacity or 0.0)
        max_v = float(self.category_id.volume_capacity or 0.0)

        weight_pct = (total_w / max_w * 100.0) if max_w else 0.0
        volume_pct = (total_v / max_v * 100.0) if max_v else 0.0

        return {
            'total_weight': total_w,
            'total_volume': total_v,
            'weight_pct':   min(weight_pct, 100.0),
            'volume_pct':   min(volume_pct, 100.0),
        }

class AssignRouteWizard(models.TransientModel):
    _name = 'assign.route.wizard'
    _description = 'Assign Route Planning Orders'

    vehicle_id = fields.Many2one('fleet.vehicle', string='Vehicle', required=True)
    planing_ids = fields.Many2many('route.planing', string="Route Planings")
    delivery_date    = fields.Date('route.planing', readonly=True)
    delivery_address = fields.Char('route.planing', readonly=True)
    partner_latitude = fields.Float('route.planing',readonly=True)
    partner_longitude= fields.Float('route.planing',readonly=True)
    

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        vehicle_id = self.env.context.get('default_vehicle_id')
        res['vehicle_id'] = vehicle_id
        res['planing_ids'] = [(6, 0, self.env['route.planing'].search([('vehicle_id', '=', False)]).ids)]
        return res

    def assign_to_vehicle(self):
        for plan in self.planing_ids:
            plan.action_assign_selected(self.vehicle_id.id)
        _logger.info(f"Assigned {len(self.planing_ids)} route planning orders to vehicle {self.vehicle_id.name}")   
        # Close the wizard after assignment
        return {'type': 'ir.actions.act_window_close',
                'next': {
                            'type': 'ir.actions.act_window_close',
                            'tag': 'reload',
                        }
        }
 