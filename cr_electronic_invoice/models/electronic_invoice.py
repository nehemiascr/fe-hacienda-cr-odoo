# -*- coding: utf-8 -*-

import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class IdentificationType(models.Model):
	_name = "identification.type"

	code = fields.Char(string="Código", required=False, )
	name = fields.Char(string="Nombre", required=False, )
	notes = fields.Text(string="Notas", required=False, )


class CodeTypeProduct(models.Model):
	_name = "code.type.product"

	code = fields.Char(string="Código", required=False, )
	name = fields.Char(string="Nombre", required=False, )


class ProductElectronic(models.Model):
	_inherit = "product.template"

	@api.model
	def _default_code_type_id(self):
		code_type_id = self.env['code.type.product'].search([('code', '=', '04')], limit=1)
		return code_type_id or False

	commercial_measurement = fields.Char(string="Unidad de Medida Comercial", required=False, )
	code_type_id = fields.Many2one(comodel_name="code.type.product", string="Tipo de código", required=False,
								   default=_default_code_type_id)





class Exoneration(models.Model):
	_name = "exoneration"

	name = fields.Char(string="Nombre", required=False, )
	code = fields.Char(string="Código", required=False, )
	type = fields.Char(string="Tipo", required=False, )
	exoneration_number = fields.Char(string="Número de exoneración", required=False, )
	name_institution = fields.Char(string="Nombre de institución", required=False, )
	date = fields.Date(string="Fecha", required=False, )
	percentage_exoneration = fields.Float(string="Porcentaje de exoneración", required=False, )


class PaymentMethods(models.Model):
	_name = "payment.methods"

	active = fields.Boolean(string="Activo", required=False, default=True)
	sequence = fields.Char(string="Secuencia", required=False, )
	name = fields.Char(string="Nombre", required=False, )
	notes = fields.Text(string="Notas", required=False, )


class SaleConditions(models.Model):
	_name = "sale.conditions"

	active = fields.Boolean(string="Activo", required=False, default=True)
	sequence = fields.Char(string="Secuencia", required=False, )
	name = fields.Char(string="Nombre", required=False, )
	notes = fields.Text(string="Notas", required=False, )


class AccountPaymentTerm(models.Model):
	_inherit = "account.payment.term"
	sale_conditions_id = fields.Many2one(comodel_name="sale.conditions", string="Condiciones de venta")


class ReferenceDocument(models.Model):
	_name = "reference.document"

	active = fields.Boolean(string="Activo", required=False, default=True)
	code = fields.Char(string="Código", required=False, )
	name = fields.Char(string="Nombre", required=False, )


class ReferenceCode(models.Model):
	_name = "reference.code"

	active = fields.Boolean(string="Activo", required=False, default=True)
	code = fields.Char(string="Código", required=False, )
	name = fields.Char(string="Nombre", required=False, )


class Resolution(models.Model):
	_name = "resolution"

	active = fields.Boolean(string="Activo", required=False, default=True)
	name = fields.Char(string="Nombre", required=False, )
	date_resolution = fields.Date(string="Fecha de resolución", required=False, )


class ProductUom(models.Model):
	_inherit = "product.uom"
	code = fields.Char(string="Código", required=False, )


class AccountJournal(models.Model):
	_inherit = "account.journal"
	nd = fields.Boolean(string="Nota de Débito", required=False, )





