# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError
import xml.etree.ElementTree as ET
import base64
import re
import datetime
import pytz
from lxml import etree
import logging

_logger = logging.getLogger(__name__)


class AccountInvoice(models.Model):
    _name = 'account.invoice'
    _inherit = ['account.invoice', 'eicr.mixin']

    eicr_consecutivo = fields.Char(related='number', copy=False, index=True)


    _sql_constraints = [
        ('eicr_clave_uniq', 'unique (eicr_clave)', "La clave de comprobante debe ser única"),
    ]

    @api.multi
    def action_invoice_sent(self):
        """ Open a window to compose an email, with the edi invoice template
            message loaded by default
        """
        self.ensure_one()
        template = self.env.ref('account.email_template_edi_invoice', False)
        compose_form = self.env.ref('account.account_invoice_send_wizard_form', False)

        comprobante = self.env['ir.attachment'].search(
            [('res_model', '=', 'account.invoice'), ('res_id', '=', self.id),
             ('res_field', '=', 'eicr_documento_file')], limit=1)
        comprobante.name = self.eicr_documento_fname
        comprobante.datas_fname = self.eicr_documento_fname

        attachments = comprobante

        if self.eicr_mensaje_hacienda_file:
            respuesta = self.env['ir.attachment'].search(
                [('res_model', '=', 'account.invoice'), ('res_id', '=', self.id),
                 ('res_field', '=', 'eicr_mensaje_hacienda_file')], limit=1)
            respuesta.name = self.eicr_mensaje_hacienda_fname
            respuesta.datas_fname = self.eicr_mensaje_hacienda_fname

            attachments = attachments | respuesta

        template.attachment_ids = [(6, 0, attachments.mapped('id'))]

        email_to = self.partner_id.email_facturas or self.partner_id.email
        _logger.info('emailing to %s' % email_to)

        ctx = dict(
            default_model='account.invoice',
            default_res_id=self.id,
            default_use_template=bool(template),
            default_template_id=template and template.id or False,
            default_composition_mode='comment',
            mark_invoice_as_sent=True,
            custom_layout="mail.mail_notification_paynow",
            force_email=True,
            default_email_to=email_to
        )
        return {
            'name': _('Send Invoice'),
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'account.invoice.send',
            'views': [(compose_form.id, 'form')],
            'view_id': compose_form.id,
            'target': 'new',
            'context': ctx,
        }



    @api.onchange('eicr_documento2_file')
    def _onchange_eicr_documento2_file(self):
        # sin xml limpiamos los campos de la facturacion electronica
        if not self.eicr_documento2_file:
            _logger.info('no xml')
            self.eicr_state = 'na'
            self.eicr_documento2_file = None
            self.eicr_documento2_fname = None
            self.eicr_mensaje_hacienda_file = None
            self.eicr_mensaje_hacienda_fname = None
            self.eicr_date = None
            self.eicr_clave = None
            self.eicr_aceptacion = None
            return
        # si la factura es de proveedor y esta en borrador, cargamos las lineas
        _logger.info('some xml')
        _logger.info('type %s' % self.type)
        _logger.info('state %s' % self.state)
        if self.type in ('in_invoice', 'in_refund') and self.state in ('draft'):
            _logger.info('processing xml')
            self.env['eicr.tools']._process_supplier_invoice(self)

    @api.multi
    def action_enviar_aceptacion(self, vals):
        _logger.info('action_enviar_mensaje self %s' % self)
        _logger.info('action_enviar_mensaje vals %s' % vals)
        self.env['eicr.tools'].enviar_aceptacion(self)

    @api.multi
    @api.returns('self')
    def refund(self, date_invoice=None, date=None, description=None, journal_id=None, invoice_id=None, eicr_reference_code_id=None):
        if self.company_id.eicr_environment == 'disabled':
            new_invoices = super(AccountInvoice, self).refund()
            return new_invoices
        else:
            new_invoices = self.browse()
            for invoice in self:
                # create the new invoice
                values = self._prepare_refund(invoice, date_invoice=date_invoice, date=date, description=description, journal_id=journal_id)
                values.update({'invoice_id': invoice_id, 'eicr_reference_code_id': eicr_reference_code_id})
                refund_invoice = self.create(values)
                if invoice.type == 'out_invoice':
                    message = _(
                        "This customer invoice credit note has been created from: <a href=# data-oe-model=account.invoice data-oe-id=%d>%s</a><br>Reason: %s") % (
                              invoice.id, invoice.number, description)
                else:
                    message = _(
                        "This vendor bill credit note has been created from: <a href=# data-oe-model=account.invoice data-oe-id=%d>%s</a><br>Reason: %s") % (
                              invoice.id, invoice.number, description)

                refund_invoice.message_post(body=message)
                new_invoices += refund_invoice
            return new_invoices

    @api.onchange('partner_id', 'company_id')
    def _onchange_partner_id(self):
        super(AccountInvoice, self)._onchange_partner_id()
        self.payment_methods_id = self.env.ref('eicr_base.PaymentMethods_1')

    @api.multi
    def action_consultar_hacienda(self):
        if self.company_id.eicr_environment != 'disabled':
            for invoice in self:
                self.env['eicr.hacienda']._consultar_documento(invoice)

    def _action_out_invoice_open(self, invoice):

        if invoice.type not in ('out_invoice', 'out_refund'):
            return invoice

        consecutivo = self.env['eicr.tools']._get_consecutivo(invoice)
        if not consecutivo:
            raise UserError('Error con el consecutivo de la factura %s' % consecutivo)
        invoice.eicr_consecutivo = consecutivo

        clave = self.env['eicr.tools']._get_clave(invoice)
        if not clave:
            raise UserError('Error con la clave de la factura %s' % clave)
        invoice.eicr_clave = clave

        comprobante = self.env['eicr.tools'].get_xml(invoice)

        if comprobante:
            invoice.eicr_documento_file = comprobante

            documento = 'TiqueteElectronico'
            if invoice.type == 'out_refund':
                documento = 'NotaCreditoElectronica'
            elif self.env['eicr.tools'].validar_receptor(invoice.partner_id):
                documento = 'FacturaElectronica'

            invoice.eicr_documento_fname = documento + '_' + invoice.eicr_clave + '.xml'

            invoice.eicr_state = 'pendiente'
        else:
            invoice.eicr_state = 'na'
        print('invoice %s' % invoice)
        return invoice

    def _action_in_invoice_open(self, invoice):

        if invoice.type not in ('in_invoice', 'in_refund'):
            return invoice

        if invoice.eicr_documento2_file:
            consecutivo = self.env['eicr.tools']._get_consecutivo(invoice)
            if not consecutivo:
                raise UserError('Error con el consecutivo de la factura %s' % consecutivo)
            invoice.number = consecutivo

            clave = self.env['eicr.tools']._get_clave(invoice)
            if not clave:
                raise UserError('Error con la clave de la factura %s' % clave)
            invoice.eicr_clave = clave

            comprobante = self.env['eicr.tools'].get_xml(invoice)

            if comprobante:
                invoice.eicr_documento_file = comprobante
                invoice.eicr_documento_fname = 'MensajeReceptor_' + invoice.eicr_clave + '.xml'
                invoice.eicr_state = 'pendiente'
            else:
                invoice.eicr_state = 'error'
        else:
            invoice.eicr_state = 'na'

        return invoice

    @api.multi
    def action_invoice_open(self):
        _logger.info('%s of type %s' % (self, self.type))
        for invoice in self:
            if not invoice.eicr_payment_method_id: invoice.eicr_payment_method_id = self.env.ref('eicr_base.PaymentMethods_1')
            if invoice.eicr_payment_method_id.code == '02':
                iva4 = self.env['account.tax'].search([('tax_code', '=', '01'), ('iva_tax_code', '=', '04'), ('type_tax_use', '=', 'sale')])
                iva4_devolucion = self.env['account.tax'].search([('tax_code', '=', '01'),('iva_tax_code', '=', '04D'),('type_tax_use', '=', 'sale')])
                for line in invoice.invoice_line_ids:
                    if iva4 in line.invoice_line_tax_ids:
                        line.invoice_line_tax_ids = [(4, iva4_devolucion.id)]
                invoice.compute_taxes()

        res = super(AccountInvoice, self).action_invoice_open()

        if self.company_id.eicr_environment != 'disabled':

            for invoice in self:
                invoice.eicr_date = self.env['eicr.tools'].datetime_obj()
                if invoice.type in ('out_invoice', 'out_refund'):
                    self._action_out_invoice_open(invoice)
                elif invoice.type in ('in_invoice', 'in_refund'):
                    self._action_in_invoice_open(invoice)

        return res
