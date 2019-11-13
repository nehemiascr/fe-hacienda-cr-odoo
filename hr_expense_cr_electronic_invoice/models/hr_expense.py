# -*- coding: utf-8 -*-
# info@fakturacion.com OPL-1


import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import float_compare
from odoo.addons import decimal_precision as dp
import datetime
import base64
import re
from lxml import etree
import pytz

_logger = logging.getLogger(__name__)


class HrExpense(models.Model):
    _inherit = 'hr.expense'

    number = fields.Char(string='Consecutivo', store=True, readonly=True, copy=False)
    number_electronic = fields.Char(string="Clave", copy=False, index=True)
    date_issuance = fields.Char(string="Fecha de emisión", copy=False)

    state_tributacion = fields.Selection([
        ('pendiente', 'Pendiente'),
        ('aceptado', 'Aceptado'),
        ('rechazado', 'Rechazado'),
        ('recibido', 'Recibido'),
        ('error', 'Error'),
        ('procesando', 'Procesando'),
        ('na', 'No Aplica'),
        ('ne', 'No Encontrado')],
        'Estado FE', copy=False, default='na')

    state_invoice_partner = fields.Selection([('1', 'Aceptado'),
                                              ('2', 'Aceptacion parcial'),
                                              ('3', 'Rechazado'), ],
                                             'Tipo de Aceptación', copy=False)


    xml_supplier_approval = fields.Binary(string="XML Proveedor", copy=False, attachment=True)
    fname_xml_supplier_approval = fields.Char(string="Nombre de archivo Comprobante XML proveedor", copy=False, attachment=True)

    xml_comprobante = fields.Binary(string="Comprobante XML", copy=False, attachment=True)
    fname_xml_comprobante = fields.Char(string="Nombre de archivo Comprobante XML", copy=False, attachment=True)

    xml_respuesta_tributacion = fields.Binary(string="Respuesta Tributación XML", copy=False, attachment=True)
    fname_xml_respuesta_tributacion = fields.Char(string="Nombre de archivo XML Respuesta Tributación", copy=False)
    respuesta_tributacion = fields.Text(string="Mensaje en la Respuesta de Tributación", readonly=True, copy=False)

    credito_iva = fields.Float('Porcentaje del Impuesto a acreditar', digits=(3,2), default=100)
    credito_iva_condicion = fields.Many2one("credit.conditions", "Condición del Impuesto")

    partner_id = fields.Many2one('res.partner', 'Proveedor')

    @api.model
    def create(self, vals):
        _logger.info('create %s' % vals)
        if 'xml_supplier_approval' in vals:
            if 'partner_id' not in vals:
                partner_id = self.env['eicr.tools'].get_partner_emisor(vals['xml_supplier_approval'])
                if partner_id:
                    vals['partner_id'] = partner_id.id
            if 'state_tributacion' not in vals:
                vals['state_tributacion'] = 'pendiente'
        expense = super(HrExpense, self).create(vals)
        print('expense %s' % expense)
        return expense

    def action_enviar_aceptacion(self, vals):
        _logger.info('action_enviar_mensaje self %s vals %s' % (self, vals))
        self.env['eicr.tools'].enviar_aceptacion(self)

    def action_consultar_hacienda(self, vals):
        _logger.info('action_consultar_hacienda self %s vals %s' % (self, vals))
        if self.state_tributacion in ('aceptado', 'rechazado', 'recibido', 'error', 'procesando'):
            self.env['eicr.hacienda']._consultar_documento(self)


    @api.onchange('xml_supplier_approval')
    def _onchange_xml_supplier_approval(self):
        _logger.info('cargando xml de proveedor')

        fe = self.env['eicr.tools']

        if self.xml_supplier_approval and fe.validar_xml_proveedor(self.xml_supplier_approval):

            xml = base64.b64decode(self.xml_supplier_approval)

            factura = etree.tostring(etree.fromstring(xml)).decode()
            factura = etree.fromstring(re.sub(' xmlns="[^"]+"', '', factura, count=1))

            Clave = factura.find('Clave')
            NumeroConsecutivo = factura.find('NumeroConsecutivo')
            FechaEmision = factura.find('FechaEmision')
            Emisor = factura.find('Emisor')
            Receptor = factura.find('Receptor')

            vat_receptor = Receptor.find('Identificacion').find('Numero').text
            vat_company = re.sub('[^0-9]', '', self.company_id.vat or '')

            if vat_company != vat_receptor:
                nombre_receptor = Receptor.find('Nombre').text
                raise UserError(_('El xml que esta intentando usar no es para esta compañia, es para\n%s - %s' % ( vat_receptor, nombre_receptor)))

            vat_proveedor = Emisor.find('Identificacion').find('Numero').text
            tipo_proveedor = Emisor.find('Identificacion').find('Tipo').text
            _logger.info('buscando %s' % vat_proveedor)
            proveedor = self.env['res.partner'].search([('vat', '=', vat_proveedor)])

            if not proveedor:
                proveedor = self.env['eicr.tools'].new_partner_from_xml(self.xml_supplier_approval)

            self.partner_id = proveedor
            self.date = FechaEmision.text
            self.reference = NumeroConsecutivo.text
            self.unit_amount = factura.find('ResumenFactura').find('TotalComprobante').text
            self.quantity = 1.0
            self.state_tributacion = 'pendiente'
            self.number_electronic = Clave.text

