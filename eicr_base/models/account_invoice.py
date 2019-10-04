# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError
import random
import xml.etree.ElementTree as ET
import base64
import re
from datetime import datetime, timedelta
import pytz
from lxml import etree
import logging

_logger = logging.getLogger(__name__)


class AccountInvoice(models.Model):
    _name = 'account.invoice'
    _inherit = ['account.invoice', 'eicr.mixin']

    eicr_consecutivo = fields.Char(related='number', copy=False, index=True)

    _sql_constraints = [
        ('eicr_clave_uniq', 'unique (eicr_clave)', "La clave de comprobante debe ser única"),
    ]

    @api.multi
    def action_invoice_sent(self):
        """ Open a window to compose an email, with the edi invoice template
            message loaded by default
        """
        self.ensure_one()
        template = self.env.ref('account.email_template_edi_invoice', False)
        compose_form = self.env.ref('account.account_invoice_send_wizard_form', False)

        # agregamos los adjuntos solo si el comprobante fue aceptado
        if self.eicr_state in ('aceptado'):
            comprobante = self.env['ir.attachment'].search(
                [('res_model', '=', 'account.invoice'), ('res_id', '=', self.id),
                 ('res_field', '=', 'eicr_documento_file')], limit=1)
            comprobante.name = self.eicr_documento_fname
            comprobante.datas_fname = self.eicr_documento_fname

            attachments = comprobante

            if self.eicr_mensaje_hacienda_file:
                respuesta = self.env['ir.attachment'].search(
                    [('res_model', '=', 'account.invoice'), ('res_id', '=', self.id),
                     ('res_field', '=', 'eicr_mensaje_hacienda_file')], limit=1)
                respuesta.name = self.eicr_mensaje_hacienda_fname
                respuesta.datas_fname = self.eicr_mensaje_hacienda_fname

                attachments = attachments | respuesta
            template.attachment_ids = [(6, 0, attachments.mapped('id'))]
        else:
            template.attachment_ids = [(5)]

        email_to = self.partner_id.email_facturas or self.partner_id.email
        _logger.info('emailing to %s' % email_to)

        ctx = dict(
            default_model='account.invoice',
            default_res_id=self.id,
            default_use_template=bool(template),
            default_template_id=template and template.id or False,
            default_composition_mode='comment',
            mark_invoice_as_sent=True,
            custom_layout="mail.mail_notification_paynow",
            force_email=True,
            default_email_to=email_to
        )
        return {
            'name': _('Send Invoice'),
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'account.invoice.send',
            'views': [(compose_form.id, 'form')],
            'view_id': compose_form.id,
            'target': 'new',
            'context': ctx,
        }



    @api.onchange('eicr_documento2_file')
    def _onchange_eicr_documento2_file(self):
        # sin xml limpiamos los campos de la facturacion electronica
        if not self.eicr_documento2_file:
            _logger.info('no xml')
            self.eicr_state = 'na'
            self.eicr_documento2_file = None
            self.eicr_documento2_fname = None
            self.eicr_mensaje_hacienda_file = None
            self.eicr_mensaje_hacienda_fname = None
            self.eicr_date = None
            self.eicr_clave = None
            self.eicr_aceptacion = None
            return
        # si la factura es de proveedor y esta en borrador, cargamos las lineas
        _logger.info('some xml')
        _logger.info('type %s' % self.type)
        _logger.info('state %s' % self.state)
        if self.type in ('in_invoice', 'in_refund') and self.state in ('draft'):
            _logger.info('processing xml')
            self.env['eicr.tools']._process_supplier_invoice(self)

    @api.multi
    def action_enviar_aceptacion(self, vals):
        _logger.info('action_enviar_mensaje self %s' % self)
        _logger.info('action_enviar_mensaje vals %s' % vals)
        self.env['eicr.tools'].enviar_aceptacion(self)

    @api.multi
    @api.returns('self')
    def refund(self, date_invoice=None, date=None, description=None, journal_id=None, invoice_id=None, eicr_reference_code_id=None):
        if self.env['eicr.tools'].eicr_habilitado(self.company_id):
            new_invoices = super(AccountInvoice, self).refund()
            return new_invoices
        else:
            new_invoices = self.browse()
            for invoice in self:
                # create the new invoice
                values = self._prepare_refund(invoice, date_invoice=date_invoice, date=date, description=description, journal_id=journal_id)
                values.update({'invoice_id': invoice_id, 'eicr_reference_code_id': eicr_reference_code_id})
                refund_invoice = self.create(values)
                if invoice.type == 'out_invoice':
                    message = _(
                        "This customer invoice credit note has been created from: <a href=# data-oe-model=account.invoice data-oe-id=%d>%s</a><br>Reason: %s") % (
                              invoice.id, invoice.number, description)
                else:
                    message = _(
                        "This vendor bill credit note has been created from: <a href=# data-oe-model=account.invoice data-oe-id=%d>%s</a><br>Reason: %s") % (
                              invoice.id, invoice.number, description)

                refund_invoice.message_post(body=message)
                new_invoices += refund_invoice
            return new_invoices

    @api.onchange('partner_id', 'company_id')
    def _onchange_partner_id(self):
        super(AccountInvoice, self)._onchange_partner_id()
        self.payment_methods_id = self.env.ref('eicr_base.PaymentMethods_1')

    @api.multi
    def action_consultar_hacienda(self):
        if self.company_id.eicr_environment != 'disabled':
            for invoice in self:
                self.env['eicr.hacienda']._consultar_documento(invoice)

    @api.multi
    def action_invoice_open(self):
        _logger.info('%s of type %s' % (self, self.type))
        fe = self.env.ref('eicr_base.FacturaElectronica_V_4_3')
        te = self.env.ref('eicr_base.TiqueteElectronico_V_4_3')
        for invoice in self:
            if self.env['eicr.tools'].eicr_habilitado(invoice.company_id):
                self.set_document()
            if self.eicr_documento_tipo in (fe, te):
                if not invoice.eicr_payment_method_id: invoice.eicr_payment_method_id = self.env.ref('eicr_base.PaymentMethods_1')
                if invoice.eicr_payment_method_id.code == '02':
                    iva4 = self.env['account.tax'].search([('tax_code', '=', '01'), ('iva_tax_code', '=', '04'), ('type_tax_use', '=', 'sale')])
                    iva4_devolucion = self.env['account.tax'].search([('tax_code', '=', '01'),('iva_tax_code', '=', '04D'),('type_tax_use', '=', 'sale')])
                    for line in invoice.invoice_line_ids:
                        if iva4 in line.invoice_line_tax_ids:
                            line.invoice_line_tax_ids = [(4, iva4_devolucion.id)]
                    invoice.compute_taxes()

        res = super(AccountInvoice, self).action_invoice_open()

        for invoice in self:
            invoice.make_xml()

        return res

    def get_consecutivo(self):
        _logger.info('consecutivando')
        # el consecutivo tiene 20 digitos
        if self.eicr_consecutivo and len(self.eicr_consecutivo) == 20 and self.eicr_consecutivo.isdigit(): return self.eicr_consecutivo
        # la secuencia tiene 10 digitos
        if len(self.eicr_consecutivo) != 10 or not self.eicr_consecutivo.isdigit(): return False
        # - sucursal
        sucursal = re.sub('[^0-9]', '', str(self.journal_id.sequence_id.sucursal or '506')).zfill(3)
        # - terminal
        terminal = re.sub('[^0-9]', '', str(self.journal_id.sequence_id.terminal or '506')).zfill(5)
        # - tipo 01 FacturaElectronica, 03 NotaCreditoElectronica 04 TiqueteElectronio
        if   self.eicr_documento_tipo == self.env.ref('eicr_base.FacturaElectronica_V_4_3'): tipo = '01'
        elif self.eicr_documento_tipo == self.env.ref('eicr_base.NotaCreditoElectronica_V_4_3'): tipo = '03'
        elif self.eicr_documento_tipo == self.env.ref('eicr_base.TiqueteElectronico_V_4_3'): tipo = '04'
        elif self.eicr_documento_tipo == self.env.ref('eicr_base.MensajeReceptor_V_4_3'):
            if self.eicr_aceptacion == '2': tipo = '06' # Aceptado Parcialmente
            elif self.eicr_aceptacion == '3': tipo = '07' # Rechazado
            else: tipo = '05' # Aceptado
        elif self.eicr_documento_tipo == self.env.ref('eicr_base.FacturaElectronicaExportacion_V_4_3'):
            tipo = '09'
        # - numeracion
        numeracion = self.eicr_consecutivo
        # consecutivo
        self.eicr_consecutivo  = sucursal + terminal + tipo + numeracion
        _logger.info('consecutivo %s' % self.eicr_consecutivo)
        return self.eicr_consecutivo

    def get_clave(self):
        if self.eicr_documento_tipo == self.env.ref('eicr_base.MensajeReceptor_V_4_3'):
            return self._get_clave_mr()

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
        # si no tiene el tipo definido aún
        if not self.eicr_documento_tipo and not self.journal_id.sequence_id.eicr_no:
            # revisamos que eicr este habilitado
            if self.env['eicr.tools'].eicr_habilitado(self.company_id):
                # Si la secuencia tiene especificado algún tipo de documento, los usamos
                if self.journal_id.sequence_id.eicr_documento_tipo:
                    self.eicr_documento_tipo = self.journal_id.sequence_id.eicr_documento_tipo
                # sino, le asignamos uno
                elif self.type == 'out_invoice':
                    if self.env['eicr.tools'].validar_receptor(self.partner_id):
                        self.eicr_documento_tipo = self.env.ref('eicr_base.FacturaElectronica_V_4_3')
                    else:
                        self.eicr_documento_tipo = self.env.ref('eicr_base.TiqueteElectronico_V_4_3')
                elif self.type == 'out_refund':
                    self.eicr_documento_tipo = self.env.ref('eicr_base.NotaCreditoElectronica_V_4_3')
                elif self.type == 'in_invoice':
                    self.eicr_documento_tipo = self.env.ref('eicr_base.MensajeReceptor_V_4_3')

        _logger.info('tipo %s' % self.eicr_documento_tipo)
        return self.eicr_documento_tipo

    @api.model
    def _get_xml_fe_te_nc(self):
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
        FechaEmision = etree.Element('FechaEmision')
        now_utc = datetime.now(pytz.timezone('UTC'))
        now_cr = now_utc.astimezone(pytz.timezone('America/Costa_Rica'))
        FechaEmision.text = now_cr.strftime("%Y-%m-%dT%H:%M:%S")
        Documento.append(FechaEmision)

        # Emisor
        Emisor = self.env['eicr.tools'].get_nodo_emisor(self.company_id)
        Documento.append(Emisor)

        # Receptor
        Receptor = self.env['eicr.tools'].get_nodo_receptor(self.partner_id)
        if Receptor: Documento.append(Receptor)

        # Condicion Venta
        CondicionVenta = etree.Element('CondicionVenta')
        if self.payment_term_id:
            CondicionVenta.text = '02'
            Documento.append(CondicionVenta)

            PlazoCredito = etree.Element('PlazoCredito')
            timedelta(7)
            fecha_de_factura = self.date_invoice
            fecha_de_vencimiento = self.date_due
            PlazoCredito.text = str((fecha_de_factura - fecha_de_vencimiento).days)
            Documento.append(PlazoCredito)
        else:
            CondicionVenta.text = '01'
            Documento.append(CondicionVenta)

        # MedioPago
        MedioPago = etree.Element('MedioPago')
        MedioPago.text = self.eicr_payment_method_id.code if self.eicr_payment_method_id else '01'
        Documento.append(MedioPago)

        # DetalleServicio
        DetalleServicio = etree.Element('DetalleServicio')

        decimales = 2

        totalServiciosGravados = round(0.00, decimales)
        totalServiciosExentos = round(0.00, decimales)
        totalMercanciasGravadas = round(0.00, decimales)
        totalMercanciasExentas = round(0.00, decimales)

        totalDescuentosMercanciasExentas = round(0.00, decimales)
        totalDescuentosMercanciasGravadas = round(0.00, decimales)
        totalDescuentosServiciosExentos = round(0.00, decimales)
        totalDescuentosServiciosGravados = round(0.00, decimales)

        totalImpuesto = round(0.00, decimales)
        totalIVADevuelto = round(0.00, decimales)

        for indice, linea in enumerate(self.invoice_line_ids.sorted(lambda l: l.sequence)):
            LineaDetalle = etree.Element('LineaDetalle')

            NumeroLinea = etree.Element('NumeroLinea')
            NumeroLinea.text = '%s' % (indice + 1)
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
            Cantidad.text = str(linea.quantity)
            LineaDetalle.append(Cantidad)

            UnidadMedida = etree.Element('UnidadMedida')
            UnidadMedida.text = 'Sp' if (linea.product_id and linea.product_id.type == 'service') else 'Unid'

            LineaDetalle.append(UnidadMedida)

            Detalle = etree.Element('Detalle')
            Detalle.text = linea.name
            LineaDetalle.append(Detalle)

            PrecioUnitario = etree.Element('PrecioUnitario')
            PrecioUnitario.text = str(round(linea.price_unit, decimales))
            LineaDetalle.append(PrecioUnitario)

            MontoTotal = etree.Element('MontoTotal')
            montoTotal = round(linea.price_unit, decimales) * round(linea.quantity, decimales)
            MontoTotal.text = str(round(montoTotal, decimales))

            LineaDetalle.append(MontoTotal)

            if linea.discount:
                Descuento = etree.Element('Descuento')

                MontoDescuento = etree.Element('MontoDescuento')
                montoDescuento = round(round(montoTotal, decimales) - round(linea.price_subtotal, decimales), decimales)
                if linea.invoice_line_tax_ids:
                    if linea.product_id and linea.product_id.type == 'service':
                        totalDescuentosServiciosGravados += montoDescuento
                    else:
                        totalDescuentosMercanciasGravadas += montoDescuento
                else:
                    if linea.product_id and linea.product_id.type == 'service':
                        totalDescuentosServiciosExentos += montoDescuento
                    else:
                        totalDescuentosMercanciasExentas += montoDescuento

                MontoDescuento.text = str(montoDescuento)
                Descuento.append(MontoDescuento)

                NaturalezaDescuento = etree.Element('NaturalezaDescuento')
                NaturalezaDescuento.text = 'Descuento Comercial'
                Descuento.append(NaturalezaDescuento)

                LineaDetalle.append(Descuento)

            SubTotal = etree.Element('SubTotal')
            SubTotal.text = str(round(linea.price_subtotal, decimales))
            LineaDetalle.append(SubTotal)

            ivaDevuelto = round(0.00, decimales)
            if linea.invoice_line_tax_ids:

                for impuesto in linea.invoice_line_tax_ids:

                    monto = round(linea.price_subtotal * impuesto.amount / 100.00, decimales)

                    if (impuesto.tax_code == '01' and impuesto.iva_tax_code == '04D'):
                        if self.eicr_payment_method_id.code == '02':
                            ivaDevuelto += abs(monto)
                    else:
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
            MontoTotalLinea.text = str(round(linea.price_total + ivaDevuelto, decimales))
            LineaDetalle.append(MontoTotalLinea)

            DetalleServicio.append(LineaDetalle)

            totalIVADevuelto += ivaDevuelto

        Documento.append(DetalleServicio)

        # ResumenFactura
        ResumenFactura = etree.Element('ResumenFactura')

        if self.currency_id.name != 'CRC':
            CodigoTipoMoneda = etree.Element('CodigoTipoMoneda')

            CodigoMoneda = etree.Element('CodigoMoneda')
            CodigoMoneda.text = self.currency_id.name
            CodigoTipoMoneda.append(CodigoMoneda)

            TipoCambio = etree.Element('TipoCambio')
            TipoCambio.text = str(round(1.0 / self.currency_id.rate, decimales))
            CodigoTipoMoneda.append(TipoCambio)

            ResumenFactura.append(CodigoTipoMoneda)

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
        TotalVenta.text = str(round(
            self.amount_untaxed + totalDescuentosServiciosGravados + totalDescuentosMercanciasGravadas + totalDescuentosServiciosExentos + totalDescuentosMercanciasExentas,
            decimales))
        ResumenFactura.append(TotalVenta)

        if totalDescuentosServiciosGravados + totalDescuentosMercanciasGravadas + totalDescuentosServiciosExentos + totalDescuentosMercanciasExentas:
            TotalDescuentos = etree.Element('TotalDescuentos')
            TotalDescuentos.text = str(round(
                totalDescuentosServiciosGravados + totalDescuentosMercanciasGravadas + totalDescuentosServiciosExentos + totalDescuentosMercanciasExentas,
                decimales))
            ResumenFactura.append(TotalDescuentos)

        TotalVentaNeta = etree.Element('TotalVentaNeta')
        TotalVentaNeta.text = str(round(self.amount_untaxed, decimales))
        ResumenFactura.append(TotalVentaNeta)

        if totalImpuesto:
            TotalImpuesto = etree.Element('TotalImpuesto')
            # TotalImpuesto.text = str(round(self.amount_tax, decimales))
            TotalImpuesto.text = str(round(totalImpuesto, decimales))
            ResumenFactura.append(TotalImpuesto)

            if totalIVADevuelto:
                TotalIVADevuelto = etree.Element('TotalIVADevuelto')
                TotalIVADevuelto.text = str(round(totalIVADevuelto, decimales))
                ResumenFactura.append(TotalIVADevuelto)

        TotalComprobante = etree.Element('TotalComprobante')
        TotalComprobante.text = str(round(self.amount_total, decimales))
        ResumenFactura.append(TotalComprobante)

        Documento.append(ResumenFactura)

        if self.type == 'out_refund':

            if self.refund_invoice_id.type == 'out_invoice':
                tipo = '01'
            elif self.refund_invoice_id.type == 'out_refund':
                tipo = '03'

            InformacionReferencia = etree.Element('InformacionReferencia')

            TipoDoc = etree.Element('TipoDoc')
            TipoDoc.text = tipo
            InformacionReferencia.append(TipoDoc)

            Numero = etree.Element('Numero')
            Numero.text = self.refund_invoice_id.eicr_clave or self.refund_invoice_id.eicr_consecutivo
            InformacionReferencia.append(Numero)

            FechaEmision = etree.Element('FechaEmision')
            if not self.refund_invoice_id.eicr_date:
                self.refund_invoice_id.eicr_date = self.datetime_obj()

            FechaEmision.text = self.env['eicr.tools'].datetime_str(self.refund_invoice_id.eicr_date)
            InformacionReferencia.append(FechaEmision)

            Codigo = etree.Element('Codigo')
            Codigo.text = self.eicr_reference_code_id.code
            InformacionReferencia.append(Codigo)

            Razon = etree.Element('Razon')
            Razon.text = self.name or 'Error en Factura'
            InformacionReferencia.append(Razon)

            Documento.append(InformacionReferencia)

        return Documento

    @api.model
    def _get_xml_mr(self):
        Documento = self.eicr_documento_tipo.get_root_node()

        xml = base64.b64decode(self.eicr_documento2_file)
        factura = etree.tostring(etree.fromstring(xml)).decode()

        factura = etree.fromstring(re.sub(' xmlns="[^"]+"', '', factura, count=1))

        Emisor = factura.find('Emisor')
        Receptor = factura.find('Receptor')
        TotalImpuesto = factura.find('ResumenFactura').find('TotalImpuesto')
        TotalComprobante = factura.find('ResumenFactura').find('TotalComprobante')

        emisor = self.company_id

        # Clave
        Clave = etree.Element('Clave')
        Clave.text = factura.find('Clave').text
        if not self.eicr_clave: self.eicr_clave = Clave.text
        Documento.append(Clave)

        # NumeroCedulaEmisor
        NumeroCedulaEmisor = etree.Element('NumeroCedulaEmisor')
        NumeroCedulaEmisor.text = factura.find('Emisor').find('Identificacion').find('Numero').text
        Documento.append(NumeroCedulaEmisor)

        if not self.eicr_date:
            self.eicr_date = self.datetime_obj()

        # FechaEmisionDoc
        FechaEmisionDoc = etree.Element('FechaEmisionDoc')
        FechaEmisionDoc.text = self.env['eicr.tools'].datetime_str(self.eicr_date)  # date_cr
        Documento.append(FechaEmisionDoc)

        # Mensaje
        Mensaje = etree.Element('Mensaje')
        Mensaje.text = self.eicr_aceptacion or '01'  # eicr_aceptacion
        Documento.append(Mensaje)

        # DetalleMensaje
        DetalleMensaje = etree.Element('DetalleMensaje')
        DetalleMensaje.text = 'Mensaje de ' + emisor.name  # emisor.name
        Documento.append(DetalleMensaje)

        if TotalImpuesto is not None:
            # MontoTotalImpuesto
            MontoTotalImpuesto = etree.Element('MontoTotalImpuesto')
            MontoTotalImpuesto.text = TotalImpuesto.text  # TotalImpuesto.text
            Documento.append(MontoTotalImpuesto)

            if Mensaje.text != '3':
                # CodigoActividad
                CodigoActividad = etree.Element('CodigoActividad')
                CodigoActividad.text = self.company_id.eicr_activity_ids[0].code
                Documento.append(CodigoActividad)

                # CondicionImpuesto
                # Si no se selecciona la condición de crédito del iva, se asume Gasto corriente no genera crédito
                if not self.eicr_credito_iva_condicion: self.eicr_credito_iva_condicion = self.env.ref('eicr_base.IVACreditCondition_04')
                CondicionImpuesto = etree.Element('CondicionImpuesto')
                CondicionImpuesto.text = self.eicr_credito_iva_condicion.code
                Documento.append(CondicionImpuesto)

                # MontoTotalImpuestoAcreditar
                condiciones_acreditables = (
                self.env.ref('eicr_base.IVACreditCondition_01'), self.env.ref('eicr_base.IVACreditCondition_02'))
                if self.eicr_credito_iva_condicion in condiciones_acreditables:

                    if not self.eicr_credito_iva:
                        self.eicr_credito_iva = self.company_id.eicr_factor_iva or 100.0
                    MontoTotalImpuestoAcreditar = etree.Element('MontoTotalImpuestoAcreditar')
                    montoTotalImpuestoAcreditar = float(TotalImpuesto.text) * self.eicr_credito_iva / 100.0
                    MontoTotalImpuestoAcreditar.text = str(round(montoTotalImpuestoAcreditar, 2))
                    Documento.append(MontoTotalImpuestoAcreditar)

        # TotalFactura
        TotalFactura = etree.Element('TotalFactura')
        TotalFactura.text = TotalComprobante.text  # TotalComprobante.text
        Documento.append(TotalFactura)

        identificacion = re.sub('[^0-9]', '', emisor.vat or '')

        if not emisor.eicr_id_type:
            raise UserError('Seleccione el tipo de identificación del emisor en el perfil de la compañía')
        elif emisor.eicr_id_type.code == '01' and len(identificacion) != 9:
            raise UserError('La Cédula Física del emisor debe de tener 9 dígitos')
        elif emisor.eicr_id_type.code == '02' and len(identificacion) != 10:
            raise UserError('La Cédula Jurídica del emisor debe de tener 10 dígitos')
        elif emisor.eicr_id_type.code == '03' and (len(identificacion) != 11 or len(identificacion) != 12):
            raise UserError('La identificación DIMEX del emisor debe de tener 11 o 12 dígitos')
        elif emisor.eicr_id_type.code == '04' and len(identificacion) != 10:
            raise UserError('La identificación NITE del emisor debe de tener 10 dígitos')

        # NumeroCedulaReceptor
        NumeroCedulaReceptor = etree.Element('NumeroCedulaReceptor')
        NumeroCedulaReceptor.text = identificacion
        Documento.append(NumeroCedulaReceptor)

        # NumeroConsecutivoReceptor
        NumeroConsecutivoReceptor = etree.Element('NumeroConsecutivoReceptor')
        NumeroConsecutivoReceptor.text = self.eicr_consecutivo
        Documento.append(NumeroConsecutivoReceptor)

        return Documento

    @api.model
    def make_xml(self):
        # si ya existe, no se rehace
        if self.eicr_documento_file: return
        if self.eicr_date in (False, None): self.eicr_date = self.env['eicr.tools'].datetime_obj()
        self.set_document()
        if not self.eicr_documento_tipo:
            self.eicr_state = 'na'
            return
        consecutivo = self.get_consecutivo()
        clave = self.get_clave()
        if self.eicr_documento_tipo in ( self.env.ref('eicr_base.FacturaElectronica_V_4_3'),
                                         self.env.ref('eicr_base.TiqueteElectronico_V_4_3'),
                                         self.env.ref('eicr_base.NotaCreditoElectronica_V_4_3'),
                                         self.env.ref('eicr_base.FacturaElectronicaExportacion_V_4_3')):

            Documento = self._get_xml_fe_te_nc()
        elif self.eicr_documento_tipo == self.env.ref('eicr_base.MensajeReceptor_V_4_3') and \
                self.env['eicr.tools'].validar_xml_proveedor(self):
            Documento = self._get_xml_mr()
        else:
            self.eicr_state = 'na'
            return

        xml = etree.tostring(Documento, encoding='UTF-8', xml_declaration=True, pretty_print=True)
        xml_base64_encoded = base64.b64encode(xml).decode('utf-8')
        xml_base64_encoded_firmado = self.env['eicr.tools'].firmar_xml(xml_base64_encoded, self.company_id)

        self.eicr_documento_file = xml_base64_encoded_firmado
        self.eicr_documento_fname = self.eicr_documento_tipo.tag + self.eicr_clave + '.xml'
        self.eicr_state = 'pendiente'
