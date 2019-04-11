# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).


import odoo.addons.decimal_precision as dp
from odoo.tools import float_compare
import json
import requests
import logging
import re
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval
import datetime
import pytz
import base64
from lxml import etree
from . import functions

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    ticket_hacienda_invoice_number = fields.Char(
        'Simplified invoice',
        copy=False,
        oldname='simplified_invoice',
    )
    number_electronic = fields.Char(string="Clave", copy=False, index=True)
    fecha = fields.Datetime('Fecha de Emisión', readonly=True, default=fields.Datetime.now(), copy=False)

    date_issuance = fields.Char(string="Fecha de emisión", copy=False)

    state_tributacion = fields.Selection([
        ('pendiente', 'Pendiente'),
        ('aceptado', 'Aceptado'),
        ('rechazado', 'Rechazado'),
        ('recibido', 'Recibido'),
        ('error', 'Error'),
        ('procesando', 'Procesando')], 'Estado FE',
        copy=False)

    respuesta_tributacion = fields.Text(string="Mensaje en la Respuesta de Tributación", readonly=True, copy=False)

    xml_respuesta_tributacion = fields.Binary(string="Respuesta Tributación XML", required=False, copy=False,
                                              attachment=True)

    fname_xml_respuesta_tributacion = fields.Char(string="Nombre de archivo XML Respuesta Tributación", required=False,
                                                  copy=False)

    xml_comprobante = fields.Binary(string="Comprobante XML", required=False, copy=False, attachment=True)

    fname_xml_comprobante = fields.Char(string="Nombre de archivo Comprobante XML", required=False, copy=False,
                                        attachment=True)


    @api.model
    def _simplified_limit_check(self, amount_total, limit=3000):
        precision_digits = dp.get_precision('Account')(self.env.cr)[1]
        # -1 or 0: amount_total <= limit, simplified
        #       1: amount_total > limit, can not be simplified
        return float_compare(
            amount_total, limit, precision_digits=precision_digits) < 0

    @api.model
    def _order_fields(self, ui_order):
        res = super(PosOrder, self)._order_fields(ui_order)
        res.update({
            'ticket_hacienda_invoice_number': ui_order.get(
                'simplified_invoice', ''),
        })
        return res

    @api.model
    def _process_order(self, order):

        _logger.info('order %s' % order)
        pos_order = super(PosOrder, self)._process_order(order)
        _logger.info('pos_order %s' % pos_order.__dict__)

        now_utc = datetime.datetime.now(pytz.timezone('UTC'))
        now_cr = now_utc.astimezone(pytz.timezone('America/Costa_Rica'))

        pos_order.fecha = now_cr.strftime('%Y-%m-%d %H:%M:%S')
        pos_order.date_issuance = now_cr.strftime("%Y-%m-%dT%H:%M:%S-06:00")

        xml_firmado = self.env['facturacion_electronica'].get_xml(pos_order)

        if xml_firmado:
            pos_order.xml_comprobante = xml_firmado
            pos_order.fname_xml_comprobante = 'TiqueteElectronico_' + pos_order.number_electronic + '.xml'
            pos_order.state_tributacion = 'pendiente'

        return pos_order