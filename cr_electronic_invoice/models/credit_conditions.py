# -*- coding: utf-8 -*-
from odoo import models, fields
import logging

_logger = logging.getLogger(__name__)


class CreditConditions(models.Model):
	_name = "credit.conditions"

	active = fields.Boolean("Activo", default=True)
	sequence = fields.Char("Secuencia")
	name = fields.Char("Nombre")
	notes = fields.Text("Notas")
