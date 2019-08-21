# -*- coding: utf-8 -*-
from odoo import models, fields
import logging


_logger = logging.getLogger(__name__)


class ElectronicInvoiceCostaRicaProductCode(models.Model):
    _name = "eicr.product_code"

    code = fields.Char("Código")
    name = fields.Char("Nombre")
