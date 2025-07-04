# file: updatamain.py
from odoo import http
from odoo.http import request
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
from datetime import datetime
import logging

_logger = logging.getLogger(__name__)
_logger.setLevel(logging.CRITICAL)

class UserLocationController(http.Controller):
    @http.route('/update_user_location', type='json', auth='user', methods=['POST'], csrf=False)
    def update_user_location(self, **kwargs):
        _logger.debug("Starting update_user_location endpoint with kwargs: %s", kwargs)
        
        # Check if the payload is wrapped under 'params'. If not, fallback to using kwargs directly.
        params = kwargs.get("params")
        if not params:
            _logger.warning("No 'params' provided in request kwargs; falling back to direct kwargs: %s", kwargs)
            params = kwargs

        latitude = params.get("latitude")
        longitude = params.get("longitude")
        speed = params.get("speed")  # New speed parameter
        
        _logger.info("Received location update: latitude=%s, longitude=%s, speed=%s", latitude, longitude, speed)
        
        # Validate that latitude and longitude are provided
        if latitude is None or longitude is None:
            _logger.warning("Incomplete location data received: latitude=%s, longitude=%s", latitude, longitude)
            return {"status": "error", "message": "Incomplete location data"}

        uid = request.session.get('uid')
        if not uid:
            _logger.error("No user ID found in session.")
            return {"status": "error", "message": "User not authenticated"}
        _logger.debug("User ID from session: %s", uid)
        
        user = request.env['res.users'].sudo().browse(uid)
        if not user:
            _logger.error("User not found for UID: %s", uid)
            return {"status": "error", "message": "User not found"}
        _logger.debug("Fetched user: %s", user.name)

        # Ensure that the user is assigned as a driver by checking fleet.vehicle records.
        driver_vehicle = request.env['fleet.vehicle'].sudo().search([('driver_id', '=', user.partner_id.id)], limit=1)
        if not driver_vehicle:
            _logger.warning("User %s is not assigned as a driver.", user.partner_id.id)
            return {"status": "error", "message": "Only drivers can update GPS data."}
        
        if user.partner_id:
            current_time = datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT)
            _logger.debug("Current server time: %s", current_time)
            try:
                user.partner_id.sudo().write({
                    'live_latitude': latitude,
                    'live_longitude': longitude,
                    'last_seen': current_time,
                    'speed': speed,
                })
                _logger.info("Partner %s updated with new location (lat: %s, lng: %s) and speed: %s at %s", 
                             user.partner_id.id, latitude, longitude, speed, current_time)
            except Exception as e:
                _logger.exception("Error while updating partner %s: %s", user.partner_id.id, e)
                return {"status": "error", "message": "Failed to update location"}
        else:
            _logger.warning("User %s does not have an associated partner.", uid)
            return {"status": "error", "message": "Partner not found for user"}

        return {"status": "ok"}
