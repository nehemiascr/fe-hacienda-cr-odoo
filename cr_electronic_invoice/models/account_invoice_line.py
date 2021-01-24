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