# Route Planing for Odoo

This module adds route planning tools to help your delivery or field service team choose the most efficient path between multiple addresses. It integrates with Odoo's existing sales, fleet, and location features to minimize travel time and costs.

## Setup
1. Copy `mss_route_plan` into your Odoo addons directory.
2. Update the Apps list from the Odoo dashboard.
3. Install **Route Planing** from the Apps menu.

After installation, configure your vehicles and addresses, then plan routes from sales orders or partner records.

Each vehicle can be assigned one or more **Delivery Days** under the Fleet settings. The route planner will only use vehicles whose `delivery_days` include the current weekday when building optimization data. Delivery orders are also filtered by their customer’s `delivery_day`, so only orders scheduled for today are optimized.

For general information about managing modules, see the [Odoo documentation](https://www.odoo.com/documentation/latest/).
