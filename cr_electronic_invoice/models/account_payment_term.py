# -*- coding: utf-8 -*-
from odoo import models, fields
import logging

_logger = logging.getLogger(__name__)


class AccountPaymentTerm(models.Model):
    _inherit = "account.payment.term"

    sale_conditions_id = fields.Many2one("sale.conditions", "Condiciones de venta")
