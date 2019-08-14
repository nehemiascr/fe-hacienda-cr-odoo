# -*- coding: utf-8 -*-

from odoo import models, fields


class ProductUom(models.Model):
    _inherit = 'product.uom'

    code = fields.Char('Código')
