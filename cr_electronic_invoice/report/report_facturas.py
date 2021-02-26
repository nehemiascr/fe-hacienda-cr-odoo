# -*- coding: utf-8 -*-
#     dev@fakturacion.com
from odoo import api, models, fields, _
import logging
from datetime import datetime
from dateutil import relativedelta

_logger = logging.getLogger(__name__)

strings = {
    'out_invoice': {
        'name': 'Facturas de Cliente',
        'title': 'Listado de Facturas Emitidas',
        'vat': 'Cédula de Cliente',
        'type': 'Cliente',
        'inverse': 'Nota de Crédito',
        'document': 'Factura'
    },
    'out_refund': {
        'name': 'Notas de Crédito',
        'title': 'Listado de Notas de Crédito Emitidas',
        'vat': 'Cédula de Cliente',
        'type': 'Cliente',
        'inverse': 'Factura',
        'document': 'Nota de Crédito'
    },
    'in_invoice': {
        'name': 'Facturas de Proveedor',
        'title': 'Listado de Documentos Recibidos',
        'vat': 'Cédula de Proveedor',
        'type': 'Proveedor',
        'document': 'Factura de Proveedor'
    },
    'in_refund': {
        'name': 'Facturas Rectificativas de Proveedor',
        'title': 'Listado de Rectificativas de Proveedor',
        'vat': 'Cédula de Proveedor',
        'type': 'Proveedor',
        'document': 'Factura Rectificativa de Proveedor'
    }
}

h = {0:'A', 1:'B', 2:'C', 3:'D', 4:'E', 5:'F', 6:'G', 7:'H', 8:'I', 9:'J', 10:'K', 11:'L', 12:'M', 13:'N', 14:'O', 15:'P', 16:'Q'}


class FacturasReportWizard(models.TransientModel):
    _name = 'cr_electronic_invoice.facturas.report.wizard'

    def _default_inicio(self):
        # primer día del mes pasado
        return datetime.now().date().replace(day=1) - relativedelta.relativedelta(months=+1)

    def _default_final(self):
        # último día del mes pasado
        return datetime.now().date().replace(day=1) + relativedelta.relativedelta(days=-1)


    inicio = fields.Date(string="Fecha de inicio del reporte", required=True, default=_default_inicio)
    final = fields.Date(string="Fecha final del reporte", required=True, default=_default_final)
    type = fields.Selection([   ('out_invoice', _(strings['out_invoice']['name'])),
                                ('out_refund' , _(strings['out_refund']['name'])),
                                ('in_invoice' , _(strings['in_invoice']['name']))   ], default='out_invoice')


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
                                                       ]).sorted(key=lambda f: (f.date_invoice, f.number))
        _logger.info('facturas %s' % facturas)

        company_currency_id = facturas[0].company_id.currency_id if facturas else self.env.user.company_id.currency_id
        report_name = strings[data['form']['type']]['name']
        color_nc = '#CCFF99'
        sheet = workbook.add_worksheet(report_name)
        cell = workbook.add_format()
        cell_nc = workbook.add_format({'bg_color': color_nc})
        bold = workbook.add_format({'bold': True})
        bold_nc = workbook.add_format({'bold': True, 'bg_color': color_nc})
        money = workbook.add_format({'num_format': '₡ #,##0.00'})
        money_nc = workbook.add_format({'num_format': '₡ #,##0.00', 'bg_color': color_nc})
        date = workbook.add_format({'num_format': 'dd/mm/yy'})
        date_nc = workbook.add_format({'num_format': 'dd/mm/yy', 'bg_color': color_nc})
        tax_ids = facturas.mapped('invoice_line_ids').mapped('invoice_line_tax_ids')
        row = 0 # Current Row index
        # Report Header
        # first row : Name     Vat     Date Range
        sheet.write(row, 0, self.env.user.company_id.name, bold)
        sheet.write(row, 2, self.env.user.company_id.vat, bold)
        sheet.write(row, 6, 'Del %s al %s' % (data['form']['inicio'], data['form']['final']), bold)
        # second row : Title
        row+=1 # 1
        sheet.write(row, 3, strings[data['form']['type']]['title'], bold)
        # third row : Column Names
        row+=1 # 2
        sheet.write(row, 0, strings[data['form']['type']]['vat'], bold)
        sheet.write(row, 1, strings[data['form']['type']]['type'], bold)
        sheet.write(row, 2, 'Documento', bold)
        sheet.write(row, 3, 'Clave', bold)
        sheet.write(row, 4, 'Consecutivo', bold)
        sheet.write(row, 5, 'Fecha', bold)
        sheet.write(row, 6, 'Subtotal', bold)
        columna = 7
        for i, tax in enumerate(tax_ids):
            sheet.write(row, columna+i, tax.name, bold)
        sheet.write(row, columna+len(tax_ids)+0, 'Total Impuestos', bold)
        sheet.write(row, columna+len(tax_ids)+1, 'Total', bold)
        sheet.write(row, columna+len(tax_ids)+2, 'Moneda', bold)
        sheet.write(row, columna+len(tax_ids)+3, 'Tipo de Cambio', bold)
        sheet.write(row, columna+len(tax_ids)+4, 'Total en la Moneda de la Factura', bold)

        # Report Lines
        row+=1 # 3
        first_data_row_index = row
        for i, factura in enumerate(facturas):
            invoice_ids = factura
            invoice_ids += factura.mapped('refund_invoice_ids').filtered(lambda i: i.state in ('open', 'paid')).sorted(key=lambda f: f.number)
            for j, i_id in enumerate(invoice_ids):
                row += j
                cell_format = cell_nc if i_id.type in ('out_refund', 'in_refund') else cell
                date_format = date_nc if i_id.type in ('out_refund', 'in_refund') else date
                mony_format = money_nc if i_id.type in ('out_refund', 'in_refund') else money
                # Tipo de Cambio
                exchange_rate = i_id.amount_total_company_signed / i_id.amount_total_signed if i_id.amount_total_signed else 1.0
                # Contacto
                sheet.write(i+row, 0, i_id.partner_id.vat or '', cell_format)
                # Nombre
                sheet.write(i+row, 1, i_id.partner_id.name, cell_format)
                # Documento
                sheet.write(i+row, 2, strings[i_id.type]['document'], cell_format)
                # Clave
                sheet.write(i+row, 3, i_id.number_electronic, cell_format)
                # Consecutivo
                sheet.write(i+row, 4, i_id.number_electronic[21:41] if i_id.number_electronic else i_id.number, cell_format)
                # Fecha
                sheet.write(i+row, 5, i_id.date_invoice, date_format)
                # Subtotal
                price_subtotal = i_id.amount_untaxed_signed
                sheet.write(i+row, 6, round(price_subtotal, 2), mony_format)
                # Impuestos
                for k, tax in enumerate(tax_ids):
                    total = i_id.tax_line_ids.filtered(lambda t: t.tax_id == tax).ensure_one().amount_total * exchange_rate if tax in i_id.tax_line_ids.mapped('tax_id') else 0.0
                    if i_id in factura.refund_invoice_ids:
                        total *= -1
                    sheet.write(i+row, columna+k, round(total, 2), mony_format)
                # Total Impuestos
                amount_total_tax = i_id.amount_total_company_signed - i_id.amount_untaxed_signed
                sheet.write(i+row, columna+len(tax_ids)+0, round(amount_total_tax, 2), mony_format)
                # Total
                amount_total = i_id.amount_total_company_signed
                sheet.write(i+row, columna+len(tax_ids)+1, round(amount_total , 2), mony_format)
                # Moneda
                sheet.write(i+row, columna+len(tax_ids)+2, i_id.currency_id.name, cell_format)
                # Tipo de Cambio
                sheet.write(i+row, columna+len(tax_ids)+3, exchange_rate, mony_format)
                # Total en la Moneda de la Factura
                invoice_currency_format = mony_format if i_id.currency_id == company_currency_id else workbook.add_format({'num_format': '%s #,##0.00' % i_id.currency_id.symbol})
                sheet.write_formula(i+row, columna+len(tax_ids)+4, '=%s%s/%s%s' % (h[columna+len(tax_ids)+1], i+row+1, h[columna+len(tax_ids)+3], i+row+1), invoice_currency_format)

        # Report footer
        f_index = row+len(facturas)
        sheet.write(f_index, 4, 'Totales', bold)
        # Subtotal
        sheet.write_formula('%s%s'% (h[columna-1], f_index+1), '=SUM(%s%s:%s%s)' % (h[columna-1], first_data_row_index+1, h[columna-1], f_index), money)
        # Taxes
        for i, tax in enumerate(tax_ids):
            sheet.write_formula('%s%s'% (h[i+columna], f_index+1), '=SUM(%s%s:%s%s)' % (h[i+columna], first_data_row_index+1, h[i+columna], f_index), money)
        # Total Impuestos
        h_index = columna+len(tax_ids)
        sheet.write_formula('%s%s'% (h[h_index], f_index+1), '=SUM(%s%s:%s%s)' % (h[h_index], first_data_row_index+1, h[h_index], f_index), money)
        # Total
        sheet.write_formula('%s%s'% (h[h_index+1], f_index+1), '=SUM(%s%s:%s%s)' % (h[h_index+1], first_data_row_index+1, h[h_index+1], f_index), money)
        

        # Ancho de columnas
        # Contacto
        sheet.set_column('A:A', 15)
        # Nombre
        sheet.set_column('B:B', 30)
        # Documento
        sheet.set_column('C:C', 15)
        # Clave
        sheet.set_column('D:D', 20)
        # Consecutivo
        sheet.set_column('E:E', 20)
        # Fecha
        sheet.set_column('F:F', 10)
        # Subtotal
        sheet.set_column('G:G', 20)
        # Impuestos
        sheet.set_column('%s:%s' % (h[columna], h[columna+len(tax_ids)+1]), 15)
        # Moneda
        sheet.set_column('%s:%s' % (h[columna+len(tax_ids)+2], h[columna+len(tax_ids)+2]), 7)
        # Tipo de Cambio
        sheet.set_column('%s:%s' % (h[columna+len(tax_ids)+3], h[columna+len(tax_ids)+3]), 13)
        # Total en la Moneda de la Factura
        sheet.set_column('%s:%s' % (h[columna+len(tax_ids)+4], h[columna+len(tax_ids)+4]), 20)
