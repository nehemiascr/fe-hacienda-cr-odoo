# -*- coding: utf-8 -*-
#     dev@fakturacion.com

import time
from odoo import api, fields, models
from datetime import datetime

import logging

_logger = logging.getLogger(__name__)


class ReportOverdue(models.AbstractModel):
    _name = 'report.account.report_overdue'

    @api.model
    def get_report_values(self, docids, data=None):

        facturas = {}
        totales = {}

        moneda = self.env.user.company_id.currency_id

        for partner_id in docids:
            facturas_de_cliente = self.env['account.invoice'].search([('partner_id', '=', partner_id),
                                                                      ('state', '=', 'open'),
                                                                      ('type','=','out_invoice')]
                                                                     ).sorted(key=lambda f: f.date_invoice)
            _logger.info('%s facturas ' % len(facturas_de_cliente))
            facturas[partner_id] = facturas_de_cliente
            debe = sum(facturas_de_cliente.mapped('residual_company_signed'))
            pagado = sum(facturas_de_cliente.mapped(lambda f: f.amount_total_company_signed - f.residual_company_signed))

            vencidas = facturas_de_cliente.filtered(lambda f: (datetime.now() - datetime.strptime(f.date_due, '%Y-%m-%d')).days > 0)
            vencido = sum(vencidas.mapped('residual_company_signed'))

            totales[partner_id] = {'debe': debe, 'pagado': pagado, 'vencido': vencido}

        return {
            'doc_ids': docids,
            'doc_model': 'res.partner',
            'docs': self.env['res.partner'].browse(docids),
            'time': time,
            'Date': fields.date.today(),
            'facturas': facturas,
            'totales': totales,
            'moneda': moneda
        }
