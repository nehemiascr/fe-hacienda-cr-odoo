# -*- coding: utf-8 -*-

from odoo import models, fields, api


class ProductTemplate(models.Model):
    _name = 'product.template'
    _inherit = 'product.template'

    @api.model
    def _default_code_type_id(self):
        code_type_id = self.env['code.type.product'].search([('code', '=', '04')], limit=1)
        return code_type_id or False

    eicr_activity_id = fields.Many2one('economic_activity', 'Actividad Económica', track_visibility='always')
    commercial_measurement = fields.Char('Unidad de Medida Comercial')
    code_type_id = fields.Many2one('code.type.product', 'Tipo de código', default=_default_code_type_id)
