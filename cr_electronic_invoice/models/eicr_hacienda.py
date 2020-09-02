# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.tools import DEFAULT_SERVER_DATE_FORMAT as DATE_FORMAT, DEFAULT_SERVER_DATETIME_FORMAT as DATETIME_FORMAT
from odoo.exceptions import UserError
import requests
import json
from datetime import datetime, timedelta
from lxml import etree
import logging
import re
import random
import os
import subprocess
import base64
import pytz, ast
import sys

EICR_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S-06:00"

_logger = logging.getLogger(__name__)


class ElectronicInvoiceCostaRicaHacienda(models.AbstractModel):
    _name = 'eicr.hacienda'
    _description = 'Herramienta de comunicación con Hacienda'


    def get_token(self, company_id):
        _logger.info('checking token')

        if company_id.eicr_token:
            try:
                token = ast.literal_eval(company_id.eicr_token)
                valid_since = datetime.strptime(token['timestamp'], '%Y-%m-%d %H:%M:%S')
                valid_until = valid_since + timedelta(seconds=token['expires_in'])
                now = datetime.now()
                ttl = (valid_until - now).total_seconds()
                extra_time = 30
                if ttl - extra_time > 0:
                    _logger.info('token still valid for %s seconds' % ttl)
                    return token['access_token']
            except Exception as e:
                _logger.info('Exception\n%s' % e)

        return self._refresh_token(company_id)

    def _refresh_token(self, company_id):
        _logger.info('refreshing token')

        if not self.env['eicr.tools'].eicr_habilitado(company_id): return False

        data = {
            'client_id': company_id.eicr_environment,
            'client_secret': '',
            'grant_type': 'password',
            'username': company_id.eicr_username,
            'password': company_id.eicr_password}

        try:
            url = self._get_url_auth(company_id)
            response = requests.post(url, data=data, timeout=5)
            _logger.info('response %s' % response.__dict__)
            respuesta = response.json()
            if 'access_token' in respuesta:
                respuesta['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                company_id.eicr_token = respuesta
                self.env.cr.commit()
                _logger.info('token renovado para %s' % company_id)
                return respuesta['access_token']
            else:
                return False

        except requests.exceptions.RequestException as e:
            _logger.info('RequestException\n%s' % e)
            return False
        except KeyError as e:
            _logger.info('KeyError\n%s' % e)
            return False
        except Exception as e:
            _logger.info('Exception\n%s' % e)
            return False

    def _get_url_auth(self, company_id):
        if company_id.eicr_environment == 'api-prod':
            return company_id.eicr_version_id.url_auth_endpoint_production
        elif company_id.eicr_environment == 'api-stag':
            return company_id.eicr_version_id.url_auth_endpoint_testing
        else:
            return None

    def get_info_contribuyente(self, identificacion=None):
        '''Obtiene la información del contribuyente'''
        if identificacion is None: identificacion = self.company_id.vat
        identificacion = re.sub('[^0-9]', '', identificacion or '')

        try:
            url = 'https://api.hacienda.go.cr/fe/ae'
            response = requests.get(url, params={'identificacion': identificacion}, timeout=5, verify=False)

        except requests.exceptions.RequestException as e:
            _logger.info('RequestException %s' % e)
            return False

        _logger.info('%s %s' % (response, response.__dict__))

        if response.status_code in (200,):
            _logger.info(response.json())
            return response.json()
        else:
            return False

    def _get_url(self, company_id):
        if company_id.eicr_environment == 'api-prod':
            return company_id.eicr_version_id.url_reception_endpoint_production
        elif company_id.eicr_environment == 'api-stag':
            return company_id.eicr_version_id.url_reception_endpoint_testing
        else:
            return None

    def _enviar_documento(self, object):

        if not self.env['eicr.tools'].eicr_habilitado(object.company_id): return False

        _logger.info('validando %s' % object)

        if object.state_tributacion != 'pendiente':
            _logger.info('Solo enviamos pendientes, no se va a enviar %s' % object)
            return False
        if not object.xml_comprobante:
            _logger.info('%s sin xml' % object)
            return False

        xml = base64.b64decode(object.xml_comprobante)

        Documento = etree.tostring(etree.fromstring(xml)).decode()
        Documento = etree.fromstring(re.sub(' xmlns="[^"]+"', '', Documento, count=1))

        Clave = Documento.find('Clave')

        _logger.info('Documento %s' % Documento)

        if self.env['eicr.tools']._es_mensaje_aceptacion(object):
            xml_factura_proveedor = object.xml_supplier_approval
            xml_factura_proveedor = base64.b64decode(xml_factura_proveedor)
            FacturaElectronica = etree.tostring(etree.fromstring(xml_factura_proveedor)).decode()
            FacturaElectronica = etree.fromstring(re.sub(' xmlns="[^"]+"', '', FacturaElectronica, count=1))
            Emisor = FacturaElectronica.find('Receptor')
            Receptor = FacturaElectronica.find('Emisor')
            FechaEmision = Documento.find('FechaEmisionDoc')
        else:
            Emisor = Documento.find('Emisor')
            Receptor = Documento.find('Receptor')
            FechaEmision = Documento.find('FechaEmision')

        mensaje = {}
        mensaje['clave'] = Clave.text
        mensaje['fecha'] = FechaEmision.text
        mensaje['emisor'] = {}
        mensaje['emisor']['tipoIdentificacion'] = Emisor.find('Identificacion').find('Tipo').text
        mensaje['emisor']['numeroIdentificacion'] = Emisor.find('Identificacion').find('Numero').text
        if Receptor is not None and Receptor.find('Identificacion') is not None:
            mensaje['receptor'] = {}
            mensaje['receptor']['tipoIdentificacion'] = Receptor.find('Identificacion').find('Tipo').text
            mensaje['receptor']['numeroIdentificacion'] = Receptor.find('Identificacion').find('Numero').text

        mensaje['comprobanteXml'] = base64.b64encode(xml).decode('utf-8')

        if self.env['eicr.tools']._es_mensaje_aceptacion(object):
            mensaje['consecutivoReceptor'] = Documento.find('NumeroConsecutivoReceptor').text

        token = self.get_token(object.company_id)
        if token is None or token is False:
            _logger.info('No hay conexión con hacienda')
            return False

        headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer {}'.format(token)}

        try:
            url = self._get_url(object.company_id)
            _logger.info('validando %s %s' % (object, Clave.text))
            response = requests.post(url, data=json.dumps(mensaje), headers=headers, timeout=10)
            _logger.info('Respuesta de hacienda\n%s' % response)

        except requests.exceptions.RequestException as e:
            _logger.info('RequestException %s' % e)
            raise Exception(e)

        if response.status_code == 202:
            _logger.info('documento entregado %s' % response)
            object.state_tributacion = 'recibido'
            return True
        if response.status_code in (522, 524):
            object.state_tributacion = 'error'
            object.respuesta_tributacion = response.content
            return False
        else:
            error_cause = response.headers[
                'X-Error-Cause'] if 'X-Error-Cause' in response.headers else 'Error desconocido'
            _logger.info('Error %s %s %s' % (response.status_code, error_cause, response.headers))
            object.state_tributacion = 'error'
            object.respuesta_tributacion = error_cause

            if 'ya fue recibido anteriormente' in object.respuesta_tributacion:
                object.state_tributacion = 'recibido'

            if 'no ha sido recibido' in object.respuesta_tributacion:
                object.state_tributacion = 'pendiente'

            return False

    def _consultar_documento(self, object):
        _logger.info('preguntando por %s' % object)

        if not self.env['eicr.tools'].eicr_habilitado(object.company_id): return False

        if object.xml_comprobante:
            xml = etree.tostring(etree.fromstring(base64.b64decode(object.xml_comprobante))).decode()
            Documento = etree.fromstring(re.sub(' xmlns="[^"]+"', '', xml, count=1))
            clave = Documento.find('Clave').text
            if not object.date_issuance:
                object.date_issuance = Documento.find('FechaEmision').text
        elif object.number_electronic:
            clave = object.number_electronic
        else:
            _logger.error('no vamos a continuar, factura sin xml ni clave')
            return False

        token = self.get_token(object.company_id)
        if token is None or token is False:
            _logger.info('No hay conexión con hacienda')
            return False

        headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer {}'.format(token)}

        if self.env['eicr.tools']._es_mensaje_aceptacion(object):
            clave += '-' + object.number

        try:
            url = self._get_url(object.company_id) + '/' + clave
            # this is made so we can work with focken hacienda
            url = url.replace('https','http') 
            _logger.info('preguntando con %s' % url)
            response = requests.get(url, data=json.dumps({'clave': clave}), headers=headers, timeout=5)

        except requests.exceptions.RequestException as e:
            _logger.info('no vamos a continuar, Exception %s' % e)
            return False

        if response.status_code in (301, 400):
            _logger.info('Error %s %s' % (response.status_code, response.headers['X-Error-Cause']))
            _logger.info('no vamos a continuar, algo inesperado sucedió %s' % response.__dict__)
            object.state_tributacion = 'error'
            object.respuesta_tributacion = response.headers[
                'X-Error-Cause'] if response.headers and 'X-Error-Cause' in response.headers else 'No hay de Conexión con Hacienda'
            if 'ya fue recibido anteriormente' in object.respuesta_tributacion: object.state_tributacion = 'recibido'
            if 'no ha sido recibido' in object.respuesta_tributacion: object.state_tributacion = 'pendiente'
            return False
        if response.status_code in (403, 500, 502, 522, 524):
            object.state_tributacion = 'error'
            object.respuesta_tributacion = response.content
            return False

        _logger.info('respuesta %s' % response.__dict__)

        respuesta = response.json()

        if 'ind-estado' not in respuesta:
            _logger.info('no vamos a continuar, no se entiende la respuesta de hacienda')
            return False

        _logger.info('respuesta de hacienda %s' % response)
        _logger.info('respuesta para %s %s' % (object, respuesta['ind-estado']))

        object.state_tributacion = respuesta['ind-estado']
        if respuesta['ind-estado'] == 'procesando': object.respuesta_tributacion = 'Procesando comprobante'

        # Se actualiza la factura con la respuesta de hacienda

        if 'respuesta-xml' in respuesta:
            object.fname_xml_respuesta_tributacion = 'MensajeHacienda_' + respuesta['clave'] + '.xml'
            object.xml_respuesta_tributacion = respuesta['respuesta-xml']

            respuesta = etree.tostring(etree.fromstring(base64.b64decode(object.xml_respuesta_tributacion))).decode()
            respuesta = etree.fromstring(re.sub(' xmlns="[^"]+"', '', respuesta, count=1))
            object.respuesta_tributacion = respuesta.find('DetalleMensaje').text

        return True

    @api.model
    def _validahacienda(self, max_documentos=4):  # cron

        try:
            invoice = self.env['account.invoice']
        except KeyError as e:
            invoice = None
        except:
            _logger.info('unknown error %s' % sys.exc_info()[0])

        try:
            order = self.env['pos.order']
        except KeyError as e:
            order = None
        except:
            _logger.info('unknown error %s' % sys.exc_info()[0])

        try:
            expense = self.env['hr.expense']
        except KeyError:
            expense = None
        except:
            _logger.info('unknown error %s' % sys.exc_info()[0])

        if invoice != None:
            facturas = invoice.search([('state', 'in', ('open', 'paid')),
                                       ('state_tributacion', 'in', ('pendiente',))],
                                      limit=max_documentos).sorted(key=lambda i: i.number)
            _logger.info('Validando %s FacturaElectronica' % len(facturas))
            for indice, factura in enumerate(facturas):
                _logger.info('Validando FacturaElectronica %s / %s ' % (indice + 1, len(facturas)))
                if not factura.xml_comprobante:
                    pass
                self._enviar_documento(factura)
                self.env.cr.commit()

        if order != None:
            tiquetes = order.search([('state_tributacion', 'in', ('pendiente',))],
                                    limit=max_documentos).sorted(key=lambda o: o.name)
            _logger.info('Validando %s TiqueteElectronico' % len(tiquetes))
            for indice, tiquete in enumerate(tiquetes):
                _logger.info('Validando TiqueteElectronico %s / %s ' % (indice + 1, len(tiquetes)))
                if not tiquete.xml_comprobante:
                    tiquete.state_tributacion = 'na'
                    pass
                self._enviar_documento(tiquete)
                self.env.cr.commit()

        if expense != None:
            gastos = expense.search([('state_tributacion', 'in', ('pendiente',))],
                                    limit=max_documentos).sorted(key=lambda e: e.reference)
            _logger.info('Validando %s Gastos' % len(gastos))
            for indice, gasto in enumerate(gastos):
                _logger.info('Validando Gasto %s/%s %s' % (indice + 1, len(gastos), gasto))
                if not gasto.xml_supplier_approval:
                    gasto.state_tributacion = 'na'
                    pass
                elif not gasto.xml_comprobante:
                    xml = self.env['eicr.tools'].get_xml(gasto)
                    if xml:
                        gasto.xml_comprobante = xml
                        gasto.fname_xml_comprobante = 'MensajeReceptor_' + gasto.number_electronic + '.xml'
                    else:
                        gasto.state_tributacion = 'na'
                        pass
                self._enviar_documento(gasto)
                self.env.cr.commit()

        _logger.info('Valida - Finalizado Exitosamente')

    @api.model
    def _consultahacienda(self, max_documentos=4):  # cron

        try:
            invoice = self.env['account.invoice']
        except KeyError:
            invoice = None

        try:
            order = self.env['pos.order']
        except KeyError:
            order = None

        try:
            expense = self.env['hr.expense']
        except KeyError:
            expense = None

        if invoice != None:
            facturas = invoice.search([('type', 'in', ('out_invoice', 'out_refund', 'in_invoice')),
                                       ('state', 'in', ('open', 'paid')),
                                       ('state_tributacion', 'in', ('recibido', 'procesando', 'error'))],
                                      limit=max_documentos)

            for indice, factura in enumerate(facturas):
                _logger.info('Consultando documento %s / %s ' % (indice + 1, len(facturas)))
                if not factura.xml_comprobante: pass
                if self._consultar_documento(factura) and factura.type != 'out_refund':
                    self.env['eicr.tools']._enviar_email(factura)
                self.env.cr.commit()
                max_documentos -= 1

        if order != None:
            tiquetes = order.search([('state_tributacion', 'in', ('recibido', 'procesando', 'error'))],
                                    limit=max_documentos)

            for indice, tiquete in enumerate(tiquetes):
                _logger.info('Consultando documento %s / %s ' % (indice + 1, len(tiquetes)))
                if not tiquete.xml_comprobante:
                    pass
                if self._consultar_documento(tiquete):
                    self.env['eicr.tools']._enviar_email(tiquete)
                self.env.cr.commit()
                max_documentos -= 1

        if expense != None:
            gastos = expense.search([('state_tributacion', 'in', ('recibido', 'procesando', 'error'))],
                                    limit=max_documentos)
            for indice, gasto in enumerate(gastos):
                _logger.info('Consultando documento %s / %s ' % (indice + 1, len(gastos)))
                if not gasto.xml_comprobante:
                    pass
                self._consultar_documento(gasto)
                self.env.cr.commit()
                max_documentos -= 1

        _logger.info('Consulta Hacienda - Finalizado Exitosamente')
