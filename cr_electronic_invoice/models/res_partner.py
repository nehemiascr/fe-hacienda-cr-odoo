# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError

import logging, re

_logger = logging.getLogger(__name__)

REGIMENES = [
    ('0', 'No tiene'),
    ('1', 'Régimen Tradicional'),
    ('2', 'Régimen Simplificado')]


class ResPartner(models.Model):
    _inherit = "res.partner"

    commercial_name = fields.Char(string="Nombre comercial")
    phone_code = fields.Char(string="Código de teléfono", default="506")
    state_id = fields.Many2one(comodel_name="res.country.state", string="Provincia")
    district_id = fields.Many2one(comodel_name="res.country.district", string="Distrito")
    county_id = fields.Many2one(comodel_name="res.country.county", string="Cantón")
    neighborhood_id = fields.Many2one(comodel_name="res.country.neighborhood", string="Barrios")
    identification_id = fields.Many2one(comodel_name="identification.type", string="Tipo de identificacion")
    payment_methods_id = fields.Many2one(comodel_name="payment.methods", string="Métodos de Pago")

    eicr_activity_ids = fields.Many2many('economic_activity', string='Actividades Económicas')
    eicr_regimen = fields.Selection(REGIMENES, 'Régimen Tributario', default='0')

    email_facturas = fields.Char()

    eicr_exoneration_ids = fields.One2many('eicr.exoneration','partner_id',string="Exoneraciones")

    _sql_constraints = [('vat_uniq', 'Check(1=1)', 'Ya hay un contacto con esa identifcación'), ]

    @api.multi
    def action_update_info(self):
        eicr = self.env['eicr.tools']
        for partner in self:
            eicr.actualizar_info(partner)

    @api.onchange('vat')
    def _onchange_state(self):
        identificacion = re.sub('[^0-9]', '', self.vat or '')
        if len(identificacion) >= 9:
            self.env['eicr.tools'].actualizar_info(self)

    def _check_unique(self, vat):
        vat = re.sub('[^0-9]', '', vat or '') 
        partner_ids = self.env['res.partner'].search([]).filtered(lambda p: re.sub('[^0-9]', '', p.vat or '') == vat)
        # here we differentiate between partners (no parent_id) and contacts (with parent_id)
        partner_ids = partner_ids.filtered(lambda p: not p.parent_id)
        partner_ids = partner_ids.filtered(lambda p: p not in self.mapped('parent_id'))
        if self and partner_ids:
            message = 'La identificación %s ya se encuentra registrada:\n' % vat
            for p in partner_ids:
                message += '%s - %s\n' % (p.vat, p.name)
            raise UserError(_(message))

    @api.model
    def create(self, vals):
        if vals.get('vat', False):
            self._check_unique(vals.get('vat'))
        return super(ResPartner, self).create(vals)

    @api.multi
    def write(self, vals):
        if vals.get('vat', False):
            self._check_unique(vals.get('vat'))
        return super(ResPartner, self).write(vals)


