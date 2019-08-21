# -*- coding: utf-8 -*-
# Part of Fakturacion. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class ElectronicInvoiceCostaRicaMixin(models.AbstractModel):
    _name = "eicr.mixin"

    eicr_clave = fields.Char("Clave", copy=False, index=True)
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
    eicr_reference_code_id = fields.Many2one("eicr.reference_code", "Código de referencia", copy=False)
    eicr_reference_document_id = fields.Many2one("eicr.reference_document", string="Documento de referencia", copy=False)
    eicr_payment_method_id = fields.Many2one("eicr.payment_method", "Métodos de Pago")

    eicr_mensaje_hacienda_file = fields.Binary(string="XML MensajeHacienda", copy=False, attachment=True)
    eicr_mensaje_hacienda_fname = fields.Char(string="Nombre de archivo XML Mensaje de Hacienda", copy=False)
    eicr_mensaje_hacienda = fields.Text(string="Contenido del Mensaje de Hacienda", readonly=True, copy=False)

    eicr_documento_tipo = fields.Many2one("eicr.schema", "Tipo de Documento", copy=False)
    eicr_documento_file = fields.Binary(string="Comprobante XML", copy=False, attachment=True)
    eicr_documento_fname = fields.Char(string="Nombre de archivo Comprobante XML", copy=False, attachment=True)

    eicr_documento2_tipo = fields.Many2one("eicr.schema", "Tipo de Documento 2", copy=False)
    eicr_documento2_file = fields.Binary(string="Comprobante XML 2", copy=False, attachment=True)
    eicr_documento2_fname = fields.Char(string="Nombre de archivo Comprobante XML 2", copy=False, attachment=True)

    credito_iva = fields.Float('Porcentaje del Impuesto a acreditar', digits=(3, 2))
    credito_iva_condicion = fields.Many2one("eicr.credit_condition", "Condición del Impuesto")

    _sql_constraints = [
        ('eicr_clave_uniq', 'unique (eicr_clave)', "Ya existe un documento con esa clave."),
    ]


