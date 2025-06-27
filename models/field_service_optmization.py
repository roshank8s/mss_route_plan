# -*- coding: utf-8 -*-

# field_service_optimization.py
import pytz
import requests
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError
import logging
import json
from datetime import datetime, time, date
from collections import defaultdict

_logger = logging.getLogger(__name__)

#########################################################
# Field Service Route Step Model - For Visualizing Routes
#########################################################

class FieldServiceRouteStep(models.Model):
    _name = 'field.service.route.step'
    _description = 'Field Service Route Step'
    _inherit = ['mail.thread']

    active = fields.Boolean(string="Active", default=True)
    task_id = fields.Many2one('project.task', string="Field Service Task")
    service_duration_minutes = fields.Integer(
        string="Service Duration (min)",
        help="Service time inherited from the related Field Service Task's allocated hours."
    )
    partner_id = fields.Many2one(
        'res.partner',
        string="Customer",
        related='task_id.partner_id',
        store=True,
    )
    # ← CHANGED: pull from partner.address
    task_address = fields.Char(
        string="Service Address",
        related='task_id.partner_id.address',
        store=True,
    )
    partner_latitude = fields.Float('Latitude', digits=(10, 7), store=True)
    partner_longitude = fields.Float('Longitude', digits=(10, 7), store=True)

    planned_date_begin = fields.Datetime(string='Planned Start Date')

    vehicle_id = fields.Many2one('fleet.vehicle', string="Vehicle")
    vehicle_name = fields.Char(string="Vehicle Name", related='vehicle_id.name', store=True)
    display_name = fields.Char(string="Display Name", compute="_compute_display_name", store=True)
    vehicle_starting_point = fields.Char(string="Starting Point", compute="_compute_vehicle_address")
    driver_name = fields.Char(string="Driver", compute="_compute_driver_name", store=True)

    route_id = fields.Integer("Route ID")
    route_sequence = fields.Integer("Route Sequence")
    _order = 'route_id, route_sequence, id'

    step_type = fields.Selection(
        [('start', 'Start'), ('job', 'Job'), ('end', 'End')],
        string="Step Type"
    )

    travel_time = fields.Float(
        string="Drive Time (min)",
        digits=(12, 2),
        help="Accumulated driving minutes up to this stop"
    )
    distance_km = fields.Float(
        string="Distance (km)",
        digits=(12, 2),
        help="Accumulated kilometers up to this stop"
    )

    info_message = fields.Html(string="Info", compute='_compute_info_message', sanitize=False)
    delivery_address = fields.Char(
        string="Delivery Address",
        related='task_id.delivery_address',
        store=True,
    )
    @api.model
    def get_google_map_api_key(self):
        # Use sudo() to bypass access restrictions
        return self.env['ir.config_parameter'].sudo().get_param(
            "address_autocomplete_gmap_widget.google_map_api_key"
        )
    @api.model
    def is_field_service_manager(self):
        """
        Checks if the current user has Field Service Manager rights.
        This is a more robust security check than a generic 'is_admin'.
        """
        return self.env.user.has_group('industry_fsm.group_fsm_manager')
    @api.depends()
    def _compute_info_message(self):
        for rec in self:
            rec.info_message = """
                <div style="padding: 10px; background: #e6f7ff; border-left: 4px solid #1890ff; font-size: 14px;">
                    <strong>Info:</strong> These are filtered field service tasks. Group by <i>Vehicle</i> for better route planning.
                </div>
            """

    @api.depends('partner_id.name', 'task_id.name')
    def _compute_display_name(self):
        for record in self:
            partner_name = record.partner_id.name.upper() if record.partner_id else 'START/END'
            task_name = record.task_id.name if record.task_id else record.vehicle_name
            if record.task_id:
                task_url = f"/web#id={record.task_id.id}&model=project.task&view_type=form"
                record.display_name = f'<a href="{task_url}" target="_blank">{partner_name} - {task_name}</a>'
            else:
                record.display_name = f"{partner_name} - {task_name}"

    def action_view_task(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Field Service Task',
            'res_model': 'project.task',
            'view_mode': 'form',
            'res_id': self.task_id.id,
            'target': 'current',
        }

    @api.depends('vehicle_id')
    def _compute_driver_name(self):
        for record in self:
            record.driver_name = record.vehicle_id.driver_id.name if record.vehicle_id.driver_id else ''

    @api.depends('vehicle_id.address')
    def _compute_vehicle_address(self):
        for record in self:
            record.vehicle_starting_point = record.vehicle_id.address if record.vehicle_id else ''

    @api.model
    def fetch_vehicle_data(self):
        """
        Build a VROOM‐style list of vehicle dicts, but only for vehicles whose
        driver is tagged exactly "Technician" in their contact tags.
        """
        _logger.info("Starting fetch_vehicle_data()")
        vehicles = self.env['fleet.vehicle'].sudo().search([])
        vehicle_data = []
 
        user_tz_name = self.env.user.tz or 'UTC'
        user_tz = pytz.timezone(user_tz_name)
        utc = pytz.UTC
 
        for vehicle in vehicles:
            _logger.debug("Evaluating vehicle %s (ID %s)", vehicle.name, vehicle.id)
 
            # 1) skip if no driver
            if not vehicle.driver_id:
                _logger.warning("Skipping vehicle %s: no driver assigned", vehicle.name)
                continue
 
            # 2) skip if driver has no tag named "Technician"
            tag_names = vehicle.driver_id.category_id.mapped('name')
            if 'Technician' not in tag_names:
                _logger.warning(
                    "Skipping vehicle %s: driver %s lacks 'Technician' tag (has %s)",
                    vehicle.name, vehicle.driver_id.name, tag_names
                )
                continue
 
            # 3) skip if invalid coords
            if not (vehicle.latitude and vehicle.longitude):
                _logger.warning("Skipping vehicle %s: missing latitude/longitude", vehicle.name)
                continue
            try:
                lat = float(vehicle.latitude)
                lon = float(vehicle.longitude)
            except (ValueError, TypeError):
                _logger.error(
                    "Skipping vehicle %s: invalid coords %r, %r",
                    vehicle.name, vehicle.latitude, vehicle.longitude
                )
                continue
 
            # Build the entry
            vdict = {
                "id": vehicle.id,
                "vehicle_name": vehicle.name,
                "start": [lon, lat],
                "end":   [lon, lat],
            }
 
            # Cost
            if vehicle.cost_type and vehicle.cost_value:
                if vehicle.cost_type == 'fixed':
                    vdict["fixed_cost"] = int(vehicle.cost_value)
                elif vehicle.cost_type == 'perhour':
                    vdict["cost_per_hour"] = int(vehicle.cost_value)
                elif vehicle.cost_type == 'per km':
                    vdict["cost_per_distance"] = int(vehicle.cost_value)
 
            # Skills
            if vehicle.skills and vehicle.skills.strip():
                try:
                    skill_list = [int(s.strip()) for s in vehicle.skills.split(',') if s.strip()]
                    if skill_list:
                        vdict["skills"] = skill_list
                except ValueError:
                    _logger.error("Invalid skills for vehicle %s: %s", vehicle.name, vehicle.skills)
 
            # Type
            if vehicle.type and vehicle.type.strip():
                vdict["type"] = vehicle.type.strip().lower()
 
            # Time window
            if vehicle.working_hours_start and vehicle.working_hours_end:
                try:
                    today = datetime.now(user_tz).date()
                    sh, sm = map(int, vehicle.working_hours_start.split(':'))
                    eh, em = map(int, vehicle.working_hours_end.split(':'))
                    local_start = user_tz.localize(datetime.combine(today, time(sh, sm)))
                    local_end   = user_tz.localize(datetime.combine(today, time(eh, em)))
                    vdict["time_window"] = [
                        int(local_start.astimezone(utc).timestamp()),
                        int(local_end.astimezone(utc).timestamp()),
                    ]
                except Exception:
                    _logger.warning("Could not parse working hours for %s", vehicle.name)
 
            # Breaks
            if vehicle.break_start and vehicle.break_end:
                try:
                    today = datetime.now(user_tz).date()
                    bsh, bsm = map(int, vehicle.break_start.split(':'))
                    beh, bem = map(int, vehicle.break_end.split(':'))
                    b_start = user_tz.localize(datetime.combine(today, time(bsh, bsm)))
                    b_end   = user_tz.localize(datetime.combine(today, time(beh, bem)))
                    dur = (b_end - b_start).total_seconds()
                    vdict["breaks"] = [{
                        "id": vehicle.id,
                        "time_windows": [[
                            int(b_start.astimezone(utc).timestamp()),
                            int(b_end.astimezone(utc).timestamp())
                        ]],
                        "service": int(dur)
                    }]
                except Exception:
                    _logger.warning("Could not parse breaks for %s", vehicle.name)
 
            # Other constraints
            if vehicle.speed_factor and vehicle.speed_factor != '1':
                vdict["speed_factor"] = int(vehicle.speed_factor)
            if vehicle.max_tasks:
                vdict["max_tasks"] = vehicle.max_tasks
            if vehicle.max_travel_time:
                vdict["max_travel_time"] = int(vehicle.max_travel_time * 3600)
            if vehicle.max_distance:
                vdict["max_distance"] = int(vehicle.max_distance * 1000)
 
            vehicle_data.append(vdict)
            _logger.info("Included vehicle %s (ID %s) for routing", vehicle.name, vehicle.id)
 
        _logger.info("fetch_vehicle_data: prepared %d vehicles for routing", len(vehicle_data))
        return vehicle_data
 
    @api.model
    def fetch_jobs_data(self):
        # Odoo 18+: use fold instead of removed is_closed
        closed_stages = self.env['project.task.type'].search([('fold', '=', True)])

        tasks = self.env['project.task'].sudo().search([
            ('stage_id', 'not in', closed_stages.ids),
            ('partner_id', '!=', False),
            ('partner_id.partner_latitude', '!=', 0),
            ('partner_id.partner_longitude', '!=', 0)
        ])
        _logger.info(f"fetch_jobs_data: Found {len(tasks)} schedulable Field Service tasks")

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
                "id":           task.id,
                "oid":          task.name,
                "user_id":      str(partner.id),
                "location":     [partner.partner_longitude, partner.partner_latitude],
                "service":      service_secs,
                "time_windows": time_windows,
            })
        return job_data

    @api.model
    def integrate_vroom(self):
        vroom_url = "https://optimize.trakop.com/"
        apikey = self.env['ir.config_parameter'].sudo().get_param('mss_route_optimization.route_api')

        vehicles = self.fetch_vehicle_data()
        jobs = self.fetch_jobs_data()

        if not jobs:
            raise UserError(_("No schedulable tasks with valid addresses found. Nothing to optimize."))
        if not vehicles:
            raise UserError(_("No vehicles with valid starting locations found. Please configure your vehicles."))

        payload = {"vehicles": vehicles, "jobs": jobs, "options": {"g": True}}
        headers = {'Content-Type': 'application/json'}
        if apikey:
            headers['apikey'] = apikey

        try:
            _logger.info(f"Sending payload to Routing API: {json.dumps(payload, indent=2)}")
            response = requests.post(vroom_url, json=payload, headers=headers, timeout=600)
            response_data = response.json()

            if response_data.get("message") == "API rate limit exceeded":
                _logger.error(f"API rate limit exceeded. Request ID: {response_data.get('request_id')}")
                return {"rate_limited": True}

            response.raise_for_status()
            _logger.info(f"VROOM response: {json.dumps(response_data, indent=2)}")
            return response_data

        except requests.exceptions.RequestException as e:
            _logger.error(f"Error connecting to Routing API: {e}")
            _logger.error(f"Payload sent: {json.dumps(payload, indent=2)}")
            if 'response' in locals():
                _logger.error(f"Response content: {response.text}")
            raise UserError(_(
                "Error connecting to the Routing API. Please check the service URL, API key,"
                " and that all tasks/vehicles have valid latitude and longitude."
            ))

    @api.model
    def get_optimized_routes(self):
        try:
            _logger.info("Starting Field Service Route Optimization")
            optimized_data = self.integrate_vroom()

            if optimized_data.get("rate_limited"):
                return {
                    'type': 'ir.actions.act_window',
                    'res_model': 'api.limit.popup',
                    'view_mode': 'form',
                    'target': 'new',
                    'name': 'API Limit Reached',
                    'view_id': self.env.ref('mss_route_optimization.view_api_limit_popup').id,
                }

            routes = optimized_data.get("routes", [])
            unassigned = optimized_data.get("unassigned", [])
            _logger.info(f"VROOM → got {len(routes)} routes and {len(unassigned)} unassigned tasks")

            # Remove old auto-generated steps
            self.search([]).unlink()

            for route_idx, route in enumerate(routes):
                vehicle = self.env['fleet.vehicle'].browse(route.get("vehicle"))
                if not vehicle:
                    continue

                cum_dur = 0
                cum_dist = 0

                for seq, step in enumerate(route.get("steps", [])):
                    vals = {
                        "vehicle_id": vehicle.id,
                        "route_id": route_idx + 1,
                        "route_sequence": seq,
                        "step_type": step.get("type"),
                    }

                    if step["type"] in ("start", "end"):
                        vals.update({
                            "partner_id": vehicle.driver_id.id if vehicle.driver_id else False,
                            "partner_latitude": float(vehicle.latitude) or 0.0,
                            "partner_longitude": float(vehicle.longitude) or 0.0,
                        })

                    elif step["type"] == "job":
                        task = self.env['project.task'].sudo().browse(step.get("job"))
                        if not task:
                            continue

                        cum_dur += step.get('duration', 0)
                        cum_dist += step.get('distance', 0)

                        arrival = datetime.fromtimestamp(step.get('arrival'), tz=pytz.UTC)
                        planned = fields.Datetime.to_string(arrival)

                        driver_user = self.env['res.users'].search(
                            [('partner_id', '=', vehicle.driver_id.id)], limit=1
                        )
                        task_vals = {
                            'planned_date_begin': planned,
                            'vehicle_id': vehicle.id,
                            'travel_time': step.get('duration', 0) / 60.0,
                            'distance_km': step.get('distance', 0) / 1000.0,
                        }
                        if driver_user:
                            task_vals['user_ids'] = [(6, 0, [driver_user.id])]

                        task.write(task_vals)

                        vals.update({
                            "task_id": task.id,
                            "planned_date_begin": planned,
                            "partner_latitude": task.partner_id.partner_latitude,
                            "partner_longitude": task.partner_id.partner_longitude,
                            "service_duration_minutes": (task.allocated_hours or 0) * 60,
                            "travel_time": cum_dur / 60.0,
                            "distance_km": cum_dist / 1000.0,
                        })

                    self.create(vals)

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Success"),
                    "message": _("Field service routes and task schedules have been optimized."),
                    "type": "success",
                    "sticky": False,
                    "next": {"type": "ir.actions.client", "tag": "reload"},
                },
            }

        except Exception as e:
            _logger.exception("Error during field service route optimization")
            raise UserError(_(
                "An unexpected error occurred during route optimization: %s") % e
            )


###############################################################
# Extend Project Task - To Sync with Field Service Route Steps
###############################################################

class ProjectTask(models.Model):
    _inherit = 'project.task'

    travel_time = fields.Float(
        string="Drive Time (min)",
        help="Calculated travel time for this task's leg.",
        readonly=True, copy=False
    )
    distance_km = fields.Float(
        string="Distance (km)",
        help="Calculated travel distance for this task's leg.",
        readonly=True, copy=False
    )
    vehicle_id = fields.Many2one(
        'fleet.vehicle',
        string='Assigned Vehicle',
        help="Vehicle assigned by the optimization engine.",
        copy=False
    )
    delivery_address = fields.Char(
        string="Service Address",
        related='partner_id.address',
        store=True,
    )

    def _is_schedulable(self):
        self.ensure_one()
        # use the Kanban‐fold flag instead of the removed is_closed field
        return not (self.stage_id and self.stage_id.fold)

    @api.model_create_multi
    def create(self, vals_list):
        tasks = super().create(vals_list)
        for task in tasks.filtered(lambda t: t._is_schedulable()):
            self.env['field.service.route.step'].sudo().create({
                'task_id': task.id,
                'partner_id': task.partner_id.id,  # <-- ADD THIS
                'task_address': task.partner_id.address, # <-- ADD THIS
                'partner_latitude': task.partner_id.partner_latitude, # <-- ADD THIS
                'partner_longitude': task.partner_id.partner_longitude, # <-- ADD THIS
                'service_duration_minutes': (task.allocated_hours or 0) * 60,
                'planned_date_begin': task.planned_date_begin or task.date_deadline,
            })
        return tasks

    def write(self, vals):
        pre_states = {t.id: t._is_schedulable() for t in self}
        res = super().write(vals)
        for task in self:
            was = pre_states.get(task.id, False)
            now = task._is_schedulable()
            step = self.env['field.service.route.step'].sudo().search([('task_id', '=', task.id)])
            if now:
                if not was and not step:
                    self.env['field.service.route.step'].sudo().create({
                        'task_id': task.id,
                        'partner_id': task.partner_id.id,
                        'task_address': task.partner_id.address,
                        'partner_latitude': task.partner_id.partner_latitude,
                        'partner_longitude': task.partner_id.partner_longitude,
                        'service_duration_minutes': (task.allocated_hours or 0) * 60,
                        'planned_date_begin': task.planned_date_begin or task.date_deadline,
                    })
                elif step and any(k in vals for k in ('allocated_hours', 'planned_date_begin', 'partner_id')):
                    step.sudo().write({
                        'partner_id': task.partner_id.id,
                        'task_address': task.partner_id.address,
                        'partner_latitude': task.partner_id.partner_latitude,
                        'partner_longitude': task.partner_id.partner_longitude,
                        'service_duration_minutes': (task.allocated_hours or 0) * 60,
                        'planned_date_begin': task.planned_date_begin or task.date_deadline,
                    })
            else:
                if was and step:
                    step.sudo().unlink()
        return res

    def unlink(self):
        self.env['field.service.route.step'].sudo().search([('task_id', 'in', self.ids)]).unlink()
        return super().unlink()


###########################################
# Other Models (Mostly Unchanged)
###########################################

class ResPartner(models.Model):
    _inherit = 'res.partner'

    address = fields.Char(string="Address")
    longitude = fields.Char(string="Longitude")
    latitude = fields.Char(string="Latitude")

    @api.model
    def create(self, vals):
        partner = super().create(vals)
        if any(k in vals for k in ('latitude', 'longitude', 'street', 'city', 'zip', 'state_id', 'country_id')):
            partner.geo_localize()
        return partner

    def write(self, vals):
        res = super().write(vals)
        if any(k in vals for k in ('latitude', 'longitude', 'street', 'city', 'zip', 'state_id', 'country_id')):
            self.geo_localize()
        return res

    def geo_localize(self):
        for partner in self.filtered(lambda p: p.latitude and p.longitude):
            try:
                partner.partner_latitude = float(partner.latitude)
                partner.partner_longitude = float(partner.longitude)
            except (ValueError, TypeError):
                super(ResPartner, partner).geo_localize()
        return super(ResPartner, self).geo_localize()


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    route_api = fields.Char(string="Routing API Key", config_parameter="mss_route_optimization.route_api")
    # route_url = fields.Char(string="Routing API URL", config_parameter="mss_route_optimization.route_url",
    #                         default="http://solver.vroom-project.org")


class FleetVehicle(models.Model):
    _inherit = "fleet.vehicle"

    driver_id = fields.Many2one(
            'res.partner',
            string="Driver",
            domain=[('category_id.name', '=', 'Technician')],
            help="Only contacts tagged ‘Technician’ may be assigned here."
        )
    address = fields.Char(string="Address")
    longitude = fields.Char(string="Longitude")
    latitude = fields.Char(string="Latitude")
    cost_value = fields.Float(string="Cost Value")
    cost_type = fields.Selection(
        [('fixed', 'Fixed'), ('perhour', 'Per Hour'), ('per km', 'Per Km')],
        string="Cost Type"
    )
    skills = fields.Char(string="Skills", help="Comma-separated list of skill numbers, e.g., 1,5,12")
    type = fields.Char(string="Vehicle Type", help="A string describing this vehicle type for VROOM")
    working_hours_start = fields.Char(string="Working Hours Start", help="Format: HH:MM, e.g., 08:00")
    working_hours_end = fields.Char(string="Working Hours End", help="Format: HH:MM, e.g., 17:30")
    break_start = fields.Char(string="Break Start", help="Format: HH:MM, e.g., 12:00")
    break_end = fields.Char(string="Break End", help="Format: HH:MM, e.g., 12:30")
    speed_factor = fields.Selection(
        [('1', '1 (Normal)'), ('2', '2'), ('3', '3'), ('4', '4'), ('5', '5')],
        string="Speed Factor", default='1'
    )
    max_tasks = fields.Integer(string="Max Tasks", help="Max number of tasks in a route for this vehicle")
    max_travel_time = fields.Float(string="Max Travel Time (Hours)",
                                   help="Max total travel time in hours for this vehicle")
    max_distance = fields.Float(string="Max Distance (Km)",
                                help="Max total travel distance in kilometers for this vehicle")

    @api.constrains('cost_value', 'cost_type')
    def _check_cost_value(self):
        for record in self:
            if record.cost_type and not record.cost_value:
                raise ValidationError(_("Please provide a cost value for the selected cost type."))


class ApiLimitPopup(models.TransientModel):
    _name = 'api.limit.popup'
    _description = 'API Limit Popup'

    name = fields.Char(default="API Limit Reached")
    message = fields.Text(default="You have exceeded your API rate limit."
                                 " Please contact support for assistance or to upgrade your plan.")

    def action_contact(self):
        return {
            'type': 'ir.actions.act_url',
            'url': 'https://www.mastersoftwaresolutions.com/request-live-preview',
            'target': 'new',
        }
