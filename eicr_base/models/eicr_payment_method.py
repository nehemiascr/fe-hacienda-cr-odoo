# -*- coding: utf-8 -*-
from odoo import models, fields
import logging

_logger = logging.getLogger(__name__)


class ElectronicInvoiceCostaRicaPaymentMethods(models.Model):
    _name = "eicr.payment_method"

    active = fields.Boolean("Activo", default=True)
    code = fields.Char("Secuencia")
    name = fields.Char("Nombre")
    notes = fields.Text("Notas")
