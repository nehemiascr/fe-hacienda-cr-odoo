# -*- coding: utf-8 -*-

from odoo import fields, models

import logging

_logger = logging.getLogger(__name__)


class ElectronicInvoiceCostaRicaVersion(models.Model):
	_name = 'eicr.version'

	name = fields.Char('Version', required=True)
	document_ids = fields.One2many('eicr.document', 'version_id', 'Esquemas de los documentos')
	url_reception_endpoint_production = fields.Char('url recepción producción', required=True)
	url_reception_endpoint_testing = fields.Char('url recepción pruebas', required=True)
	url_auth_endpoint_production = fields.Char('url auth producción', required=True )
	url_auth_endpoint_testing = fields.Char('url auth pruebas', required=True, oldname='url_auth_endpoint')
	notes = fields.Text('Notas')