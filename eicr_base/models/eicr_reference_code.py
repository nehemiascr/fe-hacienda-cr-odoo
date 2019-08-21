# -*- coding: utf-8 -*-
from odoo import models, fields
import logging

_logger = logging.getLogger(__name__)


class ElectronicInvoiceCostaRicaReferenceCode(models.Model):
    _name = "eicr.reference_code"

    active = fields.Boolean("Activo", default=True)
    code = fields.Char("Código")
    name = fields.Char("Nombre")
