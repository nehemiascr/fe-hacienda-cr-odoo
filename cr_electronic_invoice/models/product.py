# -*- coding: utf-8 -*-

from odoo import models, fields


class ProductProduct(models.Model):
    _name = 'product.product'
    _inherit = 'product.product'

    eicr_activity_id = fields.Many2one( 'economic_activity', related='product_tmpl_id.eicr_activity_id')

