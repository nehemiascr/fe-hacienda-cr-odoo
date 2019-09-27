# -*- coding: utf-8 -*-
# Part of Fakturacion. See LICENSE file for full copyright and licensing details.
import logging
from odoo import api, fields, models
from lxml import etree
import base64
import re

_logger = logging.getLogger(__name__)

class ElectronicInvoiceCostaRicaMixin(models.AbstractModel):
    _name = 'eicr.mixin'
    _description = 'Mixin class for attaching eicr electronic documents to odoo objects'

    eicr_clave = fields.Char('Clave', copy=False, index=True)
    eicr_consecutivo = fields.Char('Consecutivo', copy=False, index=True)
    eicr_date = fields.Datetime('Fecha de Emisión', readonly=True, default=fields.Datetime.now(), copy=False)
    eicr_state = fields.Selection([
        ('pendiente', 'Pendiente'), ('recibido', 'Recibido'),
        ('procesando', 'Procesando'), ('aceptado', 'Aceptado'),
        ('rechazado', 'Rechazado'), ('na', 'No Aplica'),
        ('error', 'Error'), ('ne', 'No Encontrado')],'Estado FE', copy=False)
    eicr_aceptacion = fields.Selection([('1', 'Aceptado'),
                                        ('2', 'Aceptacion parcial'),
                                        ('3', 'Rechazado'), ],
                                        'Tipo de Aceptación', copy=False)
    eicr_reference_code_id = fields.Many2one('eicr.reference_code', 'Código de referencia', copy=False)
    eicr_reference_document_id = fields.Many2one('eicr.reference_document', string='Documento de referencia', copy=False)
    eicr_payment_method_id = fields.Many2one('eicr.payment_method', 'Métodos de Pago')

    eicr_mensaje_hacienda_file = fields.Binary(string='Mensaje de Hacienda XML', copy=False, attachment=True)
    eicr_mensaje_hacienda_fname = fields.Char(string='Nombre del archivo XML Mensaje de Hacienda', copy=False)
    eicr_mensaje_hacienda = fields.Text(string='Contenido del Mensaje de Hacienda', readonly=True, copy=False)

    eicr_documento_tipo = fields.Many2one('eicr.document', 'Tipo de Comprobante', copy=False)
    eicr_documento_file = fields.Binary(string='Comprobante Elecrónico XML', copy=False, attachment=True)
    eicr_documento_fname = fields.Char(string='Nombre de archivo Comprobante XML', copy=False, attachment=True)

    eicr_documento2_tipo = fields.Many2one('eicr.document', 'Tipo de Documento', copy=False)
    eicr_documento2_file = fields.Binary(string='Documento Elecrónico XML', copy=False, attachment=True)
    eicr_documento2_fname = fields.Char(string='Nombre del archivo del Documento Electrónico XML', copy=False, attachment=True)

    eicr_credito_iva = fields.Float('Porcentaje del impuesto a acreditar', digits=(3, 2))
    eicr_credito_iva_condicion = fields.Many2one('eicr.iva.credit_condition', 'Condición del Impuesto')

    _sql_constraints = [
        ('eicr_clave_uniq', 'unique (eicr_clave)', 'Ya existe un documento con esa clave.'),
    ]

    @api.onchange('eicr_credito_iva_condicion')
    def _onchange_eicr_credito_iva_condicion(self):

        if self.eicr_credito_iva_condicion.code == '01': # Genera crédito IVA
            self.eicr_credito_iva = 100.0
        elif self.eicr_credito_iva_condicion.code == '02': # Genera Crédito parcial del IVA
            self.eicr_credito_iva = self.company_id.eicr_factor_iva or 100.0
        else:
            self.eicr_credito_iva = 0

    @api.model
    def set_document(self):
        if self.env['eicr.tools'].validar_receptor(self.partner_id):
            self.eicr_documento_tipo = self.env.ref('eicr_base.FacturaElectronica_V_4_3')
        else:
            self.eicr_documento_tipo = self.env.ref('eicr_base.TiqueteElectronico_V_4_3')


    @api.model
    def _get_clave_mr(self):
        if not self.eicr_documento2_file: return False
        try:
            xml = base64.b64decode(self.eicr_documento2_file)
            Documento = etree.tostring(etree.fromstring(xml)).decode()
            Documento = etree.fromstring(re.sub(' xmlns="[^"]+"', '', Documento, count=1))
            Clave = Documento.find('Clave')
            return Clave.text
        except Exception as e:
            print('Error con % %' % (xml, e))
            return False
