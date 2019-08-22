# -*- coding: utf-8 -*-

import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class PartnerElectronic(models.Model):
	_inherit = "res.partner"

	phone_code = fields.Char("Código de teléfono",  default="506")
	state_id = fields.Many2one("res.country.state", "Provincia")
	district_id = fields.Many2one("res.country.district", "Distrito")
	county_id = fields.Many2one("res.country.county", "Cantón")
	neighborhood_id = fields.Many2one("res.country.neighborhood", "Barrios")
	identification_id = fields.Many2one("eicr.identification_type", "Tipo de identificacion")

	email_facturas = fields.Char('Email donde enviar las facturas')

	eicr_activity_ids = fields.Many2many('eicr.economic_activity', string='Actividades Económicas')
