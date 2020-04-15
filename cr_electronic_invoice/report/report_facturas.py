# -*- coding: utf-8 -*-
#     dev@fakturacion.com
from odoo import api, models, fields, _
import logging

_logger = logging.getLogger(__name__)

strings = {
    'out_invoice': {
        'name': 'Facturas de Cliente',
        'title': 'Listado de Facturas Emitidas',
        'vat': 'Cédula de Cliente',
        'type': 'Cliente'
    },
    'out_refund': {
        'name': 'Notas de Crédito',
        'title': 'Listado de Notas de Crédito Emitidas',
        'vat': 'Cédula de Cliente',
        'type': 'Cliente'
    },
    'in_invoice': {
        'name': 'Facturas de Proveedor',
        'title': 'Listado de Documentos Recibidos',
        'vat': 'Cédula de Proveedor',
        'type': 'Proveedor'
    }
}

h = {0:'A', 1:'B', 2:'C', 3:'D', 4:'E', 5:'F', 6:'G', 7:'H', 8:'I', 9:'J', 10:'K', 11:'L'}



class FacturasReportWizard(models.TransientModel):
    _name = 'cr_electronic_invoice.facturas.report.wizard'

    inicio = fields.Date(string="Fecha de inicio del reporte", required=True, default=fields.Date.today)
    final = fields.Date(string="Fecha final del reporte", required=True, default=fields.Date.today)
    type = fields.Selection([   ('out_invoice', _(strings['out_invoice']['name'])),
                                ('out_refund' , _(strings['out_refund']['name'])),
                                ('in_invoice' , _(strings['in_invoice']['name']))   ])



    @api.multi
    def get_report(self):
        """Call when button 'Get Report' clicked.
        """
        _logger.info('get_report %s' % self.__dict__)

        data = {
            'ids': self.ids,
            'model': self._name,
            'form': {
                'inicio': self.inicio,
                'final': self.final,
                'type': self.type,
            },
        }

        _logger.info('data for report_action %s' % data)

        # use `module_name.report_id` as reference.
        # `report_action()` will call `get_report_values()` and pass `data` automatically.
        return self.env.ref('cr_electronic_invoice.facturas').report_action(self, data=data)


class Facturas(models.AbstractModel):
    _name = 'report.cr_electronic_invoice.facturas'
    _inherit = 'report.report_xlsx.abstract'

    def generate_xlsx_report(self, workbook, data, invoice):
        _logger.info('self %s workbook %s data %s invoices %s' % (self, workbook, data, invoice))

        facturas = self.env['account.invoice'].search([('type','=', data['form']['type']),
                                                       ('date_invoice', '>=', data['form']['inicio']),
                                                       ('date_invoice', '<=', data['form']['final']),
                                                       ('state', 'in', ('open','paid')),
                                                       ('company_id','=',self.env.user.company_id.id)
                                                       ])
        _logger.info('facturas %s' % facturas)

        report_name = strings[data['form']['type']]['name']
        sheet = workbook.add_worksheet(report_name)
        bold = workbook.add_format({'bold': True})
        money = workbook.add_format({'num_format': '₡#,##0.00'})
        date = workbook.add_format({'num_format': 'dd/mm/yy'})
        taxes = facturas.mapped('invoice_line_ids').mapped('invoice_line_tax_ids')

        # Report Header
        # first row : Name     Vat     Date Range
        sheet.write(0, 0, self.env.user.company_id.name, bold)
        sheet.write(0, 2, self.env.user.company_id.vat, bold)
        sheet.write(0, 6, 'Del %s al %s' % (data['form']['inicio'], data['form']['final']), bold)
        # second row : Title
        sheet.write(1, 3, strings[data['form']['type']]['title'], bold)
        # third row : Column Names
        sheet.write(2, 0, strings[data['form']['type']]['vat'], bold)
        sheet.write(2, 1, strings[data['form']['type']]['type'], bold)
        sheet.write(2, 2, 'Factura', bold)
        sheet.write(2, 3, 'Consecutivo', bold)
        sheet.write(2, 4, 'Fecha', bold)
        sheet.write(2, 5, 'Subtotal', bold)
        columna = 6
        for i, tax in enumerate(taxes):
            sheet.write(2, columna+i, tax.name, bold)
        sheet.write(2, columna+len(taxes)+0, 'Total Impuestos', bold)
        sheet.write(2, columna+len(taxes)+1, 'Total', bold)

        # Report Lines
        fila = 3
        for i, factura in enumerate(facturas):
            sheet.write(i+fila, 0, factura.partner_id.vat or '')
            sheet.write(i+fila, 1, factura.partner_id.name)
            sheet.write(i+fila, 2, factura.number_electronic)
            sheet.write(i+fila, 3, factura.number_electronic[21:41] if factura.number_electronic else factura.number)
            sheet.write(i+fila, 4, factura.date_invoice, date)
            price_subtotal = sum(factura.invoice_line_ids.mapped('price_subtotal'))
            if factura.refund_invoice_ids:
                price_subtotal -= sum(factura.refund_invoice_ids.mapped('invoice_line_ids').mapped('price_subtotal'))
            sheet.write(i+fila, 5, round(price_subtotal, 2), money)
            # sheet.write(indice+fila, 5, round(sum(factura.invoice_line_ids.mapped(lambda l: (l.price_unit * l.quantity) - l.price_subtotal)), 2))

            for j, tax in enumerate(taxes):
                total = factura.tax_line_ids.filtered(lambda t: t.tax_id == tax).ensure_one().amount_total if tax in factura.tax_line_ids.mapped('tax_id') else 0.0
                if factura.refund_invoice_ids:
                    for refund_invoice in factura.refund_invoice_ids:
                        total -= refund_invoice.tax_line_ids.filtered(lambda t: t.tax_id == tax).ensure_one().amount_total if tax in refund_invoice.tax_line_ids.mapped('tax_id') else 0.0
                sheet.write(i+fila, columna+j, round(total, 2), money)

            amount_total = sum(factura.tax_line_ids.mapped('amount_total'))
            if factura.refund_invoice_ids:
                amount_total -= sum(factura.refund_invoice_ids.mapped('tax_line_ids').mapped('amount_total'))
            sheet.write(i+fila, columna+len(taxes)+0, round(amount_total, 2), money)

            amount_total = factura.amount_total
            if factura.refund_invoice_ids:
                amount_total -= sum(factura.refund_invoice_ids.mapped('amount_total'))
            sheet.write(i+fila, columna+len(taxes)+1, round(amount_total, 2), money)

        # Report footer
        f_index = fila+len(facturas)
        sheet.write(f_index, 4, 'Totales', bold)
        # Subtotal
        sheet.write_formula('%s%s'% (h[columna-1], f_index+1), '=SUM(%s%s:%s%s)' % (h[columna-1], fila, h[columna-1], f_index), money)
        # Taxes
        for i, tax in enumerate(taxes):
            sheet.write_formula('%s%s'% (h[i+columna], f_index+1), '=SUM(%s%s:%s%s)' % (h[i+columna], fila+1, h[i+columna], f_index), money)
        # Total Impuestos
        h_index = columna+len(taxes)
        sheet.write_formula('%s%s'% (h[h_index], f_index+1), '=SUM(%s%s:%s%s)' % (h[h_index], fila, h[h_index], f_index), money)
        # Total
        sheet.write_formula('%s%s'% (h[h_index+1], f_index+1), '=SUM(%s%s:%s%s)' % (h[h_index+1], fila, h[h_index+1], f_index), money)
        


        sheet.set_column('A:A', 15)
        sheet.set_column('B:B', 30)
        sheet.set_column('C:C', 20)
        sheet.set_column('D:D', 20)
        sheet.set_column('E:E', 10)
        sheet.set_column('F:J', 15)
