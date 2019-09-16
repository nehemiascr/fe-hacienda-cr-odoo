# -*- coding: utf-8 -*-

import logging, re
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

REGIMENES = [
    ('0', 'No tiene'),
    ('1', 'Régimen Tradicional'),
    ('2', 'Régimen Tradicional')]


class PartnerElectronic(models.Model):
	_inherit = "res.partner"

	phone_code = fields.Char("Código de teléfono",  default="506")
	state_id = fields.Many2one("res.country.state", "Provincia")
	district_id = fields.Many2one("res.country.district", "Distrito")
	county_id = fields.Many2one("res.country.county", "Cantón")
	neighborhood_id = fields.Many2one("res.country.neighborhood", "Barrios")
	identification_id = fields.Many2one("eicr.identification_type", "Tipo de identificacion")

	email_facturas = fields.Char('Email donde enviar las facturas')

	eicr_activity_ids = fields.Many2many('eicr.economic_activity', string='Actividades Económicas')

	eicr_regimen = fields.Selection(REGIMENES, 'Régimen Tributario', default='0')

	_sql_constraints = [ ('vat_uniq', 'unique (vat)', "Ya hay un cliente con esa identifcación"), ]

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
