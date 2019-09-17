# -*- coding: utf-8 -*-
from odoo import models, fields
import logging

_logger = logging.getLogger(__name__)


class ElectronicInvoiceCostaRicaReferenceCode(models.Model):
    _name = "eicr.reference_code"
    _description = 'Modes in which an Electronic Document corrects or modifies other Electronic Documents'

    active = fields.Boolean("Activo", default=True)
    code = fields.Char("Código")
    name = fields.Char("Nombre")
