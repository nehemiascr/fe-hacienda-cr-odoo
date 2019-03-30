# -*- coding: utf-8 -*-

import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class InvoiceLineElectronic(models.Model):
	_inherit = "account.invoice.line"

	total_amount = fields.Float(string="Monto total", required=False, )
	total_discount = fields.Float(string="Total descuento", required=False, )
	discount_note = fields.Char(string="Nota de descuento", required=False, )
	total_tax = fields.Float(string="Total impuesto", required=False, )
	#   exoneration_total = fields.Float(string="Exoneración total", required=False, )
	#   total_line_exoneration = fields.Float(string="Exoneración total de la línea", required=False, )
	exoneration_id = fields.Many2one(comodel_name="exoneration", string="Exoneración", required=False, )