# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import datetime
import logging, re

_logger = logging.getLogger(__name__)

class CabysProducto(models.Model):
    _inherit = 'cabys.producto'

    exoneration_ids = fields.Many2many(comodel_name='eicr.exoneration')


class ElectronicInvoiceCostaRicaExonerationType(models.Model):
    _name = 'eicr.exoneration_type'
    _description = 'Tipos de Exoneración'

    code = fields.Char('Código')
    name = fields.Char('Descripcion')
    notes = fields.Text('Notas')


class ElectronicInvoiceCostaRicaExoneration(models.Model):
    _name = "eicr.exoneration"
    _description = 'Exoneración'

    name = fields.Char('Número de Documento')
    identificacion = fields.Char("Identificación")
    codigo_proyecto_cfia = fields.Char("Código Proyecto CFIA")
    fecha_emision = fields.Date("Fecha de Emisión")
    fecha_vencimiento = fields.Date("Fecha de Vencimiento")
    percentage_exoneration = fields.Float("Porcentaje de exoneración")
    tipo_documento_id = fields.Many2one('eicr.exoneration_type')
    nombre_institucion = fields.Char('Nombre Institución')
    cabys_ids = fields.Many2many('cabys.producto')
    tax_id = fields.Many2one('account.tax', 'Impuesto', domain=[('type_tax_use', '=', 'sale')], required=True)

    json = fields.Text("JSON received by hacienda")
    partner_id = fields.Many2one('res.partner')

    @api.onchange('name')
    def onchange_name(self):
        info = self.env['eicr.hacienda'].get_exoneration(self.name)
        print(info)
        if info:
            if 'identificacion' in info: 
                self.identificacion = info['identificacion']
                all_partners = self.env['res.partner'].search([('vat', '!=', '')])
                partner_id = all_partners.filtered(lambda p: re.sub('[^0-9]', '', p.vat or '') == self.identificacion)
                partner_id = partner_id.filtered(lambda p: not p.parent_id)
                if partner_id:
                    self.partner_id = partner_id
            if 'codigoProyectoCFIA' in info: 
                self.codigo_proyecto_cfia = info['codigoProyectoCFIA']
            if 'fechaEmision' in info: 
                fechaEmision = datetime.strptime(info['fechaEmision'], '%Y-%m-%dT%H:%M:%S')
                self.fecha_emision = fechaEmision.date()
            if 'fechaVencimiento' in info: 
                fechaVencimiento = datetime.strptime(info['fechaVencimiento'], '%Y-%m-%dT%H:%M:%S')
                self.fecha_vencimiento = fechaVencimiento.date()
            if 'porcentajeExoneracion' in info: 
                self.percentage_exoneration = info['porcentajeExoneracion']
            if 'tipoDocumento' in info:
                tipo_documento_id = self.env['eicr.exoneration_type'].search([('code', '=', info['tipoDocumento']['codigo'])])
                if not tipo_documento_id:
                    vals = {'code': info['tipoDocumento']['codigo'], 'name': info['tipoDocumento']['descripcion']}
                    self.env['eicr.exoneration_type'].create(vals)
                    tipo_documento_id = self.env['eicr.exoneration_type'].search([('code', '=', info['tipoDocumento']['codigo'])])
                self.tipo_documento_id = tipo_documento_id
            if 'nombreInstitucion' in info:
                self.nombre_institucion = info['nombreInstitucion']
            if 'poseeCabys' in info and info['poseeCabys']:
                self.cabys_ids = self.env['cabys.producto'].search([('codigo', 'in', info['cabys'])])
            
            self.json = info

            self.tax_id = self.env['account.tax'].search([('type_tax_use', '=', 'sale'), ('amount', '=', -(self.percentage_exoneration))],limit=1)