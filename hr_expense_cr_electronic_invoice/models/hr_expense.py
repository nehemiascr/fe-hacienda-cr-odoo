# -*- coding: utf-8 -*-
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).


import logging
from odoo import models, fields, api, _
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


    def action_cargar_xml(self, vals):
        _logger.info('action_cargar_xml self %s' % self)
        _logger.info('action_cargar_xml vals %s' % vals)

        # return {
        #     'type': 'ir.actions.act_window',
        #     'res_model': 'facturacion_electronica',
        #     'view_type': 'form',
        #     'view_mode': 'form',
        #     'target': 'new',
        #     # 'res_id': self.id,
        #     'context': dict(self._context),
        # }

    def action_enviar_aceptacion(self, vals):
        _logger.info('action_enviar_mensaje self %s' % self)
        _logger.info('action_enviar_mensaje vals %s' % vals)
        self.env['facturacion_electronica'].enviar_aceptacion(self)

    def action_consultar_recepcion(self, vals):
        _logger.info('action_consultar_recepcion self %s' % self)
        _logger.info('action_consultar_recepcion vals %s' % vals)
        if self.state_tributacion in ('aceptado', 'rechazado', 'recibido', 'error', 'procesando'):
            self.env['facturacion_electronica']._consultar_documento(self)


    @api.onchange('xml_supplier_approval')
    def _onchange_xml_supplier_approval(self):
        _logger.info('cargando xml de proveedor')

        fe = self.env['facturacion_electronica']

        if self.xml_supplier_approval and fe.validar_xml_proveedor(self.xml_supplier_approval):

            xml = base64.b64decode(self.xml_supplier_approval)
            _logger.info('xml %s' % xml)

            factura = etree.tostring(etree.fromstring(xml)).decode()
            factura = etree.fromstring(re.sub(' xmlns="[^"]+"', '', factura, count=1))

            Clave = factura.find('Clave')
            NumeroConsecutivo = factura.find('NumeroConsecutivo')
            FechaEmision = factura.find('FechaEmision')
            Emisor = factura.find('Emisor')
            Receptor = factura.find('Receptor')

            CondicionVenta = factura.find('CondicionVenta')
            PlazoCredito = factura.find('PlazoCredito')

            emisor = Emisor.find('Identificacion').find('Numero').text

            _logger.info('buscando %s' % emisor)
            proveedor = self.env['res.partner'].search([('vat', '=', emisor)])

            _logger.info('resultado %s' % proveedor)


            self.date = FechaEmision.text

            _logger.info('NumeroConsecutivo %s' % NumeroConsecutivo)
            self.reference = NumeroConsecutivo.text

            self.unit_amount = factura.find('ResumenFactura').find('TotalComprobante').text
            self.quantity = 1.0
            self.state_tributacion = 'pendiente'

            self.number_electronic = Clave.text

            # respuesta = fe.



        # else:
        #     self.state_tributacion = False
        #     self.xml_supplier_approval = False
        #     self.fname_xml_supplier_approval = False
        #     self.xml_respuesta_tributacion = False
        #     self.fname_xml_respuesta_tributacion = False
        #     self.date_issuance = False
        #     self.number_electronic = False
        #     self.state_invoice_partner = False

    # @api.model
    # def _process_order(self, order):
    #
    #     _logger.info('order %s' % order)
    #     pos_order = super(PosOrder, self)._process_order(order)
    #     _logger.info('pos_order %s' % pos_order.__dict__)
    #
    #     now_utc = datetime.datetime.now(pytz.timezone('UTC'))
    #     now_cr = now_utc.astimezone(pytz.timezone('America/Costa_Rica'))
    #
    #     pos_order.fecha = now_cr.strftime('%Y-%m-%d %H:%M:%S')
    #     pos_order.date_issuance = now_cr.strftime("%Y-%m-%dT%H:%M:%S-06:00")
    #
    #     xml_firmado = self.env['facturacion_electronica'].get_xml(pos_order)
    #
    #     if xml_firmado:
    #         pos_order.xml_comprobante = xml_firmado
    #         pos_order.fname_xml_comprobante = 'TiqueteElectronico_' + pos_order.number_electronic + '.xml'
    #         pos_order.state_tributacion = 'pendiente'
    #
    #     return pos_order