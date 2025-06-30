# -*- coding: utf-8 -*-
import requests
from odoo import api, fields, models, _, _lt
from odoo.exceptions import ValidationError, UserError
import logging
import json

_logger = logging.getLogger(__name__)

###########################################
# Traktop Model – Using Delivery Order Link
###########################################

class Traktop(models.Model):
    _name = 'traktop'
    _description = 'Traktop'
    _inherit = ['mail.thread']
    active = fields.Boolean(string="Active", default=True)
    
    # Link to a confirmed delivery order (stock.picking)
    delivery_order_id = fields.Many2one('stock.picking', string="Delivery Order")
    partner_id = fields.Many2one('res.partner', string="Customer")
    delivery_address = fields.Char(string="Delivery Address")
    partner_latitude = fields.Float('Latitude', digits=(10, 7))
    partner_longitude = fields.Float('Longitude', digits=(10, 7))
    delivery_date = fields.Datetime(string='Delivery Date')
    distance = fields.Float(string="Distance (km)")
    vehicle_id = fields.Many2one('fleet.vehicle', string="Vehicle")
    vehicle_name = fields.Char(string="Vehicle Name")
    display_name = fields.Char(string="Display Name", compute="_compute_display_name")
    vehicle_starting_point = fields.Char(string="Starting Point", compute="_compute_vehicle_address")
    driver_name = fields.Char(string="Driver", compute="_compute_driver_name", store=True)
    
    # Fields for routing
    route_id = fields.Integer("Route ID")
    route_sequence = fields.Integer("Route Sequence")
    step_type = fields.Selection(
        [('start', 'Start'), ('job', 'Job'), ('end', 'End')],
        string="Step Type"
    )
    # Flag to indicate manual updates (e.g., manual vehicle assignment)
    is_manual = fields.Boolean(string="Manual Update", default=False,
                            help="Check this box if you have manually updated the start/end details so that automated optimization does not override them.")

    @api.model
    def get_google_map_api_key(self):
        # Use sudo() to bypass access restrictions
        return self.env['ir.config_parameter'].sudo().get_param(
            "address_autocomplete_gmap_widget.google_map_api_key"
        )
###########################################

    @api.onchange('vehicle_id')
    def _onchange_vehicle_id(self):
        if self.vehicle_id:
            self.vehicle_name = self.vehicle_id.name
            # Only auto-update if the step is start or end.
            if self.step_type in ['start', 'end']:
                self.partner_latitude = float(self.vehicle_id.latitude) if self.vehicle_id.latitude else 0.0
                self.partner_longitude = float(self.vehicle_id.longitude) if self.vehicle_id.longitude else 0.0
                # Optionally update the address if available.
                self.delivery_address = self.vehicle_id.address
                # Mark record as manually updated so that automated optimization does not override it.
                self.is_manual = True

############################################            
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
            record.display_name = f"{partner_name} - {order_name}" if order_name else partner_name

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

    @api.model
    def fetch_jobs_data(self):
        # Fetch jobs from delivery orders in state 'assigned'
        deliveries = self.env['stock.picking'].sudo().search([
            ('state', '=', 'assigned'),
            ('picking_type_id.code', '=', 'outgoing')
        ])
        _logger.info("fetch_jobs_data: Found %s delivery orders in 'assigned' state", len(deliveries))
        job_data = []
        for picking in deliveries:
            if picking.partner_id and picking.partner_id.partner_latitude and picking.partner_id.partner_longitude:
                location = [picking.partner_id.partner_longitude, picking.partner_id.partner_latitude]
                job_data.append({
                    "id": picking.id,
                    "oid": picking.name,
                    "user_id": str(picking.partner_id.id),
                    "location": location,
                    "delivery_date": picking.scheduled_date.isoformat() if picking.scheduled_date else None,
                    "partner_latitude": picking.partner_id.partner_latitude,
                    "partner_longitude": picking.partner_id.partner_longitude,
                })
        return job_data

    @api.model
    def integrate_vroom(self):
        vroom_url = "https://route.trakop.com:8100"
        vehicles = self.fetch_vehicle_data()
        jobs = self.fetch_jobs_data()

        # Ensure delivery_date is properly serialized if present
        for job in jobs:
            if job.get('delivery_date'):
                job['delivery_date'] = job['delivery_date']

        payload = {
            "vehicles": vehicles,
            "jobs": jobs
        }
        try:
            _logger.info("Sending payload to Routing API: %s", json.dumps(payload, indent=4))
            response = requests.post(vroom_url, json=payload, timeout=30)
            response.raise_for_status()
            optimized_routes = response.json()
            return optimized_routes
        except requests.exceptions.RequestException as e:
            _logger.error("Error while connecting to Routing API: %s", e)
            _logger.error("Payload sent to Routing API: %s", json.dumps(payload, indent=4))
            if 'response' in locals():
                _logger.error("Response content: %s", response.text)
            raise UserError("Error connecting to Routing API: Either partners or vehicles Latitude and Longitude are missing.")

    @api.model
    def action_fetch_delivery_orders(self):
        # For manual testing – create Traktop records for delivery orders in 'assigned' state
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
                    'partner_id': picking.partner_id.id,
                    'delivery_address': picking.partner_id.contact_address,
                    'delivery_date': picking.scheduled_date,
                    'partner_latitude': picking.partner_id.partner_latitude,
                    'partner_longitude': picking.partner_id.partner_longitude,
                })
                _logger.info("Created Traktop record for delivery: %s", picking.name)
        return True

    def get_optimized_rec_created(self):
        try:
            optimized_data = self.integrate_vroom()
            # Unlink only non-manually updated records.
            self.search([('is_manual', '=', False)]).unlink()
            
            # Loop through the routes from the optimized data.
            for route_idx, route in enumerate(optimized_data.get('routes', [])):
                vehicle_id = route.get('vehicle')
                vehicle_rec = self.env['fleet.vehicle'].search([("id", "=", vehicle_id)])
                if not vehicle_rec:
                    _logger.warning("Vehicle with ID %s not found.", vehicle_id)
                    continue
                partner_id = vehicle_rec.driver_id.id if vehicle_rec.driver_id else False
                for step_idx, step in enumerate(route.get('steps', [])):
                    step_type = step.get('type')
                    vals = {
                        'vehicle_id': vehicle_rec.id,
                        'vehicle_name': vehicle_rec.name,
                        'route_id': route_idx,
                        'route_sequence': step_idx,
                        'step_type': step_type,
                    }
                    if step_type in ['start', 'end']:
                        # Check if there is an existing manual record for this route and step type.
                        existing_manual = self.search([
                            ('route_id', '=', route_idx),
                            ('step_type', '=', step_type),
                            ('is_manual', '=', True)
                        ], limit=1)
                        if existing_manual:
                            # Skip updating manual record.
                            continue  # Do not update anything if manual data exists.
                        else:
                            # Otherwise, apply the automatic values from the optimized route.
                            vals.update({
                                'partner_id': partner_id,
                                'partner_latitude': float(vehicle_rec.latitude) if vehicle_rec.latitude else 0.0,
                                'partner_longitude': float(vehicle_rec.longitude) if vehicle_rec.longitude else 0.0,
                                'delivery_address': vehicle_rec.address,
                            })
                            self.create(vals)
                    elif step_type == 'job':
                        job_id = step.get('job')
                        delivery_order = self.env['stock.picking'].sudo().browse(job_id)
                        if delivery_order:
                            # Check if there's an existing record for this route + job step.
                            existing_traktop = self.search([
                                ('delivery_order_id', '=', delivery_order.id),
                                ('route_id', '=', route_idx),
                                ('route_sequence', '=', step_idx),
                            ], limit=1)
    
                            vals.update({
                                'delivery_order_id': delivery_order.id,
                                'partner_id': delivery_order.partner_id.id,
                                'delivery_address': delivery_order.partner_id.address,
                                'delivery_date': delivery_order.scheduled_date,
                                'partner_latitude': delivery_order.partner_id.partner_latitude,
                                'partner_longitude': delivery_order.partner_id.partner_longitude,
                            })
    
                            if existing_traktop:
                                # Only update if the record hasn't been manually updated.
                                if not existing_traktop.is_manual:
                                    existing_traktop.write(vals)
                                # Else: skip updating, preserving manual changes.
                            else:
                                self.create(vals)

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success'),
                    'message': _('Optimized routes have been successfully created/updated.'),
                    'type': 'success',
                    'sticky': False,
                    'next': {
                        'type': 'ir.actions.client',
                        'tag': 'reload',
                    }
                }
            }
        except Exception as e:
            raise UserError(_('Error computing optimized routes: Either partners or vehicles Latitude and Longitude are missing.'))

###########################################
# Extend Sale Order – Create/Update/Delete Traktop via Delivery Orders
###########################################

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_confirm(self):
        res = super(SaleOrder, self).action_confirm()
        for order in self:
            # Look for outgoing delivery orders created on confirmation in state 'assigned'
            pickings = order.picking_ids.filtered(lambda p: p.picking_type_id.code == 'outgoing' and p.state == 'assigned')
            for picking in pickings:
                existing = self.env['traktop'].search([('delivery_order_id', '=', picking.id)], limit=1)
                if not existing:
                    self.env['traktop'].create({
                        'delivery_order_id': picking.id,
                        'partner_id': order.partner_shipping_id.id,
                        'delivery_address': order.partner_shipping_id.contact_address,
                        'delivery_date': order.commitment_date,
                        'partner_latitude': order.partner_shipping_id.partner_latitude,
                        'partner_longitude': order.partner_shipping_id.partner_longitude,
                    })
                    _logger.info("Sale Order %s confirmed: created Traktop record for delivery %s", order.name, picking.name)
        return res

    def write(self, vals):
        res = super(SaleOrder, self).write(vals)
        # If the sale order is canceled, remove associated Traktop records.
        if 'state' in vals and vals.get('state') == 'cancel':
            for order in self:
                for picking in order.picking_ids:
                    traktop_rec = self.env['traktop'].search([('delivery_order_id', '=', picking.id)], limit=1)
                    if traktop_rec:
                        traktop_rec.unlink()
                        _logger.info("Sale Order %s canceled: removed Traktop record for delivery %s", order.name, picking.name)
        # When key fields are updated, create missing records if still assigned.
        if any(field in vals for field in ['order_line', 'commitment_date']):
            for order in self:
                pickings = order.picking_ids.filtered(lambda p: p.picking_type_id.code == 'outgoing' and p.state == 'assigned')
                for picking in pickings:
                    existing = self.env['traktop'].search([('delivery_order_id', '=', picking.id)], limit=1)
                    if not existing:
                        self.env['traktop'].create({
                            'delivery_order_id': picking.id,
                            'partner_id': order.partner_shipping_id.id,
                            'delivery_address': order.partner_shipping_id.contact_address,
                            'delivery_date': order.commitment_date,
                            'partner_latitude': order.partner_shipping_id.partner_latitude,
                            'partner_longitude': order.partner_shipping_id.partner_longitude,
                        })
                        _logger.info("Sale Order %s updated: created Traktop record for delivery %s", order.name, picking.name)
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
            # Check if it's outgoing (optional—remove if you also want to handle incoming)
            if picking.picking_type_id.code == 'outgoing':
                traktop_rec = self.env['traktop'].sudo().search([
                    ('delivery_order_id', '=', picking.id)
                ])
                if traktop_rec:
                    _logger.info(
                        "Removing Traktop record(s) for picking %s as state is now 'done'.",
                        picking.name
                    )
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
                    _logger.info(
                        "Removing Traktop record(s) for picking %s on button_validate.",
                        picking.name
                    )
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
