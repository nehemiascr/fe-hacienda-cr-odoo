# -*- coding: utf-8 -*-

from odoo import fields, models, api
from lxml import etree
import re

import logging

_logger = logging.getLogger(__name__)


class ElectronicInvoiceCostaRicaDocument(models.Model):
	_name = 'eicr.document'
	_description = 'Electronic Document Types'

	name = fields.Char('Documento', required=True)
	tag = fields.Char('Nodo raíz', compute='_compute_tag', store=True, readonly=True)
	xmlns = fields.Char('taget namespace', compute='_compute_tag', store=True, readonly=True)

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
				tag  = xml.xpath("//xsd:element/@name", namespaces={"xsd":  "http://www.w3.org/2001/XMLSchema"})[0]
				document.tag = tag
				xmlns = xml.xpath("//xsd:schema", namespaces={"xsd": "http://www.w3.org/2001/XMLSchema"})[0].attrib['targetNamespace']
				document.xmlns = xmlns

	@api.model
	def get_root_node(self):

		xsi = 'http://www.w3.org/2001/XMLSchema-instance'
		xsd = 'http://www.w3.org/2001/XMLSchema'
		ds = 'http://www.w3.org/2000/09/xmldsig#'

		schemaLocation = '%s %s' % (self.xmlns, self.url)

		nsmap = {None : self.xmlns, 'xsd': xsd, 'xsi': xsi, 'ds': ds}
		attrib = {'{'+xsi+'}schemaLocation':schemaLocation}

		return etree.Element(self.tag, attrib=attrib, nsmap=nsmap)