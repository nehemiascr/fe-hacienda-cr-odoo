import json
import requests
import re
import random
import logging
from odoo.exceptions import UserError

import base64
from lxml import etree
import datetime
import pytz


_logger = logging.getLogger(__name__)


def get_clave(self, url, tipo_documento, numeracion, sucursal, terminal, situacion='normal'):

    # tipo de documento
    tipos_de_documento = { 'FE'  : '01', # Factura Electrónica
                           'ND'  : '02', # Nota de Débito
                           'NC'  : '03', # Nota de Crédito
                           'TE'  : '04', # Tiquete Electrónico
                           'CCE' : '05', # Confirmación Comprobante Electrónico
                           'CPCE': '06', # Confirmación Parcial Comprobante Electrónico
                           'RCE' : '07'} # Rechazo Comprobante Electrónico

    if tipo_documento not in tipos_de_documento:
        raise UserError('No se encuentra tipo de documento')

    tipo_documento = tipos_de_documento[tipo_documento]

    # numeracion
    numeracion = re.sub('[^0-9]', '', numeracion)

    if len(numeracion) != 10:
        raise UserError('La numeración debe de tener 10 dígitos')

    # sucursal
    sucursal = re.sub('[^0-9]', '', str(sucursal)).zfill(3)

    # terminal
    terminal = re.sub('[^0-9]', '', str(terminal)).zfill(5)

    # tipo de identificación
    if not self.company_id.identification_id:
        raise UserError('Seleccione el tipo de identificación del emisor en el perfil de la compañía')

    # identificación
    identificacion = re.sub('[^0-9]', '', self.company_id.vat)

    if self.company_id.identification_id.code == '01' and len(identificacion) != 9:
        raise UserError('La Cédula Física del emisor debe de tener 9 dígitos')
    elif self.company_id.identification_id.code == '02' and len(identificacion) != 10:
        raise UserError('La Cédula Jurídica del emisor debe de tener 10 dígitos')
    elif self.company_id.identification_id.code == '03' and (len(identificacion) != 11 or len(identificacion) != 12):
        raise UserError('La identificación DIMEX del emisor debe de tener 11 o 12 dígitos')
    elif self.company_id.identification_id.code == '04' and len(identificacion) != 10:
        raise UserError('La identificación NITE del emisor debe de tener 10 dígitos')

    identificacion = identificacion.zfill(12)

    # situación
    situaciones = { 'normal': '1', 'contingencia': '2', 'sininternet': '3'}

    if situacion not in situaciones:
        raise UserError('No se encuentra tipo de situación')

    situacion = situaciones[situacion]

    # código de pais
    codigo_de_pais = '506'

    # fecha
    now_utc = datetime.datetime.now(pytz.timezone('UTC'))
    now_cr = now_utc.astimezone(pytz.timezone('America/Costa_Rica'))

    dia = now_cr.strftime('%d')
    mes = now_cr.strftime('%m')
    anio = now_cr.strftime('%y')

    # código de seguridad
    codigo_de_seguridad = str(random.randint(1, 99999999)).zfill(8)

    # consecutivo
    consecutivo = sucursal + terminal + tipo_documento + numeracion

    # clave
    clave = codigo_de_pais + dia + mes + anio + identificacion + consecutivo + situacion + codigo_de_seguridad

    return {'resp': {'length': len(clave), 'clave': clave, 'consecutivo': consecutivo}}


def _get_consecutivo(invoice):
    # A) sucursal
    sucursal = str(invoice.journal_id.sucursal or 1).zfill(3)

    # B) terminal
    terminal = str(invoice.journal_id.terminal or 1).zfill(5)

    # C) tipo de comprobante o documento
    if invoice.type == 'out_invoice':
        tipo_documento = '01'  # Factura Electrónica
    elif invoice.type == 'out_refund':
        tipo_documento = '03'  # Nota de Crédito

    # D) numeracion
    numeracion = re.sub('[^0-9]', '', invoice.number)
    if len(numeracion) != 10:
        raise UserError('La numeración debe de tener 10 dígitos')

    consecutivo = sucursal + terminal + tipo_documento + numeracion

    if len(consecutivo) != 20:
        raise UserError('Algo anda mal con el consecutivo :(')

    return consecutivo


def _get_clave(invoice):
    # a) código de pais
    codigo_de_pais = '506'

    # b) día, c) mes y d) año
    fecha = datetime.datetime.strptime(invoice.date_invoice, '%Y-%m-%d')
    dia = fecha.strftime('%d')
    mes = fecha.strftime('%m')
    anio = fecha.strftime('%y')

    # e) número de identificación
    identificacion = re.sub('[^0-9]', '', invoice.company_id.vat)

    if not invoice.company_id.identification_id:
        raise UserError('Seleccione el tipo de identificación del emisor en el perfil de la compañía')
    elif invoice.company_id.identification_id.code == '01' and len(identificacion) != 9:
        raise UserError('La Cédula Física del emisor debe de tener 9 dígitos')
    elif invoice.company_id.identification_id.code == '02' and len(identificacion) != 10:
        raise UserError('La Cédula Jurídica del emisor debe de tener 10 dígitos')
    elif invoice.company_id.identification_id.code == '03' and (len(identificacion) != 11 or len(identificacion) != 12):
        raise UserError('La identificación DIMEX del emisor debe de tener 11 o 12 dígitos')
    elif invoice.company_id.identification_id.code == '04' and len(identificacion) != 10:
        raise UserError('La identificación NITE del emisor debe de tener 10 dígitos')

    identificacion = identificacion.zfill(12)

    # f) numeración consecutiva
    consecutivo = invoice.number
    # consecutivo = _get_consecutivo(invoice)

    # g) situacion del comprobante electrónico
    situacion = '1'

    # h) código de seguridad
    codigo_de_seguridad = str(random.randint(1, 99999999)).zfill(8)

    clave = codigo_de_pais + dia + mes + anio + identificacion + consecutivo + situacion + codigo_de_seguridad

    if len(clave) != 50:
        raise UserError('Algo anda mal con la clave :(')

    return clave


def _make_xml_invoice(invoice):
    emisor = invoice.company_id
    receptor = invoice.partner_id

    # FacturaElectronica 4.2
    FacturaElectronica = etree.Element('FacturaElectronica')

    # Clave
    Clave = etree.Element('Clave')
    Clave.text = _get_clave(invoice)
    FacturaElectronica.append(Clave)

    # NumeroConsecutivo
    NumeroConsecutivo = etree.Element('NumeroConsecutivo')
    NumeroConsecutivo.text = invoice.number
    FacturaElectronica.append(NumeroConsecutivo)

    # FechaEmision
    now_utc = datetime.datetime.now(pytz.timezone('UTC'))
    now_cr = now_utc.astimezone(pytz.timezone('America/Costa_Rica'))
    FechaEmision = etree.Element('FechaEmision')
    FechaEmision.text = now_cr.strftime("%Y-%m-%dT%H:%M:%S")
    FacturaElectronica.append(FechaEmision)

    # Emisor
    Emisor = etree.Element('Emisor')

    Nombre = etree.Element('Nombre')
    Nombre.text = emisor.name
    Emisor.append(Nombre)

    identificacion = re.sub('[^0-9]', '', emisor.vat)

    if not emisor.identification_id:
        raise UserError('Seleccione el tipo de identificación del emisor en el perfil de la compañía')
    elif emisor.identification_id.code == '01' and len(identificacion) != 9:
        raise UserError('La Cédula Física del emisor debe de tener 9 dígitos')
    elif emisor.identification_id.code == '02' and len(identificacion) != 10:
        raise UserError('La Cédula Jurídica del emisor debe de tener 10 dígitos')
    elif emisor.identification_id.code == '03' and (len(identificacion) != 11 or len(identificacion) != 12):
        raise UserError('La identificación DIMEX del emisor debe de tener 11 o 12 dígitos')
    elif emisor.identification_id.code == '04' and len(identificacion) != 10:
        raise UserError('La identificación NITE del emisor debe de tener 10 dígitos')

    Identificacion = etree.Element('Identificacion')

    Tipo = etree.Element('Tipo')
    Tipo.text = emisor.identification_id.code
    Identificacion.append(Tipo)

    Numero = etree.Element('Numero')
    Numero.text = identificacion
    Identificacion.append(Numero)

    Emisor.append(Identificacion)

    if emisor.commercial_name:
        NombreComercial = etree.Element('NombreComercial')
        NombreComercial.text = emisor.commercial_name
        Emisor.append(NombreComercial)

    if not emisor.state_id:
        raise UserError('La dirección del emisor está incompleta, no se ha seleccionado la Provincia')
    if not emisor.county_id:
        raise UserError('La dirección del emisor está incompleta, no se ha seleccionado el Cantón')
    if not emisor.district_id:
        raise UserError('La dirección del emisor está incompleta, no se ha seleccionado el Distrito')

    Ubicacion = etree.Element('Ubicacion')

    Provincia = etree.Element('Provincia')
    Provincia.text = emisor.partner_id.state_id.code
    Ubicacion.append(Provincia)

    Canton = etree.Element('Canton')
    Canton.text = emisor.county_id.code
    Ubicacion.append(Canton)

    Distrito = etree.Element('Distrito')
    Distrito.text = emisor.district_id.code
    Ubicacion.append(Distrito)

    if emisor.partner_id.neighborhood_id:
        Barrio = etree.Element('Barrio')
        Barrio.text = emisor.neighborhood_id.code
        Ubicacion.append(Barrio)

    OtrasSenas = etree.Element('OtrasSenas')
    OtrasSenas.text = emisor.street
    Ubicacion.append(OtrasSenas)

    Emisor.append(Ubicacion)

    telefono = emisor.phone or emisor.mobile
    if telefono and len(re.sub('[^0-9]', '', telefono)) <= 20:
        Telefono = etree.Element('Telefono')

        CodigoPais = etree.Element('CodigoPais')
        CodigoPais.text = '506'
        Telefono.append(CodigoPais)

        NumTelefono = etree.Element('NumTelefono')
        NumTelefono.text = re.sub('[^0-9]', '', telefono)[:8]

        Telefono.append(NumTelefono)

        Emisor.append(Telefono)

    if not emisor.email or not re.match('^[(a-z0-9\_\-\.)]+@[(a-z0-9\_\-\.)]+\.[(a-z)]{2,15}$', emisor.email.lower()):
        raise UserError('El correo electrónico del emisor es inválido.')

    CorreoElectronico = etree.Element('CorreoElectronico')
    CorreoElectronico.text = emisor.email.lower()
    Emisor.append(CorreoElectronico)

    FacturaElectronica.append(Emisor)

    # Receptor
    if receptor:

        Receptor = etree.Element('Receptor')

        Nombre = etree.Element('Nombre')
        Nombre.text = receptor.name
        Receptor.append(Nombre)

        if receptor.identification_id and receptor.vat:
            identificacion = re.sub('[^0-9]', '', receptor.vat)

            if receptor.identification_id.code == '01' and len(identificacion) != 9:
                raise UserError('La Cédula Física del cliente debe de tener 9 dígitos')
            elif receptor.identification_id.code == '02' and len(identificacion) != 10:
                raise UserError('La Cédula Jurídica del cliente debe de tener 10 dígitos')
            elif receptor.identification_id.code == '03' and (len(identificacion) != 11 or len(identificacion) != 12):
                raise UserError('La identificación DIMEX del cliente debe de tener 11 o 12 dígitos')
            elif receptor.identification_id.code == '04' and len(identificacion) != 10:
                raise UserError('La identificación NITE del cliente debe de tener 10 dígitos')

            Identificacion = etree.Element('Identificacion')

            Tipo = etree.Element('Tipo')
            Tipo.text = receptor.identification_id.code
            Identificacion.append(Tipo)

            Numero = etree.Element('Numero')
            Numero.text = identificacion
            Identificacion.append(Numero)

            Receptor.append(Identificacion)

        if receptor.state_id and receptor.county_id and receptor.district_id and receptor.street:
            Ubicacion = etree.Element('Ubicacion')

            Provincia = etree.Element('Provincia')
            Provincia.text = receptor.state_id.code
            Ubicacion.append(Provincia)

            Canton = etree.Element('Canton')
            Canton.text = receptor.county_id.code
            Ubicacion.append(Canton)

            Distrito = etree.Element('Distrito')
            Distrito.text = receptor.district_id.code
            Ubicacion.append(Distrito)

            if receptor.partner_id.neighborhood_id:
                Barrio = etree.Element('Barrio')
                Barrio.text = receptor.neighborhood_id.code
                Ubicacion.append(Barrio)

            OtrasSenas = etree.Element('OtrasSenas')
            OtrasSenas.text = receptor.street
            Ubicacion.append(OtrasSenas)

            Receptor.append(Ubicacion)

        telefono = receptor.phone or receptor.mobile
        if telefono and len(re.sub('[^0-9]', '', telefono)) <= 20:
            Telefono = etree.Element('Telefono')

            CodigoPais = etree.Element('CodigoPais')
            CodigoPais.text = '506'
            Telefono.append(CodigoPais)

            NumTelefono = etree.Element('NumTelefono')
            NumTelefono.text = re.sub('[^0-9]', '', telefono)[:8]
            Telefono.append(NumTelefono)

            Receptor.append(Telefono)

        if receptor.email:
            CorreoElectronico = etree.Element('CorreoElectronico')
            CorreoElectronico.text = receptor.email
            Receptor.append(CorreoElectronico)

        FacturaElectronica.append(Receptor)

    # Condicion Venta
    CondicionVenta = etree.Element('CondicionVenta')
    if invoice.payment_term_id:
        CondicionVenta.text = '02'
        FacturaElectronica.append(CondicionVenta)

        PlazoCredito = etree.Element('PlazoCredito')
        datetime.timedelta(7)
        fecha_de_factura = datetime.datetime.strptime(invoice.date_invoice, '%Y-%m-%d')
        fecha_de_vencimiento = datetime.datetime.strptime(invoice.date_due, '%Y-%m-%d')
        PlazoCredito.text = str((fecha_de_factura - fecha_de_vencimiento).days)
        FacturaElectronica.append(PlazoCredito)
    else:
        CondicionVenta.text = '01'
        FacturaElectronica.append(CondicionVenta)

    # MedioPago
    MedioPago = etree.Element('MedioPago')
    MedioPago.text = '01'
    FacturaElectronica.append(MedioPago)

    # DetalleServicio
    DetalleServicio = etree.Element('DetalleServicio')

    totalServiciosGravados = 0
    totalServiciosExentos = 0
    totalMercanciasGravadas = 0
    totalMercanciasExentas = 0

    for indice, linea in enumerate(invoice.invoice_line_ids):
        LineaDetalle = etree.Element('LineaDetalle')

        NumeroLinea = etree.Element('NumeroLinea')
        NumeroLinea.text = '%s' % (indice + 1)
        LineaDetalle.append(NumeroLinea)

        if linea.product_id.default_code:
            Codigo = etree.Element('Codigo')

            Tipo = etree.Element('Tipo')
            if linea.product_id.type == 'product' or linea.product_id.type == 'consu':
                Tipo.text = '01'
            elif linea.product_id.type == 'service':
                Tipo.text = '02'
            Codigo.append(Tipo)

            Codigo2 = etree.Element('Codigo')
            Codigo2.text = linea.product_id.default_code
            Codigo.append(Codigo2)

            LineaDetalle.append(Codigo)

        Cantidad = etree.Element('Cantidad')
        Cantidad.text = str(linea.quantity)
        LineaDetalle.append(Cantidad)

        UnidadMedida = etree.Element('UnidadMedida')
        if linea.product_id.type == 'product' or linea.product_id.type == 'consu':
            UnidadMedida.text = 'Unid'
        elif linea.product_id.type == 'service':
            UnidadMedida.text = 'Sp'
        LineaDetalle.append(UnidadMedida)

        Detalle = etree.Element('Detalle')
        Detalle.text = linea.name
        LineaDetalle.append(Detalle)

        PrecioUnitario = etree.Element('PrecioUnitario')
        PrecioUnitario.text = str(linea.price_unit)
        LineaDetalle.append(PrecioUnitario)

        MontoTotal = etree.Element('MontoTotal')
        # MontoTotal.text = str(linea.price_total)
        montoTotal = linea.price_unit * linea.quantity
        MontoTotal.text = str(montoTotal)

        LineaDetalle.append(MontoTotal)

        if linea.discount:
            MontoDescuento = etree.Element('MontoDescuento')
            MontoDescuento.text = str(montoTotal * linea.discount / 100)
            LineaDetalle.append(MontoDescuento)

            NaturalezaDescuento = etree.Element('NaturalezaDescuento')
            NaturalezaDescuento.text = linea.discount_note
            LineaDetalle.append(NaturalezaDescuento)

        SubTotal = etree.Element('SubTotal')
        SubTotal.text = str(linea.price_subtotal)
        LineaDetalle.append(SubTotal)

        if linea.invoice_line_tax_ids:
            for impuesto in linea.invoice_line_tax_ids:

                Impuesto = etree.Element('Impuesto')

                Codigo = etree.Element('Codigo')
                Codigo.text = impuesto.code
                Impuesto.append(Codigo)

                if linea.product_id.type == 'service' and impuesto.code != '07':
                    raise UserError('No se puede aplicar impuesto de ventas a los servicios')

                Tarifa = etree.Element('Tarifa')
                Tarifa.text = str(impuesto.amount)
                Impuesto.append(Tarifa)

                Monto = etree.Element('Monto')
                Monto.text = str(linea.price_subtotal * impuesto.amount / 100)
                Impuesto.append(Monto)

                LineaDetalle.append(Impuesto)

                if linea.product_id.type == 'product' or linea.product_id.type == 'consu':
                    totalMercanciasGravadas += linea.price_subtotal
                elif linea.product_id.type == 'service':
                    totalServiciosGravados += linea.price_subtotal
        else:
            if linea.product_id.type == 'product' or linea.product_id.type == 'consu':
                totalMercanciasExentas += linea.price_subtotal
            elif linea.product_id.type == 'service':
                totalServiciosExentos += linea.price_subtotal

        MontoTotalLinea = etree.Element('MontoTotalLinea')
        MontoTotalLinea.text = str(linea.price_total)
        # MontoTotalLinea.text = str(linea.price_unit * linea.quantity)
        LineaDetalle.append(MontoTotalLinea)

        DetalleServicio.append(LineaDetalle)

    FacturaElectronica.append(DetalleServicio)

    # ResumenFactura
    ResumenFactura = etree.Element('ResumenFactura')

    if totalServiciosGravados:
        TotalServGravados = etree.Element('TotalServGravados')
        TotalServGravados.text = str(totalServiciosGravados)
        ResumenFactura.append(TotalServGravados)

    if totalServiciosExentos:
        TotalServExentos = etree.Element('TotalServExentos')
        TotalServExentos.text = str(totalServiciosExentos)
        ResumenFactura.append(TotalServExentos)

    if totalMercanciasGravadas:
        TotalMercanciasGravadas = etree.Element('TotalMercanciasGravadas')
        TotalMercanciasGravadas.text = str(totalMercanciasGravadas)
        ResumenFactura.append(TotalMercanciasGravadas)

    if totalMercanciasExentas:
        TotalMercanciasExentas = etree.Element('TotalMercanciasExentas')
        TotalMercanciasExentas.text = str(totalMercanciasExentas)
        ResumenFactura.append(TotalMercanciasExentas)

    if totalServiciosGravados + totalMercanciasGravadas:
        TotalGravado = etree.Element('TotalGravado')
        TotalGravado.text = str(totalServiciosGravados + totalMercanciasGravadas)
        ResumenFactura.append(TotalGravado)

    if totalServiciosExentos + totalMercanciasExentas:
        TotalExento = etree.Element('TotalExento')
        TotalExento.text = str(totalServiciosExentos + totalMercanciasExentas)
        ResumenFactura.append(TotalExento)

    TotalVenta = etree.Element('TotalVenta')
    TotalVenta.text = str(invoice.amount_untaxed)
    ResumenFactura.append(TotalVenta)

    TotalVentaNeta = etree.Element('TotalVentaNeta')
    TotalVentaNeta.text = str(invoice.amount_untaxed)
    ResumenFactura.append(TotalVentaNeta)

    if invoice.amount_tax:
        TotalImpuesto = etree.Element('TotalImpuesto')
        TotalImpuesto.text = str(invoice.amount_tax)
        ResumenFactura.append(TotalImpuesto)

    TotalComprobante = etree.Element('TotalComprobante')
    TotalComprobante.text = str(invoice.amount_total)
    ResumenFactura.append(TotalComprobante)

    FacturaElectronica.append(ResumenFactura)

    # Normativa
    Normativa = etree.Element('Normativa')

    NumeroResolucion = etree.Element('NumeroResolucion')
    NumeroResolucion.text = 'DGT-R-48-2016'
    Normativa.append(NumeroResolucion)

    FechaResolucion = etree.Element('FechaResolucion')
    FechaResolucion.text = '07-10-2016 08:00:00'
    Normativa.append(FechaResolucion)

    FacturaElectronica.append(Normativa)

    return etree.tostring(FacturaElectronica, pretty_print=True).decode()


def make_xml_invoice(inv, tipo_documento, consecutivo, date, sale_conditions, medio_pago, total_servicio_gravado,
                     total_servicio_exento, total_mercaderia_gravado, total_mercaderia_exento, base_total, lines,
                     tipo_documento_referencia, numero_documento_referencia, fecha_emision_referencia,
                     codigo_referencia, razon_referencia, url, currency_rate):
    headers = {}
    payload = {}
    # Generar FE payload
    payload['w'] = 'genXML'
    if tipo_documento == 'FE':
        payload['r'] = 'gen_xml_fe'
    elif tipo_documento == 'NC':
        payload['r'] = 'gen_xml_nc'
    payload['clave'] = inv.number_electronic
    payload['consecutivo'] = consecutivo
    payload['fecha_emision'] = date
    payload['emisor_nombre'] = inv.company_id.name
    payload['emisor_tipo_indetif'] = inv.company_id.identification_id.code
    payload['emisor_num_identif'] = inv.company_id.vat
    payload['nombre_comercial'] = inv.company_id.commercial_name or ''
    payload['emisor_provincia'] = inv.company_id.state_id.code
    payload['emisor_canton'] = inv.company_id.county_id.code
    payload['emisor_distrito'] = inv.company_id.district_id.code
    payload['emisor_barrio'] = inv.company_id.neighborhood_id.code or ''
    payload['emisor_otras_senas'] = inv.company_id.street
    payload['emisor_cod_pais_tel'] = inv.company_id.phone_code
    payload['emisor_tel'] = re.sub('[^0-9]+', '', inv.company_id.phone)
    payload['emisor_email'] = inv.company_id.email
    payload['receptor_nombre'] = inv.partner_id.name[:80]
    payload['receptor_tipo_identif'] = inv.partner_id.identification_id.code or ''
    payload['receptor_num_identif'] = inv.partner_id.vat or ''
    payload['receptor_provincia'] = inv.partner_id.state_id.code or ''
    payload['receptor_canton'] = inv.partner_id.county_id.code or ''
    payload['receptor_distrito'] = inv.partner_id.district_id.code or ''
    payload['receptor_barrio'] = inv.partner_id.neighborhood_id.code or ''
    payload['receptor_cod_pais_tel'] = inv.partner_id.phone_code or ''
    payload['receptor_tel'] = re.sub('[^0-9]+', '', inv.partner_id.phone or '')
    payload['receptor_email'] = inv.partner_id.email or ''
    payload['condicion_venta'] = sale_conditions
    payload['plazo_credito'] = inv.partner_id.property_payment_term_id.line_ids[0].days or '0'
    payload['medio_pago'] = medio_pago
    payload['cod_moneda'] = inv.currency_id.name
    payload['tipo_cambio'] = currency_rate
    payload['total_serv_gravados'] = total_servicio_gravado
    payload['total_serv_exentos'] = total_servicio_exento
    payload['total_merc_gravada'] = total_mercaderia_gravado
    payload['total_merc_exenta'] = total_mercaderia_exento
    payload['total_gravados'] = total_servicio_gravado + total_mercaderia_gravado
    payload['total_exentos'] = total_servicio_exento + total_mercaderia_exento
    payload['total_ventas'] = total_servicio_gravado + total_mercaderia_gravado + total_servicio_exento + total_mercaderia_exento
    payload['total_descuentos'] = round(base_total - inv.amount_untaxed, 2)
    payload['total_ventas_neta'] = round((total_servicio_gravado + total_mercaderia_gravado + total_servicio_exento + total_mercaderia_exento) - \
                                   (base_total - inv.amount_untaxed), 2)
    payload['total_impuestos'] = round(inv.amount_tax, 2)
    payload['total_comprobante'] = round(inv.amount_total, 2)
    payload['otros'] = ''
    payload['detalles'] = lines

    if tipo_documento == 'NC':
        payload['infoRefeTipoDoc'] = tipo_documento_referencia
        payload['infoRefeNumero'] = numero_documento_referencia
        payload['infoRefeFechaEmision'] = fecha_emision_referencia
        payload['infoRefeCodigo'] = codigo_referencia
        payload['infoRefeRazon'] = razon_referencia

    response = requests.request("POST", url, data=payload, headers=headers)
    response_json = response.json()
    return response_json


def token_hacienda(inv, env, url):

    url = 'https://idp.comprobanteselectronicos.go.cr/auth/realms/rut-stag/protocol/openid-connect/token'

    data = {
        'client_id': env,
        'client_secret': '',
        'grant_type': 'password',
        'username': inv.company_id.frm_ws_identificador,
        'password': inv.company_id.frm_ws_password}

    try:
        response = requests.post(url, data=data)

    except requests.exceptions.RequestException as e:
        _logger.error('Exception %s' % e)
        raise Exception(e)

    return {'resp': response.json()}


def sign_xml(inv, tipo_documento, url, xml):
    payload = {}
    headers = {}
    payload['w'] = 'signXML'
    payload['r'] = 'signFE'
    payload['p12Url'] = inv.company_id.frm_apicr_signaturecode
    payload['inXml'] = xml
    payload['pinP12'] = inv.company_id.frm_pin
    payload['tipodoc'] = tipo_documento

    response = requests.request("POST", url, data=payload, headers=headers)
    response_json = response.json()
    return response_json


def send_file(inv, token, date, xml, env, url):

    if env == 'api-stag':
        url = 'https://api.comprobanteselectronicos.go.cr/recepcion-sandbox/v1/recepcion/'
    elif env == 'api-prod':
        url = 'https://api.comprobanteselectronicos.go.cr/recepcion/v1/recepcion/'

    xml = base64.b64decode(xml)

    factura = etree.tostring(etree.fromstring(xml)).decode()
    factura = etree.fromstring(re.sub(' xmlns="[^"]+"', '', factura, count=1))

    Clave = factura.find('Clave')
    FechaEmision = factura.find('FechaEmision')
    Emisor = factura.find('Emisor')
    Receptor = factura.find('Receptor')

    comprobante = {}
    comprobante['clave'] = Clave.text
    comprobante["fecha"] = FechaEmision.text
    comprobante['emisor'] = {}
    comprobante['emisor']['tipoIdentificacion'] = Emisor.find('Identificacion').find('Tipo').text
    comprobante['emisor']['numeroIdentificacion'] = Emisor.find('Identificacion').find('Numero').text
    if Receptor is not None and Receptor.find('Identificacion') is not None:
        comprobante['receptor'] = {}
        comprobante['receptor']['tipoIdentificacion'] = Receptor.find('Identificacion').find('Tipo').text
        comprobante['receptor']['numeroIdentificacion'] = Receptor.find('Identificacion').find('Numero').text

    comprobante['comprobanteXml'] = base64.b64encode(xml).decode('utf-8')

    headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer {}'.format(token)}

    try:
        response = requests.post(url, data=json.dumps(comprobante), headers=headers)

    except requests.exceptions.RequestException as e:
        _logger.info('Exception %s' % e)
        raise Exception(e)

    return {'resp': {'Status': response.status_code, 'text': response.text}}


def consulta_documentos(self, inv, env, token_m_h, url, date_cr, xml_firmado):
    payload = {}
    headers = {}
    payload['w'] = 'consultar'
    payload['r'] = 'consultarCom'
    payload['client_id'] = env
    payload['token'] = token_m_h
    payload['clave'] = inv.number_electronic
    response = requests.request("POST", url, data=payload, headers=headers)
    response_json = response.json()
    estado_m_h = response_json.get('resp').get('ind-estado')

    # Siempre sin importar el estado se actualiza la fecha de acuerdo a la devuelta por Hacienda y
    # se carga el xml devuelto por Hacienda
    if inv.type == 'out_invoice' or inv.type == 'out_refund':
        # Se actualiza el estado con el que devuelve Hacienda
        inv.state_tributacion = estado_m_h
        inv.date_issuance = date_cr
        inv.fname_xml_comprobante = 'comprobante_' + inv.number_electronic + '.xml'
        inv.xml_comprobante = xml_firmado
    elif inv.type == 'in_invoice' or inv.type == 'in_refund':
        inv.fname_xml_comprobante = 'receptor_' + inv.number_electronic + '.xml'
        inv.xml_comprobante = xml_firmado
        inv.state_send_invoice = estado_m_h

    # Si fue aceptado o rechazado por haciendo se carga la respuesta
    if (estado_m_h == 'aceptado' or estado_m_h == 'rechazado') or (inv.type == 'out_invoice'  or inv.type == 'out_refund'):
        inv.fname_xml_respuesta_tributacion = 'respuesta_' + inv.number_electronic + '.xml'
        inv.xml_respuesta_tributacion = response_json.get('resp').get('respuesta-xml')

    # Si fue aceptado por Hacienda y es un factura de cliente o nota de crédito, se envía el correo con los documentos
    if estado_m_h == 'aceptado':
        if not inv.partner_id.opt_out:
            if inv.type == 'in_invoice' or inv.type == 'in_refund':
                email_template = self.env.ref('cr_electronic_invoice.email_template_invoice_vendor', False)
            else:
                email_template = self.env.ref('account.email_template_edi_invoice', False)

            attachments = []

            attachment = self.env['ir.attachment'].search(
                [('res_model', '=', 'account.invoice'), ('res_id', '=', inv.id),
                 ('res_field', '=', 'xml_comprobante')], limit=1)
            if attachment.id:
                attachment.name = inv.fname_xml_comprobante
                attachment.datas_fname = inv.fname_xml_comprobante
                attachments.append(attachment.id)

            attachment_resp = self.env['ir.attachment'].search(
                [('res_model', '=', 'account.invoice'), ('res_id', '=', inv.id),
                 ('res_field', '=', 'xml_respuesta_tributacion')], limit=1)
            if attachment_resp.id:
                attachment_resp.name = inv.fname_xml_respuesta_tributacion
                attachment_resp.datas_fname = inv.fname_xml_respuesta_tributacion
                attachments.append(attachment_resp.id)

            if len(attachments) == 2:
                email_template.attachment_ids = [(6, 0, attachments)]

                email_template.with_context(type='binary', default_type='binary').send_mail(inv.id,
                                                                                            raise_exception=False,
                                                                                            force_send=True)  # default_type='binary'

                # limpia el template de los attachments
                email_template.attachment_ids = [(5)]
