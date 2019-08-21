# -*- coding: utf-8 -*-
from odoo import models, fields
import logging

_logger = logging.getLogger(__name__)


class ElectronicInvoiceCostaRicaIVACreditCondition(models.Model):
	_name = "eicr.iva.credit_condition"

	active = fields.Boolean("Activo", default=True)
	code = fields.Char("Código")
	name = fields.Char("Nombre")
	notes = fields.Text("Notas")
