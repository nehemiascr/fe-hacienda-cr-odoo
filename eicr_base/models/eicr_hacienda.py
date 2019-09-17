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


class ElectronicInvoiceCostaRicaTools(models.AbstractModel):
	_name = 'eicr.hacienda'
	_description = 'Herramientas de comunicación con Hacienda'



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

		if company_id.eicr_environment == 'disabled': return False

		data = {
			'client_id': company_id.eicr_environment,
			'client_secret': '',
			'grant_type': 'password',
			'username': company_id.eicr_username,
			'password': company_id.eicr_password}

		try:
			url = self._get_url_auth(company_id)
			response = requests.post(url, data=data)
			_logger.info('response %s' % response.__dict__)
			respuesta = response.json()
			if 'access_token' in respuesta:
				respuesta['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
				company_id.eicr_token = respuesta
				_logger.info('token renovado %s' % company_id.eicr_token)
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

	def _get_url(self, company_id):
		if company_id.eicr_environment == 'api-prod':
			return company_id.eicr_version_id.url_reception_endpoint_production
		elif company_id.eicr_environment == 'api-stag':
			return company_id.eicr_version_id.url_reception_endpoint_testing
		else:
			return None

	def _get_url_auth(self, company_id):
		if company_id.eicr_environment == 'api-prod':
			return company_id.eicr_version_id.url_auth_endpoint_production
		elif company_id.eicr_environment == 'api-stag':
			return company_id.eicr_version_id.url_auth_endpoint_testing
		else:
			return None

	def _enviar_documento(self, object):

		if not self.env['eicr.tools']._fe_habilitado(object.company_id):
			return False

		_logger.info('validando %s' % object)

		if object.eicr_state != 'pendiente':
			_logger.info('Solo enviamos pendientes, no se va a enviar %s' % object)
			return False
		if not object.eicr_documento_file:
			_logger.info('%s sin xml' % object)
			return False

		xml = base64.b64decode(object.eicr_documento_file)

		Documento = etree.tostring(etree.fromstring(xml)).decode()
		Documento = etree.fromstring(re.sub(' xmlns="[^"]+"', '', Documento, count=1))

		Clave = Documento.find('Clave')

		_logger.info('Documento %s' % Documento)

		if self.env['eicr.tools']._es_mensaje_aceptacion(object):
			xml_factura_proveedor = object.eicr_documento2_file
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
			response = requests.post(url, data=json.dumps(mensaje), headers=headers)
			_logger.info('Respuesta de hacienda\n%s' % response)

		except requests.exceptions.RequestException as e:
			_logger.info('RequestException %s' % e)
			raise Exception(e)

		if response.status_code == 202:
			_logger.info('documento entregado %s' % response)
			object.eicr_state = 'recibido'
			return True
		if response.status_code in (522, 524):
			object.eicr_state = 'error'
			object.eicr_mensaje_hacienda = response.content
			return False
		else:
			error_cause = response.headers['X-Error-Cause'] if 'X-Error-Cause' in response.headers else 'Error desconocido'
			_logger.info('Error %s %s %s' % (response.status_code, error_cause, response.headers))
			object.eicr_state = 'error'
			object.eicr_mensaje_hacienda = error_cause

			if 'ya fue recibido anteriormente' in object.eicr_mensaje_hacienda:
				object.eicr_state = 'recibido'

			if 'no ha sido recibido' in object.eicr_mensaje_hacienda:
				object.eicr_state = 'pendiente'

			return False

	def _consultar_documento(self, object):
		_logger.info('preguntando por %s' % object)

		if not self.env['eicr.tools']._fe_habilitado(object.company_id): return False

		if object.eicr_documento_file:
			xml = etree.tostring(etree.fromstring(base64.b64decode(object.eicr_documento_file))).decode()
			Documento = etree.fromstring(re.sub(' xmlns="[^"]+"', '', xml, count=1))
			clave = Documento.find('Clave').text
			if not object.eicr_date:
				object.eicr_date = self.env['eicr.tools'].datetime_obj(Documento.find('FechaEmision').text)
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
			_logger.info('preguntando con %s' % url)
			response = requests.get(url, data=json.dumps({'clave': clave}), headers=headers)

		except requests.exceptions.RequestException as e:
			_logger.info('no vamos a continuar, Exception %s' % e)
			return False

		if response.status_code in (301, 400):
			_logger.info('Error %s %s' % (response.status_code, response.headers['X-Error-Cause']))
			_logger.info('no vamos a continuar, algo inesperado sucedió %s' % response.__dict__)
			object.eicr_state = 'error'
			object.eicr_mensaje_hacienda = response.headers['X-Error-Cause'] if response.headers and 'X-Error-Cause' in response.headers else 'No hay de Conexión con Hacienda'
			if 'ya fue recibido anteriormente' in object.eicr_mensaje_hacienda: object.eicr_state = 'recibido'
			if 'no ha sido recibido' in object.eicr_mensaje_hacienda: object.eicr_state = 'pendiente'
			return False
		if response.status_code in (502,522, 524):
			object.eicr_state = 'error'
			object.eicr_mensaje_hacienda = response.content
			return False


		_logger.info('respuesta %s' % response.__dict__)

		respuesta = response.json()

		if 'ind-estado' not in respuesta:
			_logger.info('no vamos a continuar, no se entiende la respuesta de hacienda')
			return False

		_logger.info('respuesta de hacienda %s' %  response)
		_logger.info('respuesta para %s %s' % (object, respuesta['ind-estado']))

		object.eicr_state = respuesta['ind-estado']
		if respuesta['ind-estado'] == 'procesando': object.eicr_mensaje_hacienda = 'Procesando comprobante'

		# Se actualiza la factura con la respuesta de hacienda

		if 'respuesta-xml' in respuesta:
			object.eicr_mensaje_hacienda_fname = 'MensajeHacienda_' + respuesta['clave'] + '.xml'
			object.eicr_mensaje_hacienda_file = respuesta['respuesta-xml']

			respuesta = etree.tostring(etree.fromstring(base64.b64decode(object.eicr_mensaje_hacienda_file))).decode()
			respuesta = etree.fromstring(re.sub(' xmlns="[^"]+"', '', respuesta, count=1))
			object.eicr_mensaje_hacienda = respuesta.find('DetalleMensaje').text

		return True

	@api.model
	def _validahacienda(self, max_documentos=4):  # cron

		Invoice = self.env['account.invoice'] if self.env['eicr.tools'].module_installed('eicr_invoicing') else None
		Order = self.env['pos.order'] if self.env['eicr.tools'].module_installed('eicr_pos') else None
		Expense = self.env['hr.expense'] if self.env['eicr.tools'].module_installed('eicr_expense') else None

		if Invoice is not None:
			facturas = Invoice.search([('state', 'in', ('open', 'paid')),
									   ('eicr_state', 'in', ('pendiente',))],
									  limit=max_documentos).sorted(key=lambda i: i.number)
			_logger.info('Validating %s Invoices' % len(facturas))
			for indice, factura in enumerate(facturas):
				_logger.info('Validating Invoice %s / %s ' % (indice+1, len(facturas)))
				if not factura.eicr_documento_file:
					pass
				self._enviar_documento(factura)

		if Order is not None:
			tiquetes = Order.search([('eicr_state', 'in', ('pendiente',))],
									limit=max_documentos).sorted(key=lambda o: o.name)
			_logger.info('Validating %s Orders' % len(tiquetes))
			for indice, tiquete in enumerate(tiquetes):
				_logger.info('Validating Order %s / %s ' % (indice+1, len(tiquetes)))
				if not tiquete.eicr_documento_file:
					tiquete.eicr_state = 'na'
					pass
				self._enviar_documento(tiquete)

		if Expense is not None:
			gastos = Expense.search([('eicr_state', 'in', ('pendiente',))],
									limit=max_documentos).sorted(key=lambda e: e.reference)
			_logger.info('Validating %s Expenses' % len(gastos))
			for indice, gasto in enumerate(gastos):
				_logger.info('Validating Expense %s/%s %s' % (indice+1, len(gastos), gasto))
				if not gasto.eicr_documento2_file:
					gasto.eicr_state = 'na'
					pass
				elif not gasto.eicr_documento_file:
					xml = self.get_xml(gasto)
					if xml:
						gasto.eicr_documento_file = xml
						gasto.eicr_documento_fname = 'MensajeReceptor_' + gasto.eicr_clave + '.xml'
					else:
						gasto.eicr_state = 'na'
						pass
				self._enviar_documento(gasto)

		_logger.info('Valida - Finalizado Exitosamente')

	@api.model
	def _consultahacienda(self, max_documentos=4):  # cron

		Invoice = self.env['account.invoice'] if self.env['eicr.tools'].module_installed('eicr_invoicing') else None
		Order = self.env['pos.order'] if self.env['eicr.tools'].module_installed('eicr_pos') else None
		Expense = self.env['hr.expense'] if self.env['eicr.tools'].module_installed('eicr_expense') else None

		if Invoice is not None:
			facturas = Invoice.search([('type', 'in', ('out_invoice', 'out_refund','in_invoice')),
									   ('state', 'in', ('open', 'paid')),
									   ('eicr_state', 'in', ('recibido', 'procesando', 'error'))], limit=max_documentos)

			for indice, factura in enumerate(facturas):
				_logger.info('Consultando documento %s / %s ' % (indice+1, len(facturas)))
				if not factura.eicr_documento_file: pass
				if self._consultar_documento(factura): self._enviar_email(factura)
				max_documentos -= 1

		if Order is not None:
			tiquetes = Order.search([('eicr_state', 'in', ('recibido', 'procesando', 'error'))], limit=max_documentos)

			for indice, tiquete in enumerate(tiquetes):
				_logger.info('Consultando documento %s / %s ' % (indice+1, len(tiquetes)))
				if not tiquete.eicr_documento_file:
					pass
				if self._consultar_documento(tiquete):
					self._enviar_email(tiquete)
				max_documentos -= 1

		if Expense is not None:
			gastos = Expense.search([('eicr_state', 'in', ('recibido', 'procesando', 'error'))], limit=max_documentos)
			for indice, gasto in enumerate(gastos):
				_logger.info('Consultando documento %s / %s ' % (indice + 1, len(gastos)))
				if not gasto.eicr_documento_file:
					pass
				self._consultar_documento(gasto)
				max_documentos -= 1

		_logger.info('Consulta Hacienda - Finalizado Exitosamente')

	def get_info_contribuyente(self, identificacion=None):
		'''Obtiene la información del contribuyente'''
		if identificacion is None: identificacion = self.company_id.vat
		identificacion = re.sub('[^0-9]', '', identificacion or '')

		try:
			url = 'https://api.hacienda.go.cr/fe/ae'
			response = requests.get(url, params={'identificacion': identificacion})

		except requests.exceptions.RequestException as e:
			_logger.info('RequestException %s' % e)
			return False

		_logger.info('%s %s' % (response, response.__dict__))

		if response.status_code in (200,):
			_logger.info(response.json())
			return response.json()
		else:
			return False

	def get_actividades_economicas(self, identificacion=None):
		'''Obtiene las actividades económicas de la compañia'''

		info = self.get_info_contribuyente(identificacion)

		if info:
			return [x for x in info['actividades'] if x['estado'] == 'A']
		else:
			return False



