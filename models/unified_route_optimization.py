# -*- coding: utf-8 -*-
# unified_route_optimization.py
import logging
import json
import math
from datetime import datetime, date, time, timedelta
import pytz
import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class UnifiedRouteStep(models.Model):
    _name = 'route.unified.step'
    _description = 'Unified Route Step'
    _inherit = ['mail.thread']

    active = fields.Boolean(default=True)
    vehicle_id = fields.Many2one('fleet.vehicle', string='Vehicle')
    route_sequence = fields.Integer(string='Route Sequence')
    step_type = fields.Selection([
        ('start', 'Start'),
        ('job', 'Job'),
        ('end', 'End')
    ], string='Step Type')
    delivery_order_id = fields.Many2one('stock.picking', string='Delivery Order')
    task_id = fields.Many2one('project.task', string='Field Service Task')
    planned_date_begin = fields.Datetime(string='Planned Start')
    travel_time = fields.Float(string='Drive Time (min)')
    distance_km = fields.Float(string='Distance (km)')

    # Coordinates for either the customer or the vehicle (for start/end)
    partner_latitude = fields.Float('Latitude', digits=(10, 7))
    partner_longitude = fields.Float('Longitude', digits=(10, 7))

    partner_id = fields.Many2one('res.partner', string='Partner')
    driver_name = fields.Char(string='Driver')
    display_name = fields.Char(string='Display Name')
    delivery_address = fields.Char(string='Delivery Address')
    delivery_date = fields.Datetime(string='Delivery Date')

class UnifiedRouteOptimizer(models.TransientModel):
    _name = 'unified.route.optimizer'
    _description = 'Run unified route optimization'


    def _build_vehicle_data(self):
        # Determine if there are any field service jobs
        try:
            fsm_jobs = self._build_fsm_jobs()
        except Exception as e:
            _logger.error("Error fetching FSM jobs in _build_vehicle_data: %s", e)
            fsm_jobs = []
        has_fsm = bool(fsm_jobs)
    
        vehicles = self.env['fleet.vehicle'].sudo().search([])
        vehicle_data = []
    
        user_tz_name = self.env.user.tz or 'UTC'
        user_tz = pytz.timezone(user_tz_name)
        utc = pytz.UTC

        # Helper: accept float/int, str "HH:MM[:SS]" or datetime.time → (h, m, s)
        def parse_time_field(val):
            if isinstance(val, (float, int)):
                h = int(val)
                m = int((val % 1) * 60)
                s = int(((val * 3600) % 60))
            elif isinstance(val, str):
                parts = val.split(':')
                h = int(parts[0])
                m = int(parts[1]) if len(parts) > 1 else 0
                s = int(parts[2]) if len(parts) > 2 else 0
            elif hasattr(val, 'hour'):
                h, m, s = val.hour, val.minute, getattr(val, 'second', 0)
            else:
                raise ValueError(f"Unsupported time value: {val!r}")
            return h, m, s
    
        for vehicle in vehicles:
            # If there are FSM jobs, enforce that driver has 'Technician' tag
            if has_fsm:
                driver = vehicle.driver_id
                if not driver:
                    _logger.warning(
                        "Skipping vehicle %s: no driver assigned, required 'Technician' for FSM",
                        vehicle.name
                    )
                    continue
                tag_names = driver.category_id.mapped('name')
                if 'Technician' not in tag_names:
                    _logger.warning(
                        "Skipping vehicle %s: driver %s lacks 'Technician' tag (has %s)",
                        vehicle.name, driver.name, tag_names
                    )
                    continue
    
            # Skip if no valid coordinates
            if not (vehicle.latitude and vehicle.longitude):
                continue
            try:
                lat = float(vehicle.latitude)
                lon = float(vehicle.longitude)
            except ValueError:
                _logger.error(
                    'Invalid location for vehicle %s: %s, %s',
                    vehicle.name, vehicle.latitude, vehicle.longitude
                )
                continue
    
            vdict = {
                'id': vehicle.id,
                'vehicle_name': vehicle.name,
                'start': [lon, lat],
                'end': [lon, lat],
            }
    
            # cost_type / cost_value
            if vehicle.cost_type and vehicle.cost_value and vehicle.cost_value != 0:
                cv = int(vehicle.cost_value)
                if vehicle.cost_type == 'fixed':
                    vdict['fixed_cost'] = cv
                elif vehicle.cost_type == 'perhour':
                    vdict['cost_per_hour'] = cv
                elif vehicle.cost_type == 'per km':
                    vdict['cost_per_distance'] = cv
    
            # skills
            if vehicle.skills and vehicle.skills.strip():
                try:
                    skill_list = [
                        int(s.strip())
                        for s in vehicle.skills.split(',')
                        if s.strip()
                    ]
                    if skill_list:
                        vdict['skills'] = skill_list
                except ValueError:
                    _logger.error(
                        'Invalid skills value for vehicle %s: %s',
                        vehicle.name, vehicle.skills
                    )
    
            # type
            if vehicle.type and vehicle.type.strip():
                vdict['type'] = vehicle.type.strip().lower()
    
            # working hours (parse any format) → time_window
            if vehicle.working_hours_start and vehicle.working_hours_end:
                hs, ms, ss = parse_time_field(vehicle.working_hours_start)
                he, me, se = parse_time_field(vehicle.working_hours_end)
                today_local = datetime.now(user_tz).date()
                local_start = datetime.combine(today_local, time(hs, ms, ss))
                local_end   = datetime.combine(today_local, time(he, me, se))
                start_utc = user_tz.localize(local_start).astimezone(utc)
                end_utc   = user_tz.localize(local_end).  astimezone(utc)
                vdict['time_window'] = [
                    int(start_utc.timestamp()),
                    int(end_utc.timestamp())
                ]
    
            # breaks (parse any format) → breaks only if positive duration
            if vehicle.break_start and vehicle.break_end:
                bs_h, bs_m, bs_s = parse_time_field(vehicle.break_start)
                be_h, be_m, be_s = parse_time_field(vehicle.break_end)
                start_secs = bs_h * 3600 + bs_m * 60 + bs_s
                end_secs   = be_h * 3600 + be_m * 60 + be_s
                if end_secs > start_secs:
                    today_local = datetime.now(user_tz).date()
                    b_start = datetime.combine(today_local, time(bs_h, bs_m, bs_s))
                    b_end   = datetime.combine(today_local, time(be_h, be_m, be_s))
                    bstart_utc = user_tz.localize(b_start).astimezone(utc)
                    bend_utc   = user_tz.localize(b_end).  astimezone(utc)
                    vdict['breaks'] = [{
                        'id': vehicle.id,
                        'time_windows': [[
                            int(bstart_utc.timestamp()),
                            int(bend_utc.timestamp())
                        ]],
                        'service': end_secs - start_secs,
                    }]
    
            # speed_factor
            if vehicle.speed_factor and vehicle.speed_factor != 'normal':
                sf_map = {
                    'slow': 2,
                    'fast': 3,
                    'very_fast': 4,
                    'extremely_fast': 5,
                }
                sf_value = sf_map.get(vehicle.speed_factor)
                if sf_value:
                    vdict['speed_factor'] = sf_value
    
            # max_tasks
            if vehicle.max_tasks and vehicle.max_tasks != 0:
                vdict['max_tasks'] = int(vehicle.max_tasks)
    
            # max_travel_time
            if vehicle.max_travel_time and vehicle.max_travel_time != 0.0:
                vdict['max_travel_time'] = int(vehicle.max_travel_time)
    
            # max_distance
            if vehicle.max_distance and vehicle.max_distance != 0.0:
                vdict['max_distance'] = int(vehicle.max_distance)
    
            vehicle_data.append(vdict)
    
        return vehicle_data


    def _build_traktop_jobs(self):
        return self.env['route.planing'].sudo().fetch_jobs_data()

    def _build_fsm_jobs(self):
        closed_stages = self.env['project.task.type'].search([('fold', '=', True)])

        tasks = self.env['project.task'].sudo().search([
            ('stage_id', 'not in', closed_stages.ids),
            ('partner_id', '!=', False),
            ('partner_id.partner_latitude', '!=', 0),
            ('partner_id.partner_longitude', '!=', 0)
        ])
        _logger.info('build_fsm_jobs: Found %s schedulable Field Service tasks', len(tasks))

        user_tz_name = self.env.user.tz or 'UTC'
        user_tz = pytz.timezone(user_tz_name)
        utc = pytz.UTC

        job_data = []
        for task in tasks:
            partner = task.partner_id
            service_secs = int((task.allocated_hours or 0.5) * 3600)
            base_date = task.date_deadline or date.today()
            local_start = datetime.combine(base_date, time(8, 0))
            local_end = datetime.combine(base_date, time(18, 0))
            start_utc = user_tz.localize(local_start).astimezone(utc)
            end_utc = user_tz.localize(local_end).astimezone(utc)
            time_windows = [[int(start_utc.timestamp()), int(end_utc.timestamp())]]

            job_data.append({
                'id': task.id,
                'oid': task.name,
                'user_id': str(partner.id),
                'location': [partner.partner_longitude, partner.partner_latitude],
                'service': service_secs,
                'time_windows': time_windows,
            })

        return job_data

    def _call_vroom(self, vehicles, jobs):
        vroom_url = "https://optimize.trakop.com/"
        apikey = self.env['ir.config_parameter'].sudo().get_param('mss_route_plan.route_api')

        payload = {
            'vehicles': vehicles,
            'jobs': jobs,
            'options': {'g': True},
        }
        headers = {'Content-Type': 'application/json'}
        if apikey:
            headers['apikey'] = apikey

        _logger.info('Unified → Sending payload to Routing API: %s', json.dumps(payload, indent=2))
        response = requests.post(vroom_url, json=payload, headers=headers, timeout=600)
        data = response.json()

        if data.get('message') == 'API rate limit exceeded':
            _logger.error('API rate limit exceeded. Request ID: %s', data.get('request_id'))
            return {'rate_limited': True}

        response.raise_for_status()
        _logger.info('Unified → VROOM response: %s', json.dumps(data, indent=2))
        return data

    @api.model
    def action_run_unified_optimization(self):
        try:
            vehicles = self._build_vehicle_data()
            jobs_trak = self._build_traktop_jobs()
            jobs_fsm = self._build_fsm_jobs()

            job_source = {j['id']: 'picking' for j in jobs_trak}
            job_source.update({j['id']: 'task' for j in jobs_fsm})
            jobs = jobs_trak + jobs_fsm

            if not jobs:
                raise UserError(_('No jobs to optimize.'))
            if not vehicles:
                raise UserError(_('No vehicles with valid coordinates found.'))

            result = self._call_vroom(vehicles, jobs)
            if result.get('rate_limited'):
                return {
                    'type': 'ir.actions.act_window',
                    'res_model': 'api.limit.popup',
                    'view_mode': 'form',
                    'target': 'new',
                    'name': 'API Limit Reached',
                    'view_id': self.env.ref('mss_route_plan.view_api_limit_popup').id,
                }

            routes = result.get('routes', [])
            unassigned = result.get('unassigned', [])
            if unassigned:
                _logger.warning('Unified → %s jobs were unassigned', len(unassigned))

            self.env['route.unified.step'].sudo().search([]).unlink()

            utc = pytz.UTC
            for route in routes:
                vehicle = self.env['fleet.vehicle'].browse(route.get('vehicle'))
                if not vehicle:
                    continue
                cum_dur = 0
                cum_dist = 0
                for seq, step in enumerate(route.get('steps', [])):
                    vals = {
                        'vehicle_id': vehicle.id,
                        'route_sequence': seq,
                        'step_type': step.get('type'),
                        'driver_name': vehicle.driver_id.name if vehicle.driver_id else '',
                    }
                    if step.get('type') == 'job':
                        job_id = step.get('job')
                        arrival = datetime.fromtimestamp(step.get('arrival'), tz=utc)
                        planned = fields.Datetime.to_string(arrival)
                        dur = step.get('duration', 0)
                        dist = step.get('distance', 0)
                        cum_dur += dur
                        cum_dist += dist
                        if job_source.get(job_id) == 'picking':
                            picking = self.env['stock.picking'].browse(job_id)
                            picking.sudo().write({'scheduled_date': planned})
                            if picking.sale_id:
                                picking.sale_id.sudo().write({'commitment_date': planned})
                            
                            # 🔧 NEW: Update related Route Planing record
                            trak_rec = self.env['route.planing'].sudo().search([('delivery_order_id', '=', picking.id)], limit=1)
                            if trak_rec:
                                trak_rec.sudo().write({
                                    'delivery_date': planned,
                                    'travel_time': cum_dur / 60.0,
                                    'distance_km': cum_dist / 1000.0,
                                    'vehicle_id': vehicle.id,
                                    'manual_vehicle_override': False,  # Optional: reset override
                                })
                            
                            partner = picking.partner_id
                            if partner:
                                address_parts = [partner.street, partner.street2, partner.city, partner.zip, partner.state_id.name, partner.country_id.name]
                                address = ', '.join(filter(None, address_parts))
                            vals.update({
                                'delivery_order_id': picking.id,
                                'planned_date_begin': planned,
                                'travel_time': cum_dur / 60.0,
                                'distance_km': cum_dist / 1000.0,
                                'partner_id': partner.id if partner else False,
                                'partner_latitude': partner.partner_latitude if partner else 0.0,
                                'partner_longitude': partner.partner_longitude if partner else 0.0,
                                'display_name': f"{(partner.name or '').upper()} - {picking.name}",
                                'delivery_date': planned,
                                'delivery_address': address,
                            })
 
 
                        else:
                            task = self.env['project.task'].browse(job_id)
                            driver_user = self.env['res.users'].search(
                                [('partner_id', '=', vehicle.driver_id.id)], limit=1)
                            task_vals = {
                                'planned_date_begin': planned,
                                'vehicle_id': vehicle.id,
                                'travel_time': dur / 60.0,
                                'distance_km': dist / 1000.0,
                            }
                            if driver_user:
                                task_vals['user_ids'] = [(6, 0, [driver_user.id])]
                            task.write(task_vals)
                            partner = task.partner_id
                            address = ''
                            if partner:
                                address_parts = [partner.street, partner.street2, partner.city, partner.zip, partner.state_id.name, partner.country_id.name]
                                address = ', '.join(filter(None, address_parts))
                            vals.update({
                                'task_id': task.id,
                                'planned_date_begin': planned,
                                'travel_time': cum_dur / 60.0,
                                'distance_km': cum_dist / 1000.0,
                                'partner_id': partner.id if partner else False,
                                'partner_latitude': partner.partner_latitude if partner else 0.0,
                                'partner_longitude': partner.partner_longitude if partner else 0.0,
                                'display_name': f"{(partner.name or '').upper()} - {task.name}",
                                'delivery_date': planned,
                                'delivery_address': address,
                            })
                    else:
                        # start or end step
                        vals.update({
                            'partner_id': vehicle.driver_id.id if vehicle.driver_id else False,
                            'partner_latitude': float(vehicle.latitude or 0.0),
                            'partner_longitude': float(vehicle.longitude or 0.0),
                            'display_name': f"{step.get('type').capitalize()} - {vehicle.name}",
                        })
                    self.env['route.unified.step'].create(vals)

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success'),
                    'message': _('Unified route optimization complete.'),
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.client', 'tag': 'reload'},
                },
            }
        except Exception as e:
            _logger.exception('Unified → Error during optimization')
            raise UserError(_('Error during unified optimization: %s') % e)