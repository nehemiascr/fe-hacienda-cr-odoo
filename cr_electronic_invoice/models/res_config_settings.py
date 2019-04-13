# -*- coding: utf-8 -*-

from odoo import api, fields, models
import logging


_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
	_inherit = 'res.config.settings'

	default_FacturaElectronica_version = fields.Many2one('facturacion_electronica.version', related='company_id.facturacion_electronica_version_id')
	default_FacturaElectronica_usuario = fields.Char('res.company', related='company_id.facturacion_electronica_usuario')
	default_FacturaElectronica_password = fields.Char('res.company', related='company_id.facturacion_electronica_password')
	default_FacturaElectronica_pin = fields.Char('res.company', related='company_id.facturacion_electronica_pin')
	default_FacturaElectronica_llave_criptografica = fields.Binary('res.company', related='company_id.facturacion_electronica_llave_criptografica')

	@api.model
	def create(self, values):
		_logger.info('creating')
		_logger.info(dir(values))
		_logger.info(values)
		return super(ResConfigSettings, self).create(values)

	def probar_conexion(self, values):
		_logger.info('probando conexion')
		_logger.info('self %s' % self)
		status = self.env['facturacion_electronica.facturacion_electronica']._get_token()
		if status:
			return {'type': 'ir.actions.client', 'tag': 'Login exitoso' }
		else:
			return {'type': 'ir.actions.client', 'tag': 'usuario inválido'}