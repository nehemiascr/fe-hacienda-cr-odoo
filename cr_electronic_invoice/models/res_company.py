# -*- coding: utf-8 -*-

import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class CompanyElectronic(models.Model):
	_name = 'res.company'
	_inherit = ['res.company', 'mail.thread', ]

	commercial_name = fields.Char(string="Nombre comercial")
	phone_code = fields.Char(string="Código de teléfono",  size=3, default="506")
	signature = fields.Binary(string="Llave Criptográfica")
	identification_id = fields.Many2one(comodel_name="identification.type", string="Tipo de identificacion")
	district_id = fields.Many2one(comodel_name="res.country.district", string="Distrito")
	county_id = fields.Many2one(comodel_name="res.country.county", string="Cantón")
	neighborhood_id = fields.Many2one(comodel_name="res.country.neighborhood", string="Barrios")
	frm_ws_identificador = fields.Char(string="Usuario de Factura Electrónica")
	frm_ws_password = fields.Char(string="Password de Factura Electrónica")

	frm_ws_ambiente = fields.Selection(
		selection=[('disabled', 'Deshabilitado'), ('api-stag', 'Pruebas'), ('api-prod', 'Producción'), ],
		string="Ambiente",
		required=True, default='disabled',
		help='Es el ambiente en al cual se le está actualizando el certificado. Para el ambiente de calidad (stag) c3RhZw==, '
			 'para el ambiente de producción (prod) '
			 'cHJvZA==. Requerido.')
	frm_pin = fields.Char(string="Pin",  help='Es el pin correspondiente al certificado. Requerido')
	frm_callback_url = fields.Char(string="Callback Url",  default="https://url_callback/repuesta.php?",
								   help='Es la URL en a la cual se reenviarán las respuestas de Hacienda.')

	activated = fields.Boolean('Activado')
	state = fields.Selection([
		('draft', 'Draft'),
		('started', 'Started'),
		('progress', 'In progress'),
		('finished', 'Done'),
	], default='draft')

	frm_apicr_username = fields.Char(string="Usuario de Api")
	frm_apicr_password = fields.Char(string="Password de Api")
	frm_apicr_signaturecode = fields.Char(string="Codigo para Firmar API")

	token = fields.Text('token de sesión para el sistema de recepción de comprobantes del Ministerio de Hacienda')

	@api.multi
	def action_renovar_token(self):

		_logger.info('dumping old token %s' % self.token)

		self.env['facturacion_electronica'].refresh_token()

		_logger.info('new token saved %s' % self.token)

