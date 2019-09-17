# -*- coding: utf-8 -*-
from odoo import models, fields
import logging

_logger = logging.getLogger(__name__)


class ElectronicInvoiceCostaRicaIdentificationType(models.Model):
	_name = 'eicr.identification_type'
	_description = 'Types of IDs in Costa Rica'

	code = fields.Char('Código')
	name = fields.Char('Nombre')
	notes = fields.Text('Notas')
	digits = fields.Integer('Cantidad de dígitos de la identificación')