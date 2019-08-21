# -*- coding: utf-8 -*-

from odoo import models, fields


class ElectronicInvoiceCostaRicaAccountTaxTemplate(models.Model):
    _name = 'account.tax.template'
    _inherit = 'account.tax.template'

    tax_code = fields.Char('Código de impuesto' )
    iva_tax_desc = fields.Char('Tarifa IVA', default='N/A')
    iva_tax_code = fields.Char('Código Tarifa IVA', default='N/A')