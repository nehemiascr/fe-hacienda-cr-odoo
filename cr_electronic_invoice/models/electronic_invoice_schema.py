# -*- coding: utf-8 -*-

from odoo import fields, models

import logging

_logger = logging.getLogger(__name__)


class ElectronicInvoiceSchema(models.Model):
	_name = 'electronic_invoice.schema'

	name = fields.Char('Esquema', required=True)
	url = fields.Char('URL donde se encuentra el esquema del documento')
	schema = fields.Text('Definicion del esquema en xml', required=True)
	document = fields.Text('Documento xml que cumple el esquema')
	version_id = fields.Many2one('electronic_invoice.version', 'Versión')
