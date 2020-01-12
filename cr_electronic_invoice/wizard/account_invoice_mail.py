# -*- coding: utf-8 -*-

from odoo import models, fields, api, _, tools
import logging, ast
from lxml import etree
import re, base64


_logger = logging.getLogger(__name__)

class AccountInvoiceMail(models.TransientModel):
    _name = "account.invoice.mail"
    _inherit = "mail.thread"
    _description = "Recepción de comprobantes por email"

    name = fields.Text('Nombre', compute='_compute_from_data', store=True,  readonly=True)
    data = fields.Text('data')


    @api.one
    def _compute_from_data(self):
        self.name = 'okokokok'

    @api.model
    def create(self, values):
        _logger.info('self %s' % self)
        _logger.info('values %s' % values)
        record = super(AccountInvoiceMail, self).create(values)
        _logger.info('record %s' % record)
        return record

    def _get_partner_from_xml(self, xml_encoded):
        xml = etree.fromstring(base64.b64decode(xml_encoded))
        namespace = xml.nsmap[None]
        xml = etree.tostring(xml).decode()
        xml = re.sub(' xmlns="[^"]+"', '', xml)
        xml = etree.fromstring(xml)

        if (xml.find('Emisor') is None or
            xml.find('Emisor').find('Identificacion') is None or
            xml.find('Emisor').find('Identificacion').find('Tipo') is None or
            xml.find('Emisor').find('Identificacion').find('Numero') is None):
                return None

        Emisor = xml.find('Emisor')
        emisor_vat = Emisor.find('Identificacion').find('Numero').text
        emisor_tipo = Emisor.find('Identificacion').find('Tipo').text

        supplier = self.env['res.partner'].search([]).filtered( lambda p: re.sub('[^0-9]', '', p.vat or '') == emisor_vat)

        if not supplier:
            ctx = self.env.context.copy()
            ctx.pop('default_type', False)
            tipo = self.env['identification.type'].search([('code', '=', emisor_tipo)])

            is_company = True if tipo.code == '02' else False

            phone_code = ''
            if Emisor.find('Telefono') and Emisor.find('Telefono').find('CodigoPais'):
                phone_code = Emisor.find('Telefono').find('CodigoPais').text

            phone = ''
            if Emisor.find('Telefono') and Emisor.find('Telefono').find('NumTelefono'):
                phone = Emisor.find('Telefono').find('NumTelefono').text

            email = Emisor.find('CorreoElectronico').text
            name = Emisor.find('Nombre').text

            supplier = self.env['res.partner'].with_context(ctx).create({'name': name,
                                                                         'email': email,
                                                                         'phone_code': phone_code,
                                                                         'phone': phone,
                                                                         'vat': emisor_vat,
                                                                         'identification_id': tipo.id,
                                                                         'is_company': is_company,
                                                                         'customer': False,
                                                                         'supplier': True})
            _logger.info('nuevo proveedor %s' % supplier)
        return supplier





    @api.model
    def message_new(self, msg, custom_values=None):
        """ Overrides mail_thread message_new that is called by the mailgateway
            through message_process.
            This override updates the document according to the email.
        """
        if custom_values is None:
            custom_values = {}

        documents = []
        for i, attachment in enumerate(msg['attachments']):
            _logger.info('%s/%s attachment %s' % (i+1, len(msg['attachments']), attachment))
            clave = self.validar_xml_proveedor(attachment.content)
            if clave:
                invoice = self.env['account.invoice'].search([('type', '=', 'in_invoice'), ('number_electronic', '=', clave)])
                if not invoice:
                    consecutivo = clave[21:41]
                    invoice = self.env['account.invoice'].search([('reference', '=', consecutivo), ('state', '=', 'draft')])
                if not invoice:
                    documents.append({'clave': clave, 'xml': attachment.content, 'filename': attachment.fname})

        journal = self.env['account.journal'].search([('type', '=', 'purchase')], limit=1)
        # 0-211001 0-Cuentas por pagar a proveedores
        account = self.env.ref('l10n_cr.1_account_account_template_0_211001')

        for i, doc in enumerate(documents):
            _logger.info('%s/%s valid doc %s' % (i+1, len(documents), doc))
            xml_encoded = base64.b64encode(doc['xml']).decode('utf-8')

            partner_id = self._get_partner_from_xml(xml_encoded)




            invoice = self.env['account.invoice'].create({'type': 'in_invoice',
                                                          'xml_supplier_approval': xml_encoded,
                                                          'fname_xml_supplier_approval': doc['filename'],
                                                          'journal_id':journal.id,
                                                          'account_id':account.id,
                                                          'partner_id': partner_id.id})
            # invoice.eicr_documento2_tipo = self.env.ref('cr_electronic_invoice.FacturaElectronica_V_4_3')

            self.env['eicr.tools']._process_supplier_invoice(invoice)

            # data = invoice.copy_data()[0]
            # data['reference_type'] = 'none'
            # codigo = 'CRC'
            # data['currency_id'] = self.env['res.currency'].search([('name', '=', codigo)]).id
            # _logger.info('new vals %s' % data)
            #
            # i2 = self.env['account.invoice'].create(data)
            # _logger.info('i2 %s' % i2)

            invoice.compute_taxes()
            invoice.state_invoice_partner = '1'
            invoice.credito_iva = 100
            invoice.credito_iva_condicion = self.env.ref('cr_electronic_invoice.CreditConditions_1')

            self.env.cr.commit()
            _logger.info('invoice %s' % invoice)

        message = super(AccountInvoiceMail, self).message_new(msg, custom_values=custom_values)
        _logger.info('message %s' % message)
        return message

    @api.model
    def validar_xml_proveedor(self, xml):
        _logger.info('validando xml de proveedor para %s' % object)

        try:

            xml = etree.tostring(etree.fromstring(xml)).decode()
            xml = re.sub(' xmlns="[^"]+"', '', xml)
            xml = etree.fromstring(xml)
            document = xml.tag

            if document not in ('FacturaElectronica', 'TiqueteElectronico'):
                message = 'El archivo xml debe ser una FacturaElectronica o TiqueteElectronico. %s es un documento inválido' % document
                _logger.info('%s %s' % (object, message))
                return False

            if (xml.find('Clave') is None or
                    xml.find('FechaEmision') is None or
                    xml.find('Emisor') is None or
                    xml.find('Emisor').find('Identificacion') is None or
                    xml.find('Emisor').find('Identificacion').find('Tipo') is None or
                    xml.find('Emisor').find('Identificacion').find('Numero') is None or
                    xml.find('Receptor') is None or
                    xml.find('Receptor').find('Identificacion') is None or
                    xml.find('Receptor').find('Identificacion').find('Tipo') is None or
                    xml.find('Receptor').find('Identificacion').find('Numero') is None or
                    xml.find('ResumenFactura') is None or
                    xml.find('ResumenFactura').find('TotalComprobante') is None):
                message = 'El archivo xml parece estar incompleto, no se puede procesar.\nDocumento %s' % document
                _logger.info('%s %s' % (object, message))
                return False

            return xml.find('Clave').text

        except Exception as e:
            _logger.info(e)
            return False
