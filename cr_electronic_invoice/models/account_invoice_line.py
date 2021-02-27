# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class InvoiceLineElectronic(models.Model):
    _inherit = 'account.invoice.line'

    exoneration_id = fields.Many2one('eicr.exoneration', 'Exoneración')
    discount_note = fields.Char(string="Nota de descuento", required=False, )


    @api.onchange('exoneration_id')
    def _onchange_exoneration_id(self):
        _logger.info('_onchange_exoneration_id %s %s' % (self, self.env.user))
        # update taxes
        self._fix_exoneration()

    def _fix_exoneration(self):
        if not self.exoneration_id:
            # delete the exoneration taxes
            self.invoice_line_tax_ids = self.invoice_line_tax_ids.filtered(lambda t: t.amount >= 0)
            return

        
        if self.invoice_line_tax_ids.filtered(lambda t: t.tax_code == '01'):
            iva_id = self.invoice_line_tax_ids.filtered(lambda t: t.tax_code == '01').sorted(key='amount', reverse = True)[0]
        else:
            iva_filter = [('company_id', '=', self.invoice_id.company_id.id), ('tax_code', '=', '01'), ('type_tax_use', '=', 'sale')]
            iva_id = self.env['account.tax'].search(iva_filter).sorted(key='amount', reverse = True)[0]
        
        exoneration_filter = [('company_id', '=', self.invoice_id.company_id.id), ('amount', '=', -(self.exoneration_id.percentage_exoneration)), ('type_tax_use', '=', 'sale'), ('has_exoneration', '=', True)]
        exoneration_id = self.exoneration_id.tax_id or \
                         self.env['account.tax'].search(exoneration_filter, limit=1)

        if not iva_id or not exoneration_id:
            self.invoice_line_tax_ids = self.invoice_line_tax_ids.filtered(lambda t: t.amount >= 0)
            return
        
        self.invoice_line_tax_ids = iva_id + exoneration_id

    def check_taxes(self):
        if self.invoice_id.company_id.eicr_environment == 'disabled': return
        # Check wether the IVA 4% credit card tax return should be applied on this line.
        # It should be applied for health services, when paying with a credit card,
        # Cabys categoria3 code 931 includes all health services
        cabys_health_services_categoria3_id = self.env['cabys.categoria3'].search([('codigo', '=', '931')])
        cabys_product_id = self.product_id and self.product_id.cabys_product_id or self.product_id.categ_id.cabys_product_id or self.invoice_id.company_id.cabys_product_id
        credit_card_payment_id = self.env['payment.methods'].search([('sequence', '=','02')]) 
        # if it is a health service
        iva4 = self.env['account.tax'].search([('tax_code', '=', '01'), ('iva_tax_code', '=', '04'), ('type_tax_use', '=', 'sale'), ('amount', '=', 4)])
        iva4_devolucion = self.env['account.tax'].search([('tax_code', '=', '01'),('iva_tax_code', '=', '04'),('type_tax_use', '=', 'sale'), ('amount', '=', -4)])        
        if cabys_product_id.cabys_categoria3_id == cabys_health_services_categoria3_id:
            # if paymenth_method is credit card
            if self.invoice_id.payment_methods_id == credit_card_payment_id:
                if iva4 in self.invoice_line_tax_ids:
                    if iva4_devolucion not in self.invoice_line_tax_ids:
                        _logger.info(self.invoice_line_tax_ids)
                        self.invoice_line_tax_ids += iva4_devolucion
                        _logger.info(self.invoice_line_tax_ids)
            elif iva4_devolucion in self.invoice_line_tax_ids:
                self.invoice_line_tax_ids -= iva4_devolucion

    @api.onchange('invoice_line_tax_ids')
    def _onchange_invoice_line_tax_ids(self):
        self.check_taxes()
        