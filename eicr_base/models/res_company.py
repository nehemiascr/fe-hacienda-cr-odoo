# -*- coding: utf-8 -*-

import logging, re
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


class ElectronicInvoiceCostaRicaResCompany(models.Model):
	_name = 'res.company'
	_inherit = ['res.company', 'mail.thread', ]

	phone_code = fields.Char(string="Código de teléfono",  size=3, default="506")

	eicr_id_type = fields.Many2one("eicr.identification_type", "Tipo de identificacion")
	district_id = fields.Many2one("res.country.district", "Distrito")
	county_id = fields.Many2one("res.country.county", "Cantón")
	neighborhood_id = fields.Many2one("res.country.neighborhood", "Barrios")

	eicr_activity_ids = fields.Many2many('eicr.economic_activity', string='Actividades Económicas')

	eicr_version_id = fields.Many2one('eicr.version', 'Versión de la Facturación Electrónica')
	eicr_username = fields.Char("Usuario")
	eicr_password = fields.Char("Contraseña")
	eicr_signature = fields.Binary("Llave Criptográfica")
	eicr_pin = fields.Char("PIN")

	eicr_environment = fields.Selection(selection=[('disabled', 'Deshabilitado'), ('api-stag', 'Pruebas'), ('api-prod', 'Producción')],
										string="Ambiente",
										required=True, default='disabled',
										help='Seleccione el punto de conexión del Ministerio de Hacienda a usar')

	eicr_token = fields.Text('Token de sesión para el sistema de recepción de comprobantes')

	eicr_factor_iva = fields.Float(string="Factor IVA", help="Debe ser un valor porcentual mayor que cero y hasta cien", default=100)

	@api.constrains('eicr_factor_iva')
	def _check_eicr_factor_iva(self):
		if self.filtered(lambda company: company.eicr_factor_iva <= 0 or company.eicr_factor_iva > 100):
			raise ValidationError(_('Debe estar un valor porcentual mayor que cero y hasta cien'))

	@api.multi
	def action_get_token(self, var=None):
		_logger.info('checking token [%s]' % self.eicr_token)
		self.env['eicr.hacienda'].get_token(self)

	def action_update_info(self):
		info = self.env['eicr.hacienda'].get_info_contribuyente(self.vat)
		if info:
			self.identification_id = self.env['eicr.identification_type'].search([('code', '=', info['tipoIdentificacion'])])
			actividades = [a['codigo'] for a in info['actividades'] if a['estado'] == 'A']
			self.eicr_activity_ids = self.env['economic_activity'].search([('code', 'in', actividades)])

	@api.onchange('vat')
	def _onchange_state(self):
		identificacion = re.sub('[^0-9]', '', self.vat or '')
		if len(identificacion) >= 9:
			info = self.env['eicr.hacienda'].get_info_contribuyente(self.vat)
			if info:
				self.identification_id = self.env['eicr.identification_type'].search([('code', '=', info['tipoIdentificacion'])])
				actividades = [a['codigo'] for a in info['actividades'] if a['estado'] == 'A']
				self.eicr_activity_ids = self.env['eicr.economic_activity'].search([('code', 'in', actividades)])
				if not self.name or self.name == 'My Company' : self.name = info['nombre']
				if info['tipoIdentificacion'] in ('01', '03', '04'):
					self.partner_id.is_company = False
				elif info['tipoIdentificacion'] in ('02'):
					self.partner_id.is_company = True
