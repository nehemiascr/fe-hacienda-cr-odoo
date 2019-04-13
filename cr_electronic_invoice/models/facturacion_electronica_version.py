# -*- coding: utf-8 -*-

from odoo import fields, models

import logging

_logger = logging.getLogger(__name__)


class FacturacionElectronicaVersion(models.Model):
	_name = 'facturacion_electronica.version'

	name = fields.Char('Version', required=True)
	esquema_ids = fields.One2many('facturacion_electronica.esquema', 'version_id', 'Esquemas de los documentos')
	url_recepcion_produccion = fields.Char('url recepción producción', required=True)
	url_recepcion_pruebas = fields.Char('url recepción pruebas', required=True)
	url_auth = fields.Char('url auth', required=True)
	notas = fields.Text('Notas')
