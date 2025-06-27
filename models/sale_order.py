# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    build_time = fields.Integer(
        string="Total Build Time (min)",
        compute='_compute_build_time',
        store=True
    )

    @api.depends('order_line.product_id', 'order_line.product_uom_qty')
    def _compute_build_time(self):
        for order in self:
            total_time = 0
            for line in order.order_line:
                product = line.product_id
                qty = line.product_uom_qty
                total_time += (product.build_time or 0) * qty
            order.build_time = total_time
    def action_confirm(self):
        res = super(SaleOrder, self).action_confirm()
        for order in self:
            # look for outgoing pickings in 'assigned'
            pickings = order.picking_ids.filtered(
                lambda p: p.picking_type_id.code == 'outgoing' and p.state == 'assigned'
            )
            for picking in pickings:
                existing = self.env['traktop'].search(
                    [('delivery_order_id', '=', picking.id)], limit=1
                )
                if not existing:
                    self.env['traktop'].create({
                        'delivery_order_id':  picking.id,
                        'partner_id':          order.partner_shipping_id.id,
                        'delivery_address':    order.partner_shipping_id.contact_address,
                        'delivery_date':       order.commitment_date,
                        'partner_latitude':    order.partner_shipping_id.partner_latitude,
                        'partner_longitude':   order.partner_shipping_id.partner_longitude,
                        'build_time':          order.build_time,
                    })
        return res

    def write(self, vals):
        res = super(SaleOrder, self).write(vals)
        # if lines or commitment_date changed, ensure Traktop records exist
        if any(field in vals for field in ['order_line', 'commitment_date']):
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
                            'delivery_order_id':  picking.id,
                            'partner_id':          order.partner_shipping_id.id,
                            'delivery_address':    order.partner_shipping_id.contact_address,
                            'delivery_date':       order.commitment_date,
                            'partner_latitude':    order.partner_shipping_id.partner_latitude,
                            'partner_longitude':   order.partner_shipping_id.partner_longitude,
                            'build_time':          order.build_time,
                        })
        return res

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    build_time = fields.Integer(
        string="Build Time (min)",
        default=30,
        help="Estimated preparation time for this product"
    )
