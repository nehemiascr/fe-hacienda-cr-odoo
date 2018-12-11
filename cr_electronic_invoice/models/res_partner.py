# -*- coding: utf-8 -*-

import logging
import re
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PartnerElectronic(models.Model):
	_inherit = "res.partner"

	commercial_name = fields.Char(string="Nombre comercial", required=False, )
	phone_code = fields.Char(string="Código de teléfono", required=False, default="506")
	state_id = fields.Many2one(comodel_name="res.country.state", string="Provincia", required=False, )
	district_id = fields.Many2one(comodel_name="res.country.district", string="Distrito", required=False, )
	county_id = fields.Many2one(comodel_name="res.country.county", string="Cantón", required=False, )
	neighborhood_id = fields.Many2one(comodel_name="res.country.neighborhood", string="Barrios", required=False, )
	identification_id = fields.Many2one(comodel_name="identification.type", string="Tipo de identificacion",
										required=False, )
	payment_methods_id = fields.Many2one(comodel_name="payment.methods", string="Métodos de Pago", required=False, )
