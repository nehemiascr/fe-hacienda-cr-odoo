# -*- coding: utf-8 -*-

from odoo import fields, models

import logging

_logger = logging.getLogger(__name__)


class FacturacionElectronicaEsquema(models.Model):
	_name = 'facturacion_electronica.esquema'

	name = fields.Char('Esquema', required=True)
	url = fields.Char('URL donde se encuentra el esquema del documento')
	esquema = fields.Text('Definicion del esquema en xml', required=True)
	documento = fields.Text('Documento xml que cumple el esquema')
	version_id = fields.Many2one('facturacion_electronica.version', 'Versión')
