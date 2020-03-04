# -*- coding: utf-8 -*-
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).


import logging
from odoo import models, fields, api, _
from odoo.tools import float_compare
from odoo.addons import decimal_precision as dp
import datetime
import pytz

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    number_electronic = fields.Char(string="Clave", copy=False, index=True)
    fecha = fields.Datetime('Fecha de Emisión', readonly=True, default=fields.Datetime.now(), copy=False)

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
         'Estado FE', copy=False)

    respuesta_tributacion = fields.Text(string="Mensaje en la Respuesta de Tributación", readonly=True, copy=False)

    xml_respuesta_tributacion = fields.Binary(string="Respuesta Tributación XML", required=False, copy=False,
                                              attachment=True)

    fname_xml_respuesta_tributacion = fields.Char(string="Nombre de archivo XML Respuesta Tributación", required=False,
                                                  copy=False)

    xml_comprobante = fields.Binary(string="Comprobante XML", required=False, copy=False, attachment=True)

    fname_xml_comprobante = fields.Char(string="Nombre de archivo Comprobante XML", required=False, copy=False,
                                        attachment=True)

    @api.model
    def sequence_number_sync(self, vals):
        next = vals.get('_sequence_ref_number', False)
        next = int(next) if next else False
        if vals.get('session_id') and next is not False:
            session = self.env['pos.session'].sudo().browse(vals['session_id'])
            if next != session.config_id.sequence_id.number_next_actual:
                session.config_id.sequence_id.number_next_actual = next
        if vals.get('_sequence_ref_number') is not None:
            del vals['_sequence_ref_number']
        if vals.get('_sequence_ref') is not None:
            del vals['_sequence_ref']
        _logger.info('%s %s %s' % (self, vals, next))

    @api.model
    def _order_fields(self, ui_order):
        vals = super(PosOrder, self)._order_fields(ui_order)
        vals['_sequence_ref_number'] = ui_order.get('sequence_ref_number')
        vals['_sequence_ref'] = ui_order.get('sequence_ref')
        return vals

    @api.model
    def _process_order(self, order):

        _logger.info('order %s' % order)
        pos_order = super(PosOrder, self)._process_order(order)
        _logger.info('pos_order %s' % pos_order.__dict__)

        now_utc = datetime.datetime.now(pytz.timezone('UTC'))
        now_cr = now_utc.astimezone(pytz.timezone('America/Costa_Rica'))

        pos_order.fecha = now_cr.strftime('%Y-%m-%d %H:%M:%S')
        pos_order.date_issuance = now_cr.strftime("%Y-%m-%dT%H:%M:%S-06:00")

        xml_firmado = self.env['eicr.tools'].get_xml(pos_order)

        if xml_firmado:
            pos_order.xml_comprobante = xml_firmado

            documento = 'FacturaElectronica' if self.env['eicr.tools']._validar_receptor(pos_order.partner_id) else 'TiqueteElectronico'
            pos_order.fname_xml_comprobante = documento + '_' + pos_order.number_electronic + '.xml'
            pos_order.state_tributacion = 'pendiente'

        return pos_order