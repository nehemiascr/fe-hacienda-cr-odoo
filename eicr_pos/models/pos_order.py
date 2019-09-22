# -*- coding: utf-8 -*-

import logging
from odoo.exceptions import UserError
from odoo import models, fields, api, _
from lxml import etree
import random
import base64
import re


_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _name = 'pos.order'
    _inherit = ['pos.order', 'eicr.mixin']


    def action_consultar_hacienda(self, vals):
        _logger.info('action_consultar_hacienda self %s' % self)
        _logger.info('action_consultar_hacienda vals %s' % vals)
        if self.eicr_state in ('aceptado', 'rechazado', 'recibido', 'error', 'procesando'):
            self.env['eicr.hacienda']._consultar_documento(self)

    @api.model
    def _process_order(self, order):

        _logger.info('order %s' % order)
        pos_order = super(PosOrder, self)._process_order(order)
        _logger.info('pos_order %s' % pos_order.__dict__)

        pos_order.make_xml()

        return pos_order

    def get_consecutivo(self):
        # el consecutivo tiene 20 digitos
        if self.eicr_consecutivo and len(self.eicr_consecutivo) == 20 and self.eicr_consecutivo.isdigit(): return self.eicr_consecutivo
        # la secuencia tiene 10 digitos
        if len(self.name) != 10 or not self.name.isdigit(): return False
        # - sucursal
        sucursal = re.sub('[^0-9]', '', str(self.session_id.config_id.sequence_id.sucursal or '506')).zfill(3)
        # - terminal
        terminal = re.sub('[^0-9]', '', str(self.session_id.config_id.sequence_id.terminal or '506')).zfill(5)
        # - tipo 01 FacturaElectronica, 04 TiqueteElectronio
        tipo = '01' if self.env['eicr.tools'].validar_receptor(self.partner_id) else '04'
        # - numeracion
        numeracion = self.name
        # consecutivo
        self.eicr_consecutivo  = sucursal + terminal + tipo + numeracion

        return self.eicr_consecutivo


    def get_clave(self):
        # la clave tiene 50 digitos
        if self.eicr_clave and len(self.eicr_clave) == 50 and self.eicr_clave.isdigit(): return self.eicr_clave
        # el consecutivo tiene 20 digitos
        if not self.eicr_consecutivo or len(self.eicr_consecutivo) != 20 or not self.eicr_consecutivo.isdigit(): self.get_consecutivo()
        # revisar los datos de la compañía
        self.env['eicr.tools'].validar_emisor(self.company_id)
        # a) código de pais
        codigo_de_pais = '506'
        # fecha
        fecha = self.eicr_date
        # b) día
        dia = fecha.strftime('%d')
        # c) mes
        mes = fecha.strftime('%m')
        # d) año
        anio = fecha.strftime('%y')
        # e) identificación
        identificacion = re.sub('[^0-9]', '', self.company_id.vat).zfill(12)
        # f) consecutivo
        consecutivo = self.eicr_consecutivo
        # g) situación
        situacion = '1'
        # h) código de seguridad
        codigo_de_seguridad = str(random.randint(1, 99999999)).zfill(8)
        # clave
        self.eicr_clave = codigo_de_pais + dia + mes + anio + identificacion + consecutivo + situacion + codigo_de_seguridad

        if len(self.eicr_clave) != 50 or not self.eicr_clave.isdigit():
            _logger.info('Algo anda mal con la clave :( %s' % self.eicr_clave)
            return False
        _logger.info('se genera la clave %s para %s' % (self.eicr_clave, self))
        return self.eicr_clave

    @api.model
    def set_document(self):
        if self.env['eicr.tools'].validar_receptor(self.partner_id):
            self.eicr_documento_tipo = self.env.ref('eicr_base.FacturaElectronica_V_4_3')
        else:
            self.eicr_documento_tipo = self.env.ref('eicr_base.TiqueteElectronico_V_4_3')
        return self.eicr_documento_tipo

    @api.model
    def make_xml(self):
        consecutivo = self.get_consecutivo()
        clave = self.get_clave()
        self.set_document()
        Documento = self.eicr_documento_tipo.get_root_node()

        # Clave
        Clave = etree.Element('Clave')
        Clave.text = self.eicr_clave
        Documento.append(Clave)

        # CodigoActividad
        CodigoActividad = etree.Element('CodigoActividad')
        CodigoActividad.text = self.company_id.eicr_activity_ids[0].code
        Documento.append(CodigoActividad)

        # NumeroConsecutivo
        NumeroConsecutivo = etree.Element('NumeroConsecutivo')
        NumeroConsecutivo.text = self.eicr_consecutivo
        Documento.append(NumeroConsecutivo)

        # FechaEmision
        if not self.eicr_date: self.eicr_date = self.env['eicr.tools'].datetime_obj()
        FechaEmision = etree.Element('FechaEmision')
        FechaEmision.text = self.eicr_date.strftime("%Y-%m-%dT%H:%M:%S")
        Documento.append(FechaEmision)

        # Emisor
        Emisor = self.env['eicr.tools'].get_nodo_emisor(self.company_id)
        Documento.append(Emisor)

        # Receptor
        Receptor = self.env['eicr.tools'].get_nodo_receptor(self.partner_id)
        if Receptor: Documento.append(Receptor)

        # Condicion Venta
        CondicionVenta = etree.Element('CondicionVenta')
        CondicionVenta.text = '01'
        Documento.append(CondicionVenta)

        # MedioPago
        MedioPago = etree.Element('MedioPago')
        MedioPago.text = '01'
        Documento.append(MedioPago)

        # DetalleServicio
        DetalleServicio = etree.Element('DetalleServicio')

        decimales = 2

        totalServiciosGravados = 0.0
        totalServiciosExentos = 0.0
        totalMercanciasGravadas = 0.0
        totalMercanciasExentas = 0.0

        totalDescuentosMercanciasExentas = 0.0
        totalDescuentosMercanciasGravadas = 0.0
        totalDescuentosServiciosExentos = 0.0
        totalDescuentosServiciosGravados = 0.0

        totalImpuesto = 0.0

        impuestoServicio = self.env['account.tax'].search([('tax_code', '=', 'service')])
        servicio = True if impuestoServicio in self.lines.mapped('tax_ids_after_fiscal_position') else False
        indice = 1
        for linea in self.lines:

            LineaDetalle = etree.Element('LineaDetalle')

            NumeroLinea = etree.Element('NumeroLinea')
            NumeroLinea.text = '%s' % indice  # indice + 1
            LineaDetalle.append(NumeroLinea)

            if linea.product_id.default_code:
                CodigoComercial = etree.Element('CodigoComercial')

                Tipo = etree.Element('Tipo')
                Tipo.text = '04'  # Código de uso interno
                CodigoComercial.append(Tipo)

                Codigo = etree.Element('Codigo')
                Codigo.text = linea.product_id.default_code
                CodigoComercial.append(Codigo)

                LineaDetalle.append(CodigoComercial)

            Cantidad = etree.Element('Cantidad')
            Cantidad.text = str(linea.qty)  # linea.qty
            LineaDetalle.append(Cantidad)

            UnidadMedida = etree.Element('UnidadMedida')
            UnidadMedida.text = 'Sp' if (linea.product_id and linea.product_id.type == 'service') else 'Unid'

            LineaDetalle.append(UnidadMedida)

            Detalle = etree.Element('Detalle')
            Detalle.text = linea.product_id.product_tmpl_id.name  # product_tmpl_id.name
            LineaDetalle.append(Detalle)

            precioUnitario = linea.price_unit

            PrecioUnitario = etree.Element('PrecioUnitario')
            PrecioUnitario.text = str(round(precioUnitario, decimales))
            LineaDetalle.append(PrecioUnitario)

            MontoTotal = etree.Element('MontoTotal')
            montoTotal = precioUnitario * linea.qty
            MontoTotal.text = str(round(montoTotal, decimales))

            LineaDetalle.append(MontoTotal)

            if linea.discount:
                Descuento = etree.Element('Descuento')

                MontoDescuento = etree.Element('MontoDescuento')
                montoDescuento = montoTotal - linea.price_subtotal
                if linea.tax_ids_after_fiscal_position:
                    if linea.product_id and linea.product_id.type == 'service':
                        totalDescuentosServiciosGravados += montoDescuento
                    else:
                        totalDescuentosMercanciasGravadas += montoDescuento
                else:
                    if linea.product_id and linea.product_id.type == 'service':
                        totalDescuentosServiciosExentos += montoDescuento
                    else:
                        totalDescuentosMercanciasExentas += montoDescuento

                MontoDescuento.text = str(round(montoDescuento, decimales))
                Descuento.append(MontoDescuento)

                NaturalezaDescuento = etree.Element('NaturalezaDescuento')
                NaturalezaDescuento.text = 'Descuento Comercial'
                Descuento.append(NaturalezaDescuento)

                LineaDetalle.append(Descuento)

            SubTotal = etree.Element('SubTotal')
            SubTotal.text = str(round(linea.price_subtotal, decimales))
            LineaDetalle.append(SubTotal)

            impuestos = linea.tax_ids_after_fiscal_position - impuestoServicio

            if impuestos:
                for impuesto in linea.tax_ids_after_fiscal_position:

                    if impuesto.tax_code != 'service':
                        Impuesto = etree.Element('Impuesto')

                        Codigo = etree.Element('Codigo')
                        Codigo.text = impuesto.tax_code
                        Impuesto.append(Codigo)

                        if impuesto.tax_code == '01':
                            CodigoTarifa = etree.Element('CodigoTarifa')
                            CodigoTarifa.text = impuesto.iva_tax_code
                            Impuesto.append(CodigoTarifa)

                            Tarifa = etree.Element('Tarifa')
                            Tarifa.text = str(round(impuesto.amount, decimales))
                            Impuesto.append(Tarifa)

                        Monto = etree.Element('Monto')
                        monto = linea.price_subtotal * impuesto.amount / 100.0
                        totalImpuesto += monto
                        Monto.text = str(round(monto, decimales))
                        Impuesto.append(Monto)

                        LineaDetalle.append(Impuesto)

                        if linea.product_id and linea.product_id.type == 'service':
                            totalServiciosGravados += linea.price_subtotal
                        else:
                            totalMercanciasGravadas += linea.price_subtotal

            else:
                if linea.product_id and linea.product_id.type == 'service':
                    totalServiciosExentos += linea.price_subtotal
                else:
                    totalMercanciasExentas += linea.price_subtotal

            MontoTotalLinea = etree.Element('MontoTotalLinea')
            montoTotalLinea = linea.price_subtotal_incl
            if servicio:
                _logger.info('mndl %s' % montoTotalLinea)
                deduccion = montoTotalLinea * 10.0 / (100.0 + sum(linea.tax_ids_after_fiscal_position.mapped('amount')))
                _logger.info('mndl %s' % deduccion)
                montoTotalLinea -= deduccion
                _logger.info('mndl %s' % montoTotalLinea)
            MontoTotalLinea.text = str(round(montoTotalLinea, decimales))
            LineaDetalle.append(MontoTotalLinea)

            DetalleServicio.append(LineaDetalle)
            indice += 1

        Documento.append(DetalleServicio)

        if servicio:
            # Otros Cargos
            OtrosCargos = etree.Element('OtrosCargos')

            TipoDocumento = etree.Element('TipoDocumento')
            TipoDocumento.text = '06'
            OtrosCargos.append(TipoDocumento)

            Detalle = etree.Element('Detalle')
            Detalle.text = 'Cargo de Servicio (10%)'
            OtrosCargos.append(Detalle)

            Porcentaje = etree.Element('Porcentaje')
            Porcentaje.text = '10.0'
            OtrosCargos.append(Porcentaje)

            MontoCargo = etree.Element('MontoCargo')
            MontoCargo.text = str(round((self.amount_total - self.amount_tax) * 10.0 / 100.0, decimales))
            OtrosCargos.append(MontoCargo)

            Documento.append(OtrosCargos)

        # ResumenFactura
        ResumenFactura = etree.Element('ResumenFactura')

        if totalServiciosGravados:
            TotalServGravados = etree.Element('TotalServGravados')
            TotalServGravados.text = str(round(totalServiciosGravados + totalDescuentosServiciosGravados, decimales))
            ResumenFactura.append(TotalServGravados)

        if totalServiciosExentos:
            TotalServExentos = etree.Element('TotalServExentos')
            TotalServExentos.text = str(round(totalServiciosExentos + totalDescuentosServiciosExentos, decimales))
            ResumenFactura.append(TotalServExentos)

        if totalMercanciasGravadas:
            TotalMercanciasGravadas = etree.Element('TotalMercanciasGravadas')
            TotalMercanciasGravadas.text = str(
                round(totalMercanciasGravadas + totalDescuentosMercanciasGravadas, decimales))
            ResumenFactura.append(TotalMercanciasGravadas)

        if totalMercanciasExentas:
            TotalMercanciasExentas = etree.Element('TotalMercanciasExentas')
            TotalMercanciasExentas.text = str(
                round(totalMercanciasExentas + totalDescuentosMercanciasExentas, decimales))
            ResumenFactura.append(TotalMercanciasExentas)

        if totalServiciosGravados + totalMercanciasGravadas:
            TotalGravado = etree.Element('TotalGravado')
            TotalGravado.text = str(round(
                totalServiciosGravados + totalDescuentosServiciosGravados + totalMercanciasGravadas + totalDescuentosMercanciasGravadas,
                decimales))
            ResumenFactura.append(TotalGravado)

        if totalServiciosExentos + totalMercanciasExentas:
            TotalExento = etree.Element('TotalExento')
            TotalExento.text = str(round(
                totalServiciosExentos + totalDescuentosServiciosExentos + totalMercanciasExentas + totalDescuentosMercanciasExentas,
                decimales))
            ResumenFactura.append(TotalExento)

        TotalVenta = etree.Element('TotalVenta')
        _logger.info('total %s tax %s' % (self.amount_total, self.amount_tax))
        totalVenta = self.amount_total - self.amount_tax
        totalVenta += totalDescuentosServiciosGravados + totalDescuentosMercanciasGravadas + totalDescuentosServiciosExentos + totalDescuentosMercanciasExentas

        TotalVenta.text = str(round(totalVenta, decimales))
        ResumenFactura.append(TotalVenta)

        if totalDescuentosServiciosGravados + totalDescuentosMercanciasGravadas + totalDescuentosServiciosExentos + totalDescuentosMercanciasExentas:
            TotalDescuentos = etree.Element('TotalDescuentos')
            TotalDescuentos.text = str(round(
                totalDescuentosServiciosGravados + totalDescuentosMercanciasGravadas + totalDescuentosServiciosExentos + totalDescuentosMercanciasExentas,
                decimales))
            ResumenFactura.append(TotalDescuentos)

        TotalVentaNeta = etree.Element('TotalVentaNeta')
        totalVentaNeta = self.amount_total - self.amount_tax

        TotalVentaNeta.text = str(round(totalVentaNeta, decimales))
        ResumenFactura.append(TotalVentaNeta)

        if self.amount_tax:
            TotalImpuesto = etree.Element('TotalImpuesto')
            TotalImpuesto.text = str(round(totalImpuesto, decimales))
            ResumenFactura.append(TotalImpuesto)

        if servicio:
            TotalOtrosCargos = etree.Element('TotalOtrosCargos')
            TotalOtrosCargos.text = str(round((self.amount_total - self.amount_tax) * 10.0 / 100.0, decimales))
            ResumenFactura.append(TotalOtrosCargos)

        TotalComprobante = etree.Element('TotalComprobante')
        TotalComprobante.text = str(round(self.amount_total, decimales))
        ResumenFactura.append(TotalComprobante)

        Documento.append(ResumenFactura)

        xml = etree.tostring(Documento, encoding='UTF-8', xml_declaration=True, pretty_print=True)
        xml_base64_encoded = base64.b64encode(xml).decode('utf-8')
        xml_base64_encoded_firmado = self.env['eicr.tools'].firmar_xml(xml_base64_encoded, self.company_id)

        self.eicr_documento_file = xml_base64_encoded_firmado
        self.eicr_documento_fname = self.eicr_documento_tipo.tag + self.eicr_clave + '.xml'
        self.eicr_state = 'pendiente'