# -*- coding: utf-8 -*-
from odoo import models, fields
import logging

_logger = logging.getLogger(__name__)


class IdentificationType(models.Model):
	_name = 'identification.type'

	code = fields.Char('Código')
	name = fields.Char('Nombre')
	notes = fields.Text('Notas')