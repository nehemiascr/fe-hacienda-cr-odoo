# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)


class AccountInvoice(models.Model):

    _inherit = "account.invoice"


    @api.multi
    def action_convertir_en_gasto(self):
        _logger.info('%s of type %s' % (self, self.mapped('type')))
        for i, invoice in enumerate(self):
            if invoice.type == 'in_invoice' and invoice.state == 'draft':
                _logger.info('%s/%s la podemos convertir %s' % (i, len(self), invoice))

                product = self.env.ref('hr_expense.product_product_fixed_cost') or \
                          self.env['product.product'].search(['can_be_expensed']).sorted()
                quantity = 1.0
                unit_amount = invoice.amount_total
                tax_ids = invoice.tax_line_ids.mapped('tax_id').mapped('id')
                if tax_ids:
                    unit_amount -= (unit_amount * tax_ids[0] / 100)

                name = invoice.invoice_line_ids.sorted('price_subtotal')[-1].name[:32]

                expense = self.env['hr.expense'].create({'name': '%s con %s' % (name, invoice.partner_id.name[:20]),
                                               'quantity': quantity,
                                               'product_id': product.id,
                                               'unit_amount': unit_amount,
                                               'tax_ids': [(6, 0, tax_ids)],
                                               'xml_supplier_approval': invoice.xml_supplier_approval,
                                               'fname_xml_supplier_approval': invoice.fname_xml_supplier_approval,
                                               'state_invoice_partner': '1',
                                               'state_tributacion': 'na',
                                               'credito_iva': 100,
                                               'credito_iva_condicion': self.env.ref('cr_electronic_invoice.CreditConditions_1').id,
                                               'reference': invoice.reference,
                                               'account_id': product.property_account_expense_id.id})
                invoice.unlink()

                return {'type': 'ir.actions.act_window',
                        'res_model': 'hr.expense',
                        'view_mode': 'form',
                        'res_id': expense.id,
                        'target': 'self'}






