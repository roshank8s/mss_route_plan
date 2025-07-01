# Route Planing for Odoo

`mss_route_plan` provides advanced route optimisation for delivery orders and
field service tasks.  The module relies on the external VROOM API
(`https://optimize.trakop.com/`) to compute efficient routes and integrates the
results directly back into Odoo records.

## Features

* **Delivery Order Optimisation** – confirmed sales orders automatically create
  `route.planing` entries for each outgoing delivery.  The action *Optimize* in
  the list view calls the VROOM service and updates each record with a planned
  delivery date, route sequence, travel time and distance.
* **Field Service Optimisation** – tasks from the *Field Service* project can be
  routed in the same way via `field.service.route.step`.  Optimisation assigns
  vehicles, schedules tasks and updates the task records.
* **Unified Route Optimiser** – both delivery orders and field service jobs can
  be planned together using the *Unified Optimisation* action.  Results are
  stored as `route.unified.step` records and can be visualised on a map.
* **Vehicle & Partner Geolocation** – partner and vehicle forms include Google
  Maps autocomplete widgets.  Latitude and longitude are stored for use by the
  optimiser.
* **Real‑time Driver Tracking** – the included JavaScript `location_updater.js`
  posts GPS coordinates and speed to `/update_user_location`, storing them on
  the driver's partner record.
* **Usage Logging & API Key Registration** – a wizard guides first‑time users
  through registering with the Trakop service and stores the returned API key in
  Odoo's system parameters.

## Setup

1. Copy the `mss_route_plan` folder into your Odoo addons directory.
2. Update the Apps list from the Odoo dashboard.
3. Install **Route Planing** from the Apps menu.
4. In *Settings ‣ Companies*, enter your Google Maps and Route API keys.

After installation configure your fleet vehicles with coordinates, working hours
and optional delivery days.  Customers can also be assigned a preferred
`delivery_day` so that only relevant orders are optimised each day.

For more information about Odoo module management see the
[Odoo documentation](https://www.odoo.com/documentation/latest/).
