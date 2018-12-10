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


def get_clave(invoice, url, tipo_documento, numeracion, sucursal=1, terminal=1, situacion='normal'):
    _logger.info('aqui')
    _logger.info('get_clave con %s %s %s %s %s %s %s' % (invoice, url, tipo_documento, numeracion, sucursal, terminal, situacion))

    # tipo de documento
    tipos_de_documento = { 'FE'  : '01', # Factura Electrónica
                           'ND'  : '02', # Nota de Débito
                           'NC'  : '03', # Nota de Crédito
                           'TE'  : '04', # Tiquete Electrónico
                           'CCE' : '05', # Confirmación Comprobante Electrónico
                           'CPCE': '06', # Confirmación Parcial Comprobante Electrónico
                           'RCE' : '07'} # Rechazo Comprobante Electrónico

    _logger.info('tipo %s' % tipos_de_documento[tipo_documento])

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
    if not invoice.company_id.identification_id:
        raise UserError('Seleccione el tipo de identificación del emisor en el perfil de la compañía')

    # identificación
    identificacion = re.sub('[^0-9]', '', invoice.company_id.vat or '')

    if invoice.company_id.identification_id.code == '01' and len(identificacion) != 9:
        raise UserError('La Cédula Física del emisor debe de tener 9 dígitos')
    elif invoice.company_id.identification_id.code == '02' and len(identificacion) != 10:
        raise UserError('La Cédula Jurídica del emisor debe de tener 10 dígitos')
    elif invoice.company_id.identification_id.code == '03' and (len(identificacion) != 11 or len(identificacion) != 12):
        raise UserError('La identificación DIMEX del emisor debe de tener 11 o 12 dígitos')
    elif invoice.company_id.identification_id.code == '04' and len(identificacion) != 10:
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


    respuesta = {'resp': {'length': len(clave), 'clave': clave, 'consecutivo': consecutivo}}
    _logger.info('get_clave returning %s' % respuesta)
    return respuesta


def make_xml_invoice(inv, tipo_documento, consecutivo, date, sale_conditions, medio_pago, total_servicio_gravado,
                     total_servicio_exento, total_mercaderia_gravado, total_mercaderia_exento, base_total,

                    lines,
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
    payload['emisor_num_identif'] = re.sub('[^0-9]+', '', inv.company_id.vat)
    payload['nombre_comercial'] = inv.company_id.commercial_name or inv.company_id.name
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
    plazo_credito = str((datetime.datetime.strptime(inv.date_invoice,'%Y-%m-%d') - datetime.datetime.strptime(inv.date_due, '%Y-%m-%d')).days)
    payload['plazo_credito'] = plazo_credito
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

    calculated = 0.0
    lines_json = json.loads(lines)
    _logger.info('lines %s' % lines)
    for line in lines_json:
        _logger.info('line %s' % lines_json[line])
        if '1' in lines_json[line]['impuesto']:
            _logger.info('line %s' % lines_json[line]['impuesto']['1']['monto'])
            calculated += float(lines_json[line]['impuesto']['1']['monto'])

    _logger.info('calculated %s' % calculated)
    _logger.info('amount_tax %s' % inv.amount_tax)
    _logger.info('amount_tax rounded %s' % round(inv.amount_tax, 2))
    # raise UserError('suave')



    payload['total_impuestos'] = calculated
    # payload['total_impuestos'] = round(inv.amount_tax, 2)
    payload['total_comprobante'] = round(inv.amount_total, 2)
    payload['otros'] = ''
    payload['detalles'] = lines

    if tipo_documento == 'NC':
        payload['infoRefeTipoDoc'] = tipo_documento_referencia
        payload['infoRefeNumero'] = numero_documento_referencia
        payload['infoRefeFechaEmision'] = fecha_emision_referencia
        payload['infoRefeCodigo'] = codigo_referencia
        payload['infoRefeRazon'] = razon_referencia

    _logger.info('requesting xml with %s' % payload)

    response = requests.request("POST", url, data=payload, headers=headers)
    _logger.info('response %s' % response)
    _logger.info('response %s' % response.__dict__)
    response_json = response.json()

    _logger.info('make_xml_invoice returning %s' % response_json)

    return response_json

def _token_hacienda(invoice):
    return token_hacienda(invoice, invoice.company_id.frm_ws_ambiente, invoice.company_id.frm_callback_url)


def token_hacienda(inv, env, url=None):

    if env == 'api-stag':
        url = 'https://idp.comprobanteselectronicos.go.cr/auth/realms/rut-stag/protocol/openid-connect/token'
    elif env == 'api-prod':
        url = 'https://idp.comprobanteselectronicos.go.cr/auth/realms/rut/protocol/openid-connect/token'

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
        return False

    respuesta = {'resp': response.json()}
    _logger.info('token_hacienda returning %s' % respuesta)

    return respuesta


def sign_xml(inv, tipo_documento, url, xml):
    payload = {}
    headers = {}
    payload['w'] = 'signXML'
    payload['r'] = 'signFE'
    payload['p12Url'] = inv.company_id.frm_apicr_signaturecode
    payload['inXml'] = base64.b64encode(bytes(xml, 'utf-8')).decode('utf-8')
    payload['inXml'] = xml
    payload['pinP12'] = inv.company_id.frm_pin
    payload['tipodoc'] = tipo_documento

    response = requests.request("POST", url, data=payload, headers=headers)

    response_json = response.json()
    return response_json


def _send_file(invoice, token, xml_firmado):
    return send_file(invoice, token, invoice.date_issuance, xml_firmado, invoice.company_id.frm_ws_ambiente, invoice.company_id.frm_callback_url)


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

    respuesta = {'resp': {'Status': response.status_code, 'text': response.text}}
    _logger.info('send_file returning %s' % respuesta)

    return respuesta


def consulta_documentos(self, inv, env, token_m_h, url, date_cr, xml_firmado):
    _logger.info('consulta_documentos')
    payload = {}
    headers = {}
    payload['w'] = 'consultar'
    payload['r'] = 'consultarCom'
    payload['client_id'] = env
    payload['token'] = token_m_h
    payload['clave'] = inv.number_electronic
    response = requests.request("POST", url, data=payload, headers=headers)
    _logger.info('response %s' % response.__dict__)
    response_json = response.json()

    if 'resp' not in response_json or 'ind-estado' not in response_json.get('resp'):
        _logger.info('error de comunicación %s' % response.__dict__)
        return

    if not date_cr:
        now_utc = datetime.datetime.now(pytz.timezone('UTC'))
        now_cr = now_utc.astimezone(pytz.timezone('America/Costa_Rica'))
        date_cr = now_cr.strftime("%Y-%m-%dT%H:%M:%S-06:00")

    if not xml_firmado:
        xml_firmado = inv.xml_comprobante

    estado_m_h = response_json.get('resp').get('ind-estado')
    _logger.info('estado de %s es %s' % (inv.number_electronic, estado_m_h))

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

def findwholeword(word, search):
    return word.find(search)