# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class ElectronicInvoiceCostaRicaEconomicActivity(models.Model):
    _name = 'eicr.economic_activity'
    _description = 'Economic Activities in Costa Rica'

    active = fields.Boolean('Activo',  default=True)
    code = fields.Char('Código')
    name = fields.Char('Nombre')
    description = fields.Char('Descripción')
