from odoo import models, fields, api
from odoo.exceptions import UserError
import requests
import json
from odoo.exceptions import AccessError
import logging

_logger = logging.getLogger(__name__)

class UserRegistration(models.Model):
    _name = 'mss_route_plan.user.registration'
    _description = 'User Registration'

    partner_id = fields.Many2one('res.partner', string="User Contact")
    company_id = fields.Many2one('res.company', string="Company")

    # Editable Fields
    name = fields.Char(string="Name")
    email = fields.Char(string="Email")
    phone = fields.Char(string="Phone")
    company_name = fields.Char(string="Business Legal Name")
    country_id = fields.Many2one('res.country', string="Country")
    employee_count = fields.Selection([
        ('1-5', '1-5'),
        ('5-10', '5-10'),
        ('10-50', '10-50'),
        ('50-100', '50-100'),
        ('100-200', '100-200'),
        ('200-500', '200-500'),
        ('500-1000', '500-1000'),
        ('1000+', '1000+')
    ], string="Employee Count")

    customer_type = fields.Selection([
        ('mostly businesses', 'Mostly Businesses'), 
        ('mostly residential', 'Mostly Residential'),
        ('businesses and residential equally', 'Businesses and Residential Equally'),
    ], string="Customer Type")

    business_type = fields.Selection([
        ('distributer', 'Distributer'),
        ('manufacturer', 'Manufacturer'),
        ('others', 'Others'),
        ('producer', 'Producer'),
        ('retailer', 'Retailer'),
        ('supplier', 'Supplier'),
        ('wholesaler', 'WholeSaler'),
    ], string="What best describes your business?")
    
    delivery_method = fields.Selection([
        ('own_fleet', 'Own Fleet (Company-Owned Trucks & Drivers)'),
        ('3pl', 'Third-Party Logistics (FedEx, UPS, DHL, Local 3PL etc)'),
        ('hybrid', 'Hybrid Model (Own Fleet + 3PL Vendors)'),
        ('dropshipping', 'Dropshipping (Products shipped directly from suppliers)')
    ], string="How do you distribute/deliver your products?")

    annual_turnover = fields.Selection([
        ('<$1m', '<$1M'),
        ('$1m-$5m', '$1M-$5M'),
        ('$5m-$10m', '$5M-$10M'),
        ('$10m-$50m', '$10M-$50M'),
        ('$50m-$100m', '$50M-$100M'),
        ('$100m+', '$100M+'),
    ], string="Annual Turnover")

    # Hidden original values
    actual_name = fields.Char(string="Original Name")
    actual_email = fields.Char(string="Original Email")
    actual_phone = fields.Char(string="Original Phone")
    actual_company_name = fields.Char(string="Original Business Name")
    actual_country_id = fields.Many2one('res.country', string="Original Country")

    google_map_api_key = fields.Char(string="Google Maps API Key")
    route_api = fields.Char(string="Route API Key")
    registered_date = fields.Datetime(string="Registered On", default=fields.Datetime.now)
    usage_display = fields.Char(string="Usage Display")


class UserRegisterWizard(models.TransientModel):
    _name = 'user.register.wizard'
    _description = 'Activate Plugin'

    # Hidden (original) fields
    actual_name = fields.Char(string="Actual Name", readonly=True)
    actual_email = fields.Char(string="Actual Email", readonly=True)
    actual_phone = fields.Char(string="Actual Phone", readonly=True)
    actual_company_name = fields.Char(string="Actual Company Name", readonly=True)
    actual_country = fields.Many2one('res.country', string="Actual Country", readonly=True)

    # Editable fields
    name = fields.Char(string="Name")
    email = fields.Char(string="Email")
    phone = fields.Char(string="Phone")
    company_name = fields.Char(string="Business Legal Name")
    country_id = fields.Many2one('res.country', string="Country")

    employee_count = fields.Selection([
        ('1-5', '1-5'),
        ('5-10', '5-10'),
        ('10-50', '10-50'),
        ('50-100', '50-100'),
        ('100-200', '100-200'),
        ('200-500', '200-500'),
        ('500-1000', '500-1000'),
        ('1000+', '1000+')
    ], string="Employee Count")

    customer_type = fields.Selection([
        ('mostly businesses', 'Mostly Businesses'), 
        ('mostly residential', 'Mostly Residential'),
        ('businesses and residential equally', 'Businesses and Residential Equally'),
    ], string="Customer Type")

    business_type = fields.Selection([
        ('distributer', 'Distributer'),
        ('manufacturer', 'Manufacturer'),
        ('others', 'Others'),
        ('producer', 'Producer'),
        ('retailer', 'Retailer'),
        ('supplier', 'Supplier'),
        ('wholesaler', 'WholeSaler'),
    ], string="What best describes your business?")

    delivery_method = fields.Selection([
        ('own_fleet', 'Own Fleet (Company-Owned Trucks & Drivers)'),
        ('3pl', 'Third-Party Logistics (FedEx, UPS, DHL, Local 3PL etc)'),
        ('hybrid', 'Hybrid Model (Own Fleet + 3PL Vendors)'),
        ('dropshipping', 'Dropshipping (Products shipped directly from suppliers)')
    ], string="How do you distribute/deliver your products?")
    annual_turnover = fields.Selection([
        ('<$1m', '<$1M'),
        ('$1m-$5m', '$1M-$5M'),
        ('$5m-$10m', '$5M-$10M'),
        ('$10m-$50m', '$10M-$50M'),
        ('$50m-$100m', '$50M-$100M'),
        ('$100m+', '$100M+'),
    ], string="Annual Turnover")

    # Technical fields
    partner_id = fields.Many2one('res.partner', string="User", default=lambda self: self.env.user.partner_id)
    company_id = fields.Many2one('res.company', string="Company", default=lambda self: self.env.user.company_id)
    google_map_api_key = fields.Char(string="Google Maps API Key")
    route_api = fields.Char(string="Route API Key")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        user = self.env.user
        partner = user.partner_id
        company = user.company_id
        config = self.env['ir.config_parameter'].sudo()

        # Original values
        res['actual_name'] = partner.name
        res['actual_email'] = partner.email
        res['actual_phone'] = partner.phone
        res['actual_company_name'] = company.name
        res['actual_country'] = partner.country_id.id

        # Prefilled editable
        res['name'] = partner.name
        res['email'] = partner.email
        res['phone'] = partner.phone
        res['company_name'] = company.name
        res['country_id'] = partner.country_id.id

        res['google_map_api_key'] = config.get_param('address_autocomplete_gmap_widget.google_map_api_key', '')
        res['route_api'] = config.get_param('mss_route_plan.route_api', '')

        return res

    def action_register(self):
        if not self.email:
            raise UserError("Email is required.")

        registration = self.env['mss_route_plan.user.registration'].create({
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'google_map_api_key': self.google_map_api_key,
            'route_api': self.route_api,

            # New values
            'name': self.name,
            'email': self.email,
            'phone': self.phone,
            'company_name': self.company_name,
            'country_id': self.country_id.id,
            'employee_count': self.employee_count,
            'customer_type': self.customer_type,
            'business_type': self.business_type,
            'delivery_method': self.delivery_method,
            'annual_turnover': self.annual_turnover or "",

            # Original values
            'actual_name': self.actual_name,
            'actual_email': self.actual_email,
            'actual_phone': self.actual_phone,
            'actual_company_name': self.actual_company_name,
            'actual_country_id': self.actual_country.id,
        })

        config = self.env['ir.config_parameter'].sudo()
        if self.google_map_api_key:
            config.set_param('address_autocomplete_gmap_widget.google_map_api_key', self.google_map_api_key)
        if self.route_api:
            config.set_param('mss_route_plan.route_api', self.route_api)

        # External API call
        api_url = 'https://optimize.trakop.com/route/register'
        user_info = {
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "company_name": self.company_name,
            "country": self.country_id.name if self.country_id else "",
            "employee_count": self.employee_count,
            "customer_type": self.customer_type,
            "business_type": self.business_type,
            "delivery_method": self.delivery_method,
            "annual_turnover": self.annual_turnover or "",
            "original_name": self.actual_name,
            "original_email": self.actual_email,
            "original_phone": self.actual_phone,
            "original_company_name": self.actual_company_name,
            "original_country": self.actual_country.name if self.actual_country else "",
        }
        _logger.info("Preparing to register user: %s", user_info)
        payload = {
            'name': self.name,
            'email': self.email,
            'phone': self.phone,
            'company_name': self.company_name,
            'country': self.country_id.name if self.country_id else "",
            'employee_count': self.employee_count,
            'customer_type': self.customer_type,
            'business_type': self.business_type,
            'delivery_method': self.delivery_method,
            'annual_turnover': self.annual_turnover or "",
            'original_name': self.actual_name,
            'original_email': self.actual_email,
            'original_phone': self.actual_phone if self.actual_phone else "",
            'original_company_name': self.actual_company_name,
            'original_country': self.actual_country.name if self.actual_country else "",
            }
        _logger.info("Registering user via API: %s", payload)

        try:
            response = requests.post(api_url, headers={'Content-Type': 'application/json'},
                                     data=json.dumps(payload), timeout=30)
            _logger.info("Response: %s - %s", response.status_code, response.text)
            response_json = response.json() if response.headers.get('Content-Type', '').startswith('application/json') else {}

            if response.status_code == 200 and 'api_key' in response_json:
                api_key = response_json['api_key']
                config.set_param('mss_route_plan.route_api', api_key)

                # 🔁 Log Usage API Call
                usage_payload = {
                    "email": self.email
                }
                try:
                    usage_response = requests.post(
                        "https://optimize.trakop.com/route/log-usage",
                        headers={'Content-Type': 'application/json'},
                        data=json.dumps(usage_payload),
                        timeout=20
                    )
                    _logger.info("Usage log response: %s - %s", usage_response.status_code, usage_response.text)
                    usage_data = usage_response.json() if usage_response.status_code == 200 else {}

                    usage_display = usage_data.get("usage_display", "N/A")

                except Exception as e:
                    _logger.error("Failed to log usage: %s", str(e))
                    usage_display = "N/A"
                registration.sudo().write({'route_api': api_key,'usage_display': usage_display})
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Success',
                        'message': f'Registration successful! Usage: {usage_display}',
                        'type': 'success',
                        'sticky': False,
                        'next': {'type': 'ir.actions.act_window_close'},
                    }
                }

            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Failed',
                        'message': f'Error {response.status_code}: {response.text}',
                        'type': 'danger',
                        'sticky': True,
                    }
                }

        except requests.exceptions.Timeout:
            _logger.error("Timeout while registering user: %s", self.email)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Connection Error',
                    'message': 'Request timeout. Please try again.',
                    'type': 'danger',
                    'sticky': True,
                }
            }
        except Exception as e:
            _logger.error("Registration failed: %s", str(e), exc_info=True)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': str(e),
                    'type': 'danger',
                    'sticky': True,
                }
            }

class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model
    def open_module_action(self):
        _logger.info(">>> open_module_action() called by user ID: %s (Partner ID: %s)", self.env.user.id, self.env.user.partner_id.id)

        registration = self.env['mss_route_plan.user.registration'].sudo().search([
            ('route_api', '!=', False)
        ], limit=1)

        if registration:
            _logger.info(">>> Found registration record: ID=%s | route_api=%s", registration.id, registration.route_api)
        else:
            _logger.warning(">>> No registration record found for user: %s", self.env.user.id)

        if registration and registration.route_api:
            _logger.info(">>> route_api found. Granting access to module (action_traktop).")
            return self.env.ref('mss_route_plan.action_traktop').sudo().read()[0]
        else:
            _logger.info(">>> route_api not found. Opening registration wizard.")
            _logger.info(">>> Admin user. Opening registration wizard.")
            return {
                'type': 'ir.actions.act_window',
                'name': 'Activate Plugin',
                'res_model': 'user.register.wizard',
                'view_mode': 'form',
                'target': 'new',
                'view_id': self.env.ref('mss_route_plan.view_user_register_wizard').id,
            }

class OpenModuleTrigger(models.TransientModel):
    _name = 'open.module.trigger'
    _description = 'Trigger for opening Route Optimization module'        
