# -*- coding: utf-8 -*-

from odoo import models, fields
import logging

_logger = logging.getLogger(__name__)


class ElectronicInvoiceCostaRicaAccountJournal(models.Model):
    _name = 'account.journal'
    _inherit = ['account.journal']

    sucursal = fields.Integer('Sucursal', default='1')
    terminal = fields.Integer('Terminal', default='1')
    nd = fields.Boolean('Nota de Débito')