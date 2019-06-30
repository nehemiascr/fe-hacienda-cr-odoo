# -*- coding: utf-8 -*-

import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class CompanyElectronic(models.Model):
	_name = 'res.company'
	_inherit = ['res.company', 'mail.thread', ]

	commercial_name = fields.Char(string="Nombre comercial")
	phone_code = fields.Char(string="Código de teléfono",  size=3, default="506")

	identification_id = fields.Many2one(comodel_name="identification.type", string="Tipo de identificacion")
	district_id = fields.Many2one(comodel_name="res.country.district", string="Distrito")
	county_id = fields.Many2one(comodel_name="res.country.county", string="Cantón")
	neighborhood_id = fields.Many2one(comodel_name="res.country.neighborhood", string="Barrios")

	eicr_version_id = fields.Many2one('electronic_invoice.version', 'Versión de la Facturación Electrónica')
	eicr_username = fields.Char(string="Usuario")
	eicr_password = fields.Char(string="Contraseña")
	eicr_signature = fields.Binary(string="Llave Criptográfica")
	eicr_pin = fields.Char(string="PIN")

	eicr_environment = fields.Selection(selection=[('disabled', 'Deshabilitado'), ('api-stag', 'Pruebas'), ('api-prod', 'Producción')],
										string="Ambiente",
										required=True, default='disabled',
										help='Seleccione el punto de conexión del Ministerio de Hacienda a usar')

	eicr_token = fields.Text('Token de sesión para el sistema de recepción de comprobantes del Ministerio de Hacienda')

	@api.multi
	def action_get_token(self):
		_logger.info('checking token %s' % self.eicr_token)
		self.env['electronic_invoice'].get_token(self)