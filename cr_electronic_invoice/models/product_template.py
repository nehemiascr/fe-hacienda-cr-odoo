# -*- coding: utf-8 -*-

from odoo import models, fields


class ProductTemplate(models.Model):
    _name = 'product.template'
    _inherit = 'product.template'

    eicr_activity_id = fields.Many2one('economic_activity', 'Actividad Económica', track_visibility='always')

