# -*- coding: utf-8 -*-

from odoo import models, fields


class ProductCategory(models.Model):
    _name = 'product.category'
    _inherit = 'product.category'

    eicr_activity_id = fields.Many2one('economic_activity', 'Actividad Económica', track_visibility='always')

