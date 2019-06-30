# -*- coding: utf-8 -*-

from odoo import fields, models

import logging

_logger = logging.getLogger(__name__)


class ElectronicInvoiceVersion(models.Model):
	_name = 'electronic_invoice.version'

	name = fields.Char('Version', required=True)
	schema_ids = fields.One2many('electronic_invoice.schema', 'version_id', 'Esquemas de los documentos')
	url_reception_endpoint_production = fields.Char('url recepción producción', required=True)
	url_reception_endpoint_testing = fields.Char('url recepción pruebas', required=True)
	url_auth_endpoint = fields.Char('url auth', required=True)
	notes = fields.Text('Notas')
