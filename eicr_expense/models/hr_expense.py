# -*- coding: utf-8 -*-

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
    _name = 'hr.expense'
    _inherit = ['hr.expense', 'eicr.mixin']

    partner_id = fields.Many2one('res.partner', 'Proveedor')

    @api.model
    def create(self, vals):
        _logger.info('create %s' % vals)
        if 'eicr_documento2_file' in vals:
            if 'partner_id' not in vals:
                partner_id = self.env['eicr.tools'].get_partner_emisor(vals['eicr_documento2_file'])
                if partner_id:
                    vals['partner_id'] = partner_id.id
            if 'eicr_state' not in vals:
                vals['eicr_state'] = 'pendiente'
        expense = super(HrExpense, self).create(vals)
        print('expense %s' % expense)
        return expense


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
        self.env['eicr.tools'].enviar_aceptacion(self)

    def action_consultar_hacienda(self, vals):
        _logger.info('action_consultar_hacienda self %s' % self)
        _logger.info('action_consultar_hacienda vals %s' % vals)
        if self.eicr_state in ('aceptado', 'rechazado', 'recibido', 'error', 'procesando'):
            self.env['eicr.hacienda']._consultar_documento(self)


    @api.onchange('eicr_documento2_file')
    def _onchange_eicr_documento2_file(self):
        _logger.info('cargando xml de proveedor')

        fe = self.env['eicr.tools']

        if self.eicr_documento2_file:
            if fe.validar_xml_proveedor(self):

                xml = base64.b64decode(self.eicr_documento2_file)

                factura = etree.tostring(etree.fromstring(xml)).decode()
                factura = etree.fromstring(re.sub(' xmlns="[^"]+"', '', factura, count=1))

                Clave = factura.find('Clave')
                NumeroConsecutivo = factura.find('NumeroConsecutivo')
                FechaEmision = factura.find('FechaEmision')
                Emisor = factura.find('Emisor')
                Receptor = factura.find('Receptor')

                vat_receptor = Receptor.find('Identificacion').find('Numero').text
                vat_company =  re.sub('[^0-9]', '', self.company_id.vat or '')
                if vat_company != vat_receptor:
                    nombre_receptor = Receptor.find('Nombre').text
                    raise UserError(_('El xml que esta intentando usar no es para esta compañia, es para\n%s - %s' % (vat_receptor, nombre_receptor)))

                vat_proveedor = Emisor.find('Identificacion').find('Numero').text
                tipo_proveedor = Emisor.find('Identificacion').find('Tipo').text
                _logger.info('buscando %s' % vat_proveedor)
                proveedor = self.env['res.partner'].search([('vat', '=', vat_proveedor)])

                if not proveedor:
                    ctx = self.env.context.copy()
                    ctx.pop('default_type', False)
                    tipo = self.env['eicr.identification_type'].search([('code', '=', tipo_proveedor)])

                    is_company = True if tipo.code == '02' else False

                    phone_code = ''
                    if Emisor.find('Telefono') and Emisor.find('Telefono').find('CodigoPais'):
                        phone_code = Emisor.find('Telefono').find('CodigoPais').text

                    phone = ''
                    if Emisor.find('Telefono') and Emisor.find('Telefono').find('NumTelefono'):
                        phone = Emisor.find('Telefono').find('NumTelefono').text

                    email = Emisor.find('CorreoElectronico').text
                    name = Emisor.find('Nombre').text

                    proveedor = self.env['res.partner'].with_context(ctx).create({'name': name,
                                                                                 'email': email,
                                                                                 'phone_code': phone_code,
                                                                                 'phone': phone,
                                                                                 'vat': vat_proveedor,
                                                                                 'eicr_id_type': tipo.id,
                                                                                 'is_company': is_company,
                                                                                 'customer': False,
                                                                                 'supplier': True})
                    _logger.info('nuevo proveedor %s' % proveedor)


                self.partner_id = proveedor
                self.date = FechaEmision.text
                self.reference = NumeroConsecutivo.text
                self.unit_amount = factura.find('ResumenFactura').find('TotalComprobante').text
                self.quantity = 1.0
                self.eicr_state = 'pendiente'
                self.eicr_clave = Clave.text
