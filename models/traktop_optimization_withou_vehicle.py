# -*- coding: utf-8 -*-
import pytz
import requests
from odoo import api, fields, models, _, _lt
from odoo.exceptions import ValidationError, UserError
import logging
import json

from datetime import datetime, time, timedelta

from collections import defaultdict
from datetime import datetime, timedelta
from odoo import api, fields, models, _, _
from odoo.exceptions import UserError
import logging
from datetime import datetime, date, time, timedelta, timezone

import math

_logger = logging.getLogger(__name__)

###########################################
# Traktop Model – Using Delivery Order Link
###########################################

class Traktop(models.Model):
    _name = 'traktop'
    _description = 'Traktop'
    _inherit = ['mail.thread']

    active = fields.Boolean(string="Active", default=True)
    
    # ─── New field to store prep/build time ────────────────────────────
    build_time = fields.Integer(
        string="Build Time (min)",
        help="Prep time inherited from the related Sale Order"
    )
    

    # Link to a confirmed delivery order (stock.picking)
    delivery_order_id = fields.Many2one('stock.picking', string="Delivery Order")
    partner_id = fields.Many2one('res.partner', string="Customer")
    delivery_address = fields.Char(string="Delivery Address")
    partner_latitude = fields.Float('Latitude', digits=(10, 7))
    partner_longitude = fields.Float('Longitude', digits=(10, 7))
    delivery_date = fields.Datetime(string='Delivery Date')
    # distance = fields.Float(string="Distance (km)")
    vehicle_id = fields.Many2one('fleet.vehicle', string="Vehicle")
    vehicle_name = fields.Char(string="Vehicle Name")
    display_name = fields.Char(string="Display Name", compute="_compute_display_name")
    vehicle_starting_point = fields.Char(string="Starting Point", compute="_compute_vehicle_address")
    driver_name = fields.Char(string="Driver", compute="_compute_driver_name", store=True)
    sequence = fields.Integer(string="Sequence", default=10)
    # _order = 'sequence'
    route_sequence = fields.Integer("Route Sequence")
    _order = 'route_sequence, id'

    # Fields for distance and travel time
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

    # Fields for routing
    route_id = fields.Integer("Route ID")
    route_sequence = fields.Integer("Route Sequence")
    step_type = fields.Selection(
        [('start', 'Start'), ('job', 'Job'), ('end', 'End')],
        string="Step Type"
    )
    

    
    # New field to allow manual override of the assigned vehicle
    manual_vehicle_override = fields.Boolean(string="Manual Vehicle Assignment", default=False)
    # product_summary = fields.Char(
    #     string="Picked Products",
    #     compute="_compute_product_summary",
    #     store=False  # You can make it stored if needed, but for display it's fine as transient
    # )

            
    # @api.depends('delivery_order_id.move_ids_without_package.picked')
    # def _compute_product_summary(self):
    #     for record in self:
    #         moves = record.delivery_order_id.move_ids_without_package
    #         total = len(moves)
    #         picked = sum(1 for m in moves if m.picked)
    #         record.product_summary = f"{picked} / {total}"

    def action_view_products(self):
        self.ensure_one()
        # Use your module’s XML‑ID here
        action = self.env.ref('mss_route_optimization.action_traktop_products').sudo().read()[0]
        action.update({
            'domain': [('picking_id', '=', self.delivery_order_id.id)],
            'context': {'default_picking_id': self.delivery_order_id.id},
        })
        return action
    
    @api.model
    def is_admin(self):
        return self.env.user.has_group("base.group_system")
    
    @api.model
    def get_google_map_api_key(self):
        # Use sudo() to bypass access restrictions
        return self.env['ir.config_parameter'].sudo().get_param(
            "address_autocomplete_gmap_widget.google_map_api_key"
        )
    
    def action_view_delivery_order(self):
        """Open the related Delivery Order form view."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Delivery Order',
            'res_model': 'stock.picking',
            'view_mode': 'form',
            'res_id': self.delivery_order_id.id,
            'target': 'current',
        }
    
    @api.depends('vehicle_id')
    def _compute_driver_name(self):
        for record in self:
            record.driver_name = record.vehicle_id.driver_id.name if record.vehicle_id.driver_id else ''
    
    @api.depends('vehicle_id')
    def _compute_vehicle_address(self):
        for record in self:
            record.vehicle_starting_point = record.vehicle_id.address if record.vehicle_id else ''
    
    @api.depends('partner_id', 'delivery_order_id')
    def _compute_display_name(self):
        for record in self:
            partner_name = record.partner_id.name.upper() if record.partner_id else ''
            order_name = record.delivery_order_id.name if record.delivery_order_id else ''
            if order_name:
                # Generate the clickable link to the Sales Order form view
                sales_order_url = "/web#id={}&model=sale.order&view_type=form".format(record.delivery_order_id.sale_id.id)
                record.display_name = f'<a href="{sales_order_url}" target="_blank">{partner_name} - {order_name}</a>'
            else:
                record.display_name = partner_name
    
    def action_view_map(self):
        self.ensure_one()
        map_view_id = self.env.ref('traktop.traktop_map_view').id
        return {
            'type': 'ir.actions.act_window',
            'name': 'Traktop Map View',
            'res_model': 'traktop',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(map_view_id, 'form')],
            'target': 'new',
        }
    
    def get_delivery_locations(self):
        locations = self.search([])
        routes = {}
        for loc in locations:
            if loc.route_id not in routes:
                routes[loc.route_id] = []
            routes[loc.route_id].append({
                "name": loc.display_name,
                "latitude": loc.partner_latitude,
                "longitude": loc.partner_longitude,
                "sequence": loc.route_sequence,
                "type": loc.step_type,
            })
        for route_id in routes:
            routes[route_id].sort(key=lambda x: x["sequence"])
        return {"routes": routes}
    
    @api.model
    def fetch_vehicle_data(self):
        vehicles = self.env['fleet.vehicle'].sudo().search([])
        vehicle_data = []
        for vehicle in vehicles:
            if vehicle.latitude and vehicle.longitude:
                try:
                    latitude = float(vehicle.latitude)
                    longitude = float(vehicle.longitude)
                    vehicle_data.append({
                        "id": vehicle.id,
                        "vehicle_name": vehicle.name,
                        "start": [longitude, latitude],
                        "end": [longitude, latitude]
                    })
                except ValueError:
                    _logger.error("Invalid location for vehicle %s: %s, %s", vehicle.name, vehicle.latitude, vehicle.longitude)
        return vehicle_data

    #############################################################################
    # ─── Integrate with VROOM API ───────────────────────────────────────────────  
    @api.model
    def integrate_vroom(self):
        vroom_url = "https://route.trakop.com:8100"
        # vroom_url = "http://solver.vroom-project.org"
        vehicles = self.fetch_vehicle_data()
        jobs = self.fetch_jobs_data()
    
        # Ensure delivery_date is properly serialized if present
        for job in jobs:
            if job.get('delivery_date'):
                job['delivery_date'] = job['delivery_date']
    
        payload = {
            "vehicles": vehicles,
            "jobs": jobs,
            "options": {"g": True},
        }
        try:
            _logger.info("Sending payload to Routing API: %s", json.dumps(payload, indent=4))
            response = requests.post(vroom_url, json=payload, timeout=30)
            response.raise_for_status()
            optimized_routes = response.json()
            _logger.info("VROOM response: %s", json.dumps(optimized_routes, indent=2))
            return optimized_routes
        except requests.exceptions.RequestException as e:
            _logger.error("Error while connecting to Routing API: %s", e)
            _logger.error("Payload sent to Routing API: %s", json.dumps(payload, indent=4))
            if 'response' in locals():
                _logger.error("Response content: %s", response.text)
            raise UserError("Error connecting to Routing API: Either partners or vehicles Latitude and Longitude are missing.")
    
    @api.model
    def action_fetch_delivery_orders(self):
        # For manual/testing – create Traktop records for delivery orders in 'assigned' state
        deliveries = self.env['stock.picking'].sudo().search([
            ('state', '=', 'assigned'),
            ('picking_type_id.code', '=', 'outgoing')
        ])
        _logger.info("action_fetch_delivery_orders: Found %s delivery orders in 'assigned' state", len(deliveries))
        existing_ids = self.search([]).mapped('delivery_order_id.id')
        for picking in deliveries:
            if picking.id not in existing_ids:
                self.create({
                    'delivery_order_id': picking.id,
                    'partner_id':        picking.partner_id.id,
                    'delivery_address':  picking.partner_id.contact_address,
                    'delivery_date':     picking.scheduled_date,
                    'partner_latitude':  picking.partner_id.partner_latitude,
                    'partner_longitude': picking.partner_id.partner_longitude,
                    # ← grab build_time off the related sale.order if any:
                    'build_time':        getattr(picking.sale_id, 'build_time', 0),
                })
                _logger.info("Created Traktop record for delivery: %s", picking.name)
        return True


    def write(self, vals):
        # Check if vehicle_id is being updated manually (without the optimization context)
        if 'vehicle_id' in vals and not self.env.context.get('from_optimization', False):
            vals['manual_vehicle_override'] = True
        return super(Traktop, self).write(vals)
    
######################################################################################
    @api.model
    def fetch_jobs_data(self):
        """
        Build a VROOM‐style payload where each job’s "time_windows" 
        covers every day from its base commitment_date out to as many 
        days as needed so that all service‐blocks can fit.

        1) Count how many vehicles we actually have (with valid lat/long).
        2) Sum up the service‐times of all pending deliveries.
        3) Compute days_needed = ceil(total_service_seconds / (num_vehicles * 36_000))
           (since each vehicle only has 10 hours = 36 000 seconds per day).
        4) For each delivery, generate time_windows = [[D0-start, D0-end], [D1-start, D1-end], … up to Dn].
        """
        # ───────────────────────────────────────────────────────────
        # 1) Gather all “assigned” outgoing pickings:
        deliveries = self.env['stock.picking'].sudo().search([
            ('state', '=', 'assigned'),
            ('picking_type_id.code', '=', 'outgoing'),
        ])
        _logger.info("fetch_jobs_data: Found %s delivery orders in 'assigned' state", len(deliveries))

        # ───────────────────────────────────────────────────────────
        # 2) Figure out how many vehicles we have with valid coordinates:
        vehicles = self.fetch_vehicle_data()
        num_vehicles = len(vehicles)
        if num_vehicles == 0:
            # If there are no vehicles, VROOM cannot assign anything;
            # just return an empty list (all jobs will be unassigned).
            _logger.warning("fetch_jobs_data: No vehicles found with valid lat/long")
            return []

        # ───────────────────────────────────────────────────────────
        # 3) Compute total service time for all deliveries (in seconds).
        total_service_secs = 0
        # Store each job’s service time so we don’t recalc in the main loop:
        service_per_pick = {}
        for pick in deliveries:
            so = pick.sale_id
            service_secs = int((so.build_time or 0) * 60)
            total_service_secs += service_secs
            service_per_pick[pick.id] = service_secs

        # Each vehicle has 10 hours = 36 000 seconds per day available (08:00–18:00).
        daily_capacity_secs = 10 * 3600  # 36,000
        # Total daily capacity = num_vehicles * 36,000
        total_daily_capacity = num_vehicles * daily_capacity_secs

        # If total_service_secs = 200 000 and total_daily_capacity = 36 000, then days_needed = ceil(200 000 / 36 000) = 6
        days_needed = int(math.ceil(total_service_secs / total_daily_capacity))
        # At minimum we need at least 1 day in case there is any work at all.
        days_needed = max(days_needed, 1)

        _logger.info(
            "fetch_jobs_data: total_service_secs=%s, num_vehicles=%s, days_needed=%s",
            total_service_secs, num_vehicles, days_needed
        )

        # ───────────────────────────────────────────────────────────
        # 4) Prepare to build each job’s multi-day time_windows
        user_tz_name = self.env.user.tz or 'UTC'
        user_tz = pytz.timezone(user_tz_name)
        utc = pytz.UTC

        job_data = []
        for pick in deliveries:
            so = pick.sale_id
            partner = pick.partner_id
            if not (partner.partner_latitude and partner.partner_longitude):
                # Skip if no valid coordinates
                continue

            # 4.a) Determine that job’s “base date” in user TZ:
            if so.commitment_date:
                # Convert commitment_date (UTC string) → aware UTC → convert to user TZ
                dt_utc = utc.localize(fields.Datetime.from_string(so.commitment_date))
                base_local = dt_utc.astimezone(user_tz)
            else:
                base_local = datetime.now(user_tz)

            # 4.b) Generate an 08:00–18:00 window for each day from 0 to days_needed−1
            time_windows = []
            for day_offset in range(days_needed):
                this_date = base_local.date() + timedelta(days=day_offset)
                local_start = datetime.combine(this_date, time(8, 0))
                local_end   = datetime.combine(this_date, time(18, 0))

                # Localize in user TZ then convert to UTC timestamps
                start_utc = user_tz.localize(local_start).astimezone(utc)
                end_utc   = user_tz.localize(local_end).astimezone(utc)

                time_windows.append([
                    int(start_utc.timestamp()),
                    int(end_utc.timestamp())
                ])

            job_data.append({
                "id":           pick.id,
                "oid":          pick.name,
                "user_id":      str(partner.id),
                "location":     [partner.partner_longitude, partner.partner_latitude],
                "service":      service_per_pick[pick.id],
                "time_windows": time_windows,
            })

        return job_data
    #############################################################################  
    @api.model
    def get_optimized_rec_created(self):
        try:
            _logger.info("VROOM → Entering get_optimized_rec_created()")

            # 1) Call VROOM exactly as before
            vehicles    = self.fetch_vehicle_data()
            job_payload = self.fetch_jobs_data()
            _logger.info("VROOM → sending payload with %d vehicles & %d jobs",
                         len(vehicles), len(job_payload))
            optimized = self.integrate_vroom()
            routes    = optimized.get("routes", [])
            _logger.info("VROOM → got %d routes back", len(routes))

            # 2) Flatten & sort all job‐steps by arrival, but capture VROOM’s 'distance' & 'duration'
            #    We will use these to compute cumulative travel_time & distance_km.
            job_steps = []
            for route in routes:
                vid = route.get("vehicle")
                total_route_metres = route.get("distance", 0)  # entire route’s distance in metres
                for step in route.get("steps", []):
                    if step.get("type") == "job" and "arrival" in step:
                        job_steps.append((vid, step))
            job_steps.sort(key=lambda x: x[1]["arrival"])
            _logger.info("VROOM → total job_steps after sort: %d", len(job_steps))

            # 3) Prepare timezone helpers + per‐vehicle accumulators
            user_tz_name = self.env.user.tz or "UTC"
            user_tz = pytz.timezone(user_tz_name)
            utc = pytz.UTC

            cursors = {}  # next‐available UTC timestamp per vehicle
            accum_secs = {}    # running sum of step["duration"] per vehicle (in seconds)

            # 4) Loop through each job step → schedule + write travel_time/distance_km on existing Traktop rec
            for vehicle_id, step in job_steps:
                pick_id = step["job"]
                picking = self.env["stock.picking"].browse(pick_id)
                if not picking:
                    _logger.warning("VROOM → missing picking %s; skipping", pick_id)
                    continue

                so = picking.sale_id
                service_secs = int((so.build_time or 0) * 60)
                _logger.info(
                    "VROOM → vehicle %s, picking %s, service=%s secs",
                    vehicle_id, picking.name, service_secs
                )

                # ─ initialize cursor & accumulators once per vehicle ─────────────
                if vehicle_id not in cursors:
                    # “Today at 08:00 local → UTC timestamp”
                    today_local = datetime.now(user_tz).date()
                    local_0800  = datetime.combine(today_local, time(8, 0))
                    utc_0800    = user_tz.localize(local_0800).astimezone(utc)
                    cursors[vehicle_id] = int(utc_0800.timestamp())
                    accum_secs[vehicle_id] = 0
                    _logger.info(
                        "VROOM → init cursor for vehicle %s = %s (UTC)",
                        vehicle_id, utc_0800
                    )

                cursor = cursors[vehicle_id]

                # ─ compute this local day’s 08:00–18:00 window in UTC ───────────
                local_day     = datetime.fromtimestamp(cursor, tz=utc).astimezone(user_tz).date()
                local_start   = datetime.combine(local_day, time(8, 0))
                local_end     = datetime.combine(local_day, time(18, 0))
                win_start_utc = int(user_tz.localize(local_start).astimezone(utc).timestamp())
                win_end_utc   = int(user_tz.localize(local_end).astimezone(utc).timestamp())

                # If before 08:00, jump to 08:00
                if cursor < win_start_utc:
                    cursor = win_start_utc
                # If it won’t fit before 18:00, roll to next day @ 08:00
                if cursor + service_secs > win_end_utc:
                    tomorrow_local = local_day + timedelta(days=1)
                    tom_0800       = datetime.combine(tomorrow_local, time(8, 0))
                    cursor = int(user_tz.localize(tom_0800).astimezone(utc).timestamp())
                    _logger.info("VROOM → rolling into next day@08:00 local → %s", tom_0800)

                # ─ schedule it at `cursor` (UTC) ────────────────────────────────
                date_dt_utc = datetime.fromtimestamp(cursor, tz=utc)
                date_str    = fields.Datetime.to_string(date_dt_utc)
                _logger.info("VROOM → scheduling pick %s at %s UTC", picking.name, date_str)

                # ─ 1) Accumulate driving seconds from step["duration"]
                leg_secs = int(step.get("duration", 0))
                accum_secs[vehicle_id] += leg_secs

                # ─ 2) Read cumulative metres from step["distance"] and convert to km
                job_metres = float(step.get("distance", 0))
                job_km     = job_metres / 1000.0

                # ─ 3) Write back to Picking.scheduled_date and SO.commitment_date
                picking.sudo().write({"scheduled_date": date_str})
                if so:
                    so.sudo().write({"commitment_date": date_str})

                # ─ 4) Update the existing Traktop record with travel_time (min) & distance_km
                tr = self.search([("delivery_order_id", "=", pick_id)], limit=1)
                if tr:
                    tr_vals = {
                        "delivery_date": date_str,
                        "travel_time":   accum_secs[vehicle_id] / 60.0,
                        "distance_km":   job_km,
                    }
                    tr.write(tr_vals)

                # ─ 5) Advance cursor by `service_secs`
                cursors[vehicle_id] = cursor + service_secs
                _logger.info(
                    "VROOM → next cursor for vehicle %s = %s",
                    vehicle_id, cursors[vehicle_id]
                )

            # ───────────────────────────────────────────────────────────────────
            # 5) Purge old auto‐generated Traktop records & rebuild per‐vehicle
            auto = self.search([("manual_vehicle_override", "=", False)])
            _logger.info("VROOM → unlinking %d old Traktop records", len(auto))
            auto.unlink()

            from collections import defaultdict
            steps_by_vehicle = defaultdict(list)
            for route in routes:
                vid = route.get("vehicle")
                if vid:
                    steps_by_vehicle[vid].extend(route.get("steps", []))

            # ─ We will now recreate each Traktop “step” in order, carrying forward
            #   the same two fields we just wrote (travel_time & distance_km).
            for route_idx, (vehicle_id, steps) in enumerate(steps_by_vehicle.items()):
                vehicle   = self.env["fleet.vehicle"].browse(vehicle_id)
                driver_id = vehicle.driver_id.id if vehicle.driver_id else False

                # Re‐initialize a local “running total” for seconds, so we can recalc
                # travel_time on each new record exactly as we did above.
                accum_secs_this_vehicle = 0

                for seq, step in enumerate(steps):
                    vals = {
                        "vehicle_id":     vehicle.id,
                        "vehicle_name":   vehicle.name,
                        "route_id":       route_idx,
                        "route_sequence": seq,
                        "step_type":      step.get("type"),
                    }

                    # If it's a “start” or “end,” zero out everything:
                    if step["type"] in ("start", "end"):
                        vals.update({
                            "partner_id":        driver_id,
                            "partner_latitude":  float(vehicle.latitude)  or 0.0,
                            "partner_longitude": float(vehicle.longitude) or 0.0,
                            # travel_time = 0, distance_km = 0 (start/end)
                            "travel_time":  0.0,
                            "distance_km":  0.0,
                        })

                    else:
                        # It's a “job” step. We can re‐compute the same two values:
                        job_id = step.get("job")
                        dp     = self.env["stock.picking"].browse(job_id)
                        if dp:
                            vals.update({
                                "delivery_order_id": dp.id,
                                "partner_id":        dp.partner_id.id,
                                "delivery_address":  dp.partner_id.address,
                                "delivery_date":     dp.scheduled_date,
                                "partner_latitude":  dp.partner_id.partner_latitude,
                                "partner_longitude": dp.partner_id.partner_longitude,
                                "build_time":        dp.sale_id.build_time or 0,
                            })

                        # Re‐accumulate travel_time & distance in the exact same way:
                        leg_secs = int(step.get("duration", 0))
                        accum_secs_this_vehicle += leg_secs
                        leg_metres = float(step.get("distance", 0))
                        leg_km     = leg_metres / 1000.0

                        vals.update({
                            "travel_time":  accum_secs_this_vehicle / 60.0,
                            "distance_km":  leg_km,
                        })

                        existing = self.search([("delivery_order_id", "=", job_id)], limit=1)
                        if existing:
                            # In case user manually overrode “vehicle_id,” just
                            # update route_sequence & skip re‐creating it
                            if existing.manual_vehicle_override:
                                existing.with_context(from_optimization=True).write({
                                    "route_id":       route_idx,
                                    "route_sequence": seq,
                                })
                                continue
                            else:
                                existing.unlink()

                    # Finally, create a brand‐new Traktop record with travel_time & distance_km included
                    self.with_context(from_optimization=True).create(vals)

            # ───────────────────────────────────────────────────────────────────
            # 6) Recompute per‐vehicle route_sequence (exactly as before)
            self.recalculate_route_sequence()

            return {
                "type": "ir.actions.client",
                "tag":  "display_notification",
                "params": {
                    "title":   _("Success"),
                    "message": _("Routes & dates updated (with rollover)."),
                    "type":    "success",
                    "sticky":  False,
                    "next":    {"type": "ir.actions.client", "tag": "reload"},
                },
            }

        except Exception as e:
            _logger.exception("VROOM → Exception in get_optimized_rec_created")
            raise UserError(_("Error optimizing routes: %s") % e)



               
 ########################################################

    def recalculate_route_sequence(self):
        """
        Recalculate the route sequence per vehicle by calling the VROOM API.
        Now we only consider vehicles that have at least one job record.
        """
        # Only process vehicles that have at least one job step.
        job_vehicle_ids = self.search([('step_type', '=', 'job')]).mapped('vehicle_id.id')
        for vehicle_id in set(job_vehicle_ids):
            vehicle_rec = self.env['fleet.vehicle'].browse(vehicle_id)
            # Gather all Traktop records for this vehicle.
            orders = self.search([('vehicle_id', '=', vehicle_id)])
            # Skip if there are no orders or if there is no valid vehicle coordinate.
            if not orders or not (vehicle_rec.latitude and vehicle_rec.longitude):
                continue
            try:
                lat = float(vehicle_rec.latitude)
                lon = float(vehicle_rec.longitude)
            except ValueError:
                continue

            vehicle_data = {
                "id": vehicle_rec.id,
                "vehicle_name": vehicle_rec.name,
                "start": [lon, lat],
                "end": [lon, lat]
            }
            jobs_data = []
            for order in orders:
                if order.step_type == 'job' and order.delivery_order_id and order.partner_latitude and order.partner_longitude:
                    # compute same 8–18 window on order.delivery_date
                    sched = fields.Datetime.from_string(order.delivery_date)
                    start_dt = datetime.combine(sched.date(), time(8, 0))
                    end_dt   = datetime.combine(sched.date(), time(18, 0))
                    start_ts = int(start_dt.timestamp())
                    end_ts   = int(end_dt.timestamp())

                    # prep time
                    service_secs = int((order.delivery_order_id.sale_id.build_time or 0) * 60)

                    jobs_data.append({
                        "id":               order.delivery_order_id.id,
                        "oid":              order.delivery_order_id.name,
                        "user_id":          str(order.partner_id.id) if order.partner_id else '',
                        "location":         [order.partner_longitude, order.partner_latitude],
                        "service":          service_secs,
                        "time_windows":   [[start_ts, end_ts]],
                        "partner_latitude":  order.partner_latitude,
                        "partner_longitude": order.partner_longitude,
                    })

            # Only call the API if there is at least one job.
            if not jobs_data:
                _logger.info("No job records found for vehicle %s; skipping route sequence recalculation.", vehicle_rec.name)
                continue

            payload = {
                "vehicles": [vehicle_data],
                "jobs": jobs_data,
                "options": {"g": True},
            }
            try:
                _logger.info("Recalculating route sequence for vehicle %s using payload: %s", vehicle_rec.name, json.dumps(payload, indent=4))
                response = requests.post("https://route.trakop.com:8100", json=payload, timeout=30)
                # response = requests.post("http://solver.vroom-project.org", json=payload, timeout=30)
                response.raise_for_status()
                result = response.json()
                _logger.info("VROOM recalc response: %s", json.dumps(result, indent=2))
                routes = result.get("routes", [])
                if routes:
                    route = routes[0]  # We assume one vehicle per payload.
                    steps = route.get("steps", [])
                    for seq, step in enumerate(steps):
                        if step.get("type") == "job":
                            job_id = step.get("job")
                            # Update the route_sequence for the matching Traktop record.
                            tr_record = self.search([('delivery_order_id', '=', job_id), ('vehicle_id', '=', vehicle_id)], limit=1)
                            if tr_record:
                                tr_record.write({'route_sequence': seq})
                else:
                    _logger.info("No routes returned from VROOM API for vehicle %s.", vehicle_rec.name)
            except Exception as e:
                _logger.error("Error recalculating route sequence for vehicle %s: %s", vehicle_rec.name, str(e))
                raise UserError("Error recalculating route sequence for vehicle %s" % vehicle_rec.name)
            
###########################################
# Extend Sale Order – Create/Update/Delete Traktop via Delivery Orders
###########################################

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    build_time = fields.Integer(
        string="Build Time (min)",
        default=30,
        help="Minutes needed to prepare this order"
    )

    def action_confirm(self):
        res = super().action_confirm()
        for order in self:
            pickings = order.picking_ids.filtered(
                lambda p: p.picking_type_id.code == 'outgoing' and p.state == 'assigned'
            )
            for picking in pickings:
                existing = self.env['traktop'].search(
                    [('delivery_order_id', '=', picking.id)], limit=1
                )
                if not existing:
                    self.env['traktop'].create({
                        'delivery_order_id': picking.id,
                        'partner_id':         order.partner_shipping_id.id,
                        'delivery_address':   order.partner_shipping_id.contact_address,
                        'delivery_date':      order.commitment_date,
                        'partner_latitude':   order.partner_shipping_id.partner_latitude,
                        'partner_longitude':  order.partner_shipping_id.partner_longitude,
                        # ← propagate build_time here:
                        'build_time':         order.build_time,
                    })
                    _logger.info(
                        "Sale Order %s confirmed: created Traktop record for delivery %s",
                        order.name, picking.name
                    )
        return res


    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ('order_line', 'commitment_date')):
            for order in self:
                pickings = order.picking_ids.filtered(
                    lambda p: p.picking_type_id.code == 'outgoing' and p.state == 'assigned'
                )
                for picking in pickings:
                    existing = self.env['traktop'].search(
                        [('delivery_order_id', '=', picking.id)], limit=1
                    )
                    if not existing:
                        self.env['traktop'].create({
                            'delivery_order_id': picking.id,
                            'partner_id':         order.partner_shipping_id.id,
                            'delivery_address':   order.partner_shipping_id.contact_address,
                            'delivery_date':      order.commitment_date,
                            'partner_latitude':   order.partner_shipping_id.partner_latitude,
                            'partner_longitude':  order.partner_shipping_id.partner_longitude,
                            # ← and here too:
                            'build_time':         order.build_time,
                        })
                        _logger.info(
                            "Sale Order %s updated: created Traktop record for delivery %s",
                            order.name, picking.name
                        )
        return res


    def unlink(self):
        for order in self:
            for picking in order.picking_ids:
                traktop_rec = self.env['traktop'].search([('delivery_order_id', '=', picking.id)])
                if traktop_rec:
                    traktop_rec.unlink()
                    _logger.info("Sale Order %s deleted: removed Traktop record for delivery %s", order.name, picking.name)
        return super(SaleOrder, self).unlink()

###########################################
# Extend Stock Picking – Keep Traktop Records in Sync with Picking State
###########################################

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def write(self, vals):
        res = super(StockPicking, self).write(vals)
        if 'state' in vals:
            for picking in self:
                if picking.picking_type_id.code == 'outgoing':
                    picking_state = picking.state
                    _logger.info("Processing picking %s with new state: %s", picking.name, picking_state)
                    # Use sudo() to ensure we have the necessary rights
                    traktop_records = self.env['traktop'].sudo().search([('delivery_order_id', '=', picking.id)])
                    if picking_state == 'assigned':
                        if not traktop_records:
                            self.env['traktop'].sudo().create({
                                'delivery_order_id': picking.id,
                                'partner_id': picking.partner_id.id,
                                'delivery_address': picking.partner_id.contact_address,
                                'delivery_date': picking.scheduled_date,
                                'partner_latitude': picking.partner_id.partner_latitude,
                                'partner_longitude': picking.partner_id.partner_longitude,
                                'build_time':        getattr(picking.sale_id, 'build_time', 0),
                            })
                            _logger.info("Created Traktop record for picking %s", picking.name)
                    else:
                        if traktop_records:
                            _logger.info("Unlinking %d Traktop record(s) for picking %s", len(traktop_records), picking.name)
                            traktop_records.sudo().unlink()
                            _logger.info("Removed Traktop record for picking %s", picking.name)
        return res

    def action_done(self):
        """Triggered when the picking is validated and moves to 'done'."""
        res = super(StockPicking, self).action_done()
        for picking in self:
            if picking.picking_type_id.code == 'outgoing':
                traktop_rec = self.env['traktop'].sudo().search([
                    ('delivery_order_id', '=', picking.id)
                ])
                if traktop_rec:
                    _logger.info("Removing Traktop record(s) for picking %s as state is now 'done'.", picking.name)
                    traktop_rec.sudo().unlink()
        return res

    def button_validate(self):
        """
        Odoo calls this method when you click Validate on a picking.
        It often calls action_done() internally, but we can ensure the record is removed here as well.
        """
        res = super(StockPicking, self).button_validate()
        for picking in self:
            if picking.picking_type_id.code == 'outgoing' and picking.state == 'done':
                traktop_rec = self.env['traktop'].sudo().search([
                    ('delivery_order_id', '=', picking.id)
                ])
                if traktop_rec:
                    _logger.info("Removing Traktop record(s) for picking %s on button_validate.", picking.name)
                    traktop_rec.sudo().unlink()
        return res

###########################################
# Other Models (ResPartner, ResConfigSettings, FleetVehicle)
###########################################

class ResPartner(models.Model):
    _inherit = 'res.partner'
    
    address = fields.Char(string="Address")
    longitude = fields.Char(string="Longitude")
    latitude = fields.Char(string="Latitude")
    ne_latitude = fields.Char(string="North-East Latitude")
    ne_longitude = fields.Char(string="North-East Longitude")
    sw_latitude = fields.Char(string="South-East Latitude")
    sw_longitude = fields.Char(string="South-East Longitude")
    
    live_latitude = fields.Float(string="Live Latitude", digits=(10, 7))
    live_longitude = fields.Float(string="Live Longitude", digits=(10, 7))
    last_seen = fields.Datetime(string="Last Seen")
    speed = fields.Float(string="Speed")

    @api.model
    def create(self, vals):
        partner = super(ResPartner, self).create(vals)
        if 'latitude' in vals and 'longitude' in vals:
            partner.geo_localize()
        elif any(field in vals for field in ['street', 'city', 'zip', 'state_id', 'country_id']):
            partner.geo_localize()
        return partner

    def write(self, vals):
        res = super(ResPartner, self).write(vals)
        if 'latitude' in vals and 'longitude' in vals:
            self.geo_localize()
        elif any(field in vals for field in ['street', 'city', 'zip', 'state_id', 'country_id']):
            self.geo_localize()
        return res

    def geo_localize(self):
        for partner in self:
            if partner.latitude and partner.longitude:
                partner.write({
                    'partner_latitude': float(partner.latitude),
                    'partner_longitude': float(partner.longitude),
                })
            else:
                super(ResPartner, partner).geo_localize()

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    google_map_api_key = fields.Char(string="Google Map API Key", config_parameter="address_autocomplete_gmap_widget.google_map_api_key")

class FleetVehicle(models.Model):
    _inherit = "fleet.vehicle"

    address = fields.Char(string="Address")
    longitude = fields.Char(string="Longitude")
    latitude = fields.Char(string="Latitude")
    ne_latitude = fields.Char(string="North-East Latitude")
    ne_longitude = fields.Char(string="North-East Longitude")
    sw_latitude = fields.Char(string="South-East Latitude")
    sw_longitude = fields.Char(string="South-East Longitude")
    cost_value = fields.Float(
        string="Cost Value",
        help="Enter the cost value for the selected cost type (e.g., 5 for fixed, 20 for per hour, etc.)"
    )
    cost_type =fields.Selection([
        ('fixed', 'Fixed'),
        ('perhour', 'Perhour'),
        ('per km', 'Per Km'),
    ], string="Cost Type", help="a cost object defining costs for this vehicle")
    skills = fields.Char(string="Skills", help="an array of integers defining skills")
    type = fields.Char(string="Vehicle Type", help="a string describing this vehicle type")
   
    working_hours_start = fields.Float(
        string="Working Hours Start",
        help="Enter the start time of working hours in 24-hour format (e.g., 8.0 for 8:00 AM, 13.5 for 1:30 PM)"
    )
    working_hours_end = fields.Float(
        string="Working Hours End",
        help="Enter the end time of working hours in 24-hour format (e.g., 16.0 for 4:00 PM, 18.5 for 6:30 PM)"
    )
    time_window = fields.Char(
        string="Working Hours (seconds)",
        compute="_compute_time_window",
        store=True,
        help="A JSON array describing working hours in seconds. Example: [28800, 57600]"
    )
    time_window_display = fields.Char(
            string="Working Hours (hrs)",
            compute="_compute_time_window_display",
            help="Displays the total working hours in hours (e.g., 8 hrs)"
    )
    # breaks = fields.Text(string="Breaks", compute="_compute_breaks", store=True, help="an array of break objects")
    break_start = fields.Float(
        string="Break Start",
        help="Enter the start time of the break in 24-hour format (e.g., 14.0 for 2:00 PM)"
    )

    break_end = fields.Float(
        string="Break End",
        help="Enter the end time of the break in 24-hour format (e.g., 14.5 for 2:30 PM)"
    )
    speed_factor = fields.Selection([
        ('normal', '1'),
        ('slow', '2'),
        ('fast', '3'),
        ('very_fast', '4'),
        ('extremely_fast', '5'),
    ], string="Speed Factor", default='normal', help="a string defining the speed factor for this vehicle, where 1 is normal speed and higher values indicate faster speeds. This can be used to adjust travel times based on the vehicle's speed capabilities.")
    max_tasks = fields.Integer(string="Max Tasks", help="an integer defining the maximum number of tasks in a route for this vehicle")
    max_travel_time = fields.Float(string="Max Travel Time", help="an integer defining the maximum travel time for this vehicle")
    max_distance = fields.Float(string="Max Distance", help="an integer defining the maximum distance for this vehicle")
    @api.onchange('max_travel_time')
    def _onchange_max_travel_time(self):
        """
        Convert max_travel_time from hours to seconds before saving.
        """
        for record in self:
            if record.max_travel_time:
                record.max_travel_time = record.max_travel_time * 3600  # Convert hours to seconds

    @api.onchange('max_distance')
    def _onchange_max_distance(self):
        """
        Convert max_distance from kilometers to meters before saving.
        """
        for record in self:
            if record.max_distance:
                record.max_distance = record.max_distance * 1000  # Convert kilometers to meters
    @api.depends('working_hours_start', 'working_hours_end')
    def _compute_time_window(self):
        """
        Compute the time_window field based on the start and end times.
        """
        for record in self:
            if record.working_hours_start is not None and record.working_hours_end is not None:
                # Convert start and end times to seconds
                start_time_seconds = int(record.working_hours_start * 3600)
                end_time_seconds = int(record.working_hours_end * 3600)

                # Proceed with logic without checking if end time is greater than start time
                record.time_window = json.dumps([start_time_seconds, end_time_seconds])
            else:
                # Skip computation if either start or end time is not set
                record.time_window = False
    @api.depends('time_window')
    def _compute_time_window_display(self):
        """
        Compute the time_window_display field to show the total working hours in hours.
        """
        for record in self:
            if record.time_window:
                try:
                    time_window = json.loads(record.time_window)
                    start_time_seconds, end_time_seconds = time_window
                    total_hours = (end_time_seconds - start_time_seconds) / 3600
                    record.time_window_display = f"{total_hours:.1f} hrs"
                except (ValueError, TypeError):
                    record.time_window_display = "Invalid"
            else:
                record.time_window_display = "N/A"
    def _inverse_time_window(self):
        """
        Inverse method to update working_hours_start and working_hours_end from time_window.
        """
        for record in self:
            if record.time_window:
                try:
                    time_window = json.loads(record.time_window)
                    start_time_seconds, end_time_seconds = time_window
                    record.working_hours_start = start_time_seconds / 3600
                    record.working_hours_end = end_time_seconds / 3600
                except (ValueError, TypeError):
                    record.working_hours_start = 0
                    record.working_hours_end = 0
    @api.constrains('cost_value', 'cost_type')
    def _check_cost_value(self):
        for record in self:
            if record.cost_type and not record.cost_value:
                    raise ValidationError(_("Please provide a cost value for the selected cost type."))
    # @api.constrains('skills')
    # def _check_skills_format(self):
    #     for record in self:
    #         if record.skills:
    #             try:
    #                 skills = [int(skill) for skill in record.skills.split(',')]
    #             except ValueError:
    #                 raise ValidationError(_("Skills must be a comma-separated list of integers."))
    @api.constrains('break_start', 'break_end')
    def _check_break_duration(self):
        for record in self:
            if record.break_start is not None and record.break_end is not None:
                if record.break_start < 0 or record.break_start > 24:
                    raise ValidationError(_("Break start time must be between 0 and 24 hours."))
                if record.break_end < 0 or record.break_end > 24:
                    raise ValidationError(_("Break end time must be between 0 and 24 hours."))
                if record.break_end <= record.break_start:
                    raise ValidationError(_("Break end time must be greater than break start time."))
                if (record.break_end - record.break_start) > 0.5:
                    raise ValidationError(_("Break duration cannot exceed 30 minutes."))
class StockMove(models.Model):
    _inherit = 'stock.move'

    picked = fields.Boolean(
        string="Picked",
        default=False,
        help="Check when this product has been physically picked"
    )
