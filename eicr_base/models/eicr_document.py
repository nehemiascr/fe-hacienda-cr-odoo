# -*- coding: utf-8 -*-

from odoo import fields, models, api
from lxml import etree
import re

import logging

_logger = logging.getLogger(__name__)


class ElectronicInvoiceCostaRicaDocument(models.Model):
	_name = 'eicr.document'

	name = fields.Char('Esquema', required=True)
	tag = fields.Char('Etiqueta del Documento Electronico', compute='_compute_tag', store=True, readonly=True)
	url = fields.Char('URL donde se encuentra el esquema del documento')
	schema = fields.Text('Definicion del esquema en xml', required=True)
	document = fields.Text('Documento xml que cumple el esquema')
	version_id = fields.Many2one('eicr.version', 'Versión')


	@api.depends('schema')
	def _compute_tag(self):
		for document in self:
			if not document.tag:
				xml = etree.tostring(etree.fromstring(document.schema)).decode()
				xml = re.sub(' xmlns="[^"]+"', '', xml)
				xml = etree.fromstring(xml)
				document.tag = xml.tag