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
	_name = 'eicr.tools'

	@api.model
	def module_installed(self, name):
		module = self.env['ir.module.module'].search([('name', '=', name)], limit=1)
		return True if module and module.state == 'installed' else False

	@api.model
	def date_string(self, datetime=None):
		if datetime is None:
			now_utc = datetime.now(pytz.timezone('UTC'))
			datetime = now_utc.astimezone(pytz.timezone('America/Costa_Rica'))
		return datetime.strftime(EICR_DATE_FORMAT)

	@api.model
	def date_time(self, date_string=None):
		if date_string is None:
			date_string = self.date_string()
		return datetime.strptime(date_string,EICR_DATE_FORMAT)


	@api.model
	def actualizar_info(self, partner_id):
		info = self.get_info_contribuyente(partner_id.vat)
		if info:
			# tipo de identificación
			partner_id.identification_id = self.env['eicr.identification_type'].search([('code', '=', info['tipoIdentificacion'])])
			if info['tipoIdentificacion'] in ('01', '03', '04'):
				partner_id.is_company = False
			elif info['tipoIdentificacion'] in ('02'):
				partner_id.is_company = True
			# actividad económica
			actividades = [a['codigo'] for a in info['actividades'] if a['estado'] == 'A']
			partner_id.eicr_activity_ids = self.env['eicr.economic_activity'].search([('code', 'in', actividades)])
			# nombre
			if not partner_id.name or partner_id.name == 'My Company': partner_id.name = info['nombre']
			# régimen tributario
			partner_id.eicr_regimen = str(info['regimen']['codigo'])

	@api.model
	def validar_xml_proveedor(self, object):
		_logger.info('validando xml de proveedor para %s' % object)

		xml = base64.b64decode(object.eicr_documento2_file)
		xml = etree.tostring(etree.fromstring(xml)).decode()
		xml = re.sub(' xmlns="[^"]+"', '', xml)
		xml = etree.fromstring(xml)
		document = xml.tag

		if document not in ('FacturaElectronica', 'TiqueteElectronico'):
			message = 'El archivo xml debe ser una FacturaElectronica o TiqueteElectronico.\n%s es un documento inválido' % document
			_logger.info('%s %s' % (object, message))
			raise UserError(message)

		if (xml.find('Clave') is None or
			xml.find('FechaEmision') is None or
			xml.find('Emisor') is None or
			xml.find('Emisor').find('Identificacion') is None or
			xml.find('Emisor').find('Identificacion').find('Tipo') is None or
			xml.find('Emisor').find('Identificacion').find('Numero') is None or
			xml.find('Receptor') is None or
			xml.find('Receptor').find('Identificacion') is None or
			xml.find('Receptor').find('Identificacion').find('Tipo') is None or
			xml.find('Receptor').find('Identificacion').find('Numero') is None or
			xml.find('ResumenFactura') is None or
			xml.find('ResumenFactura').find('TotalComprobante') is None ):

			message = 'El archivo xml parece estar incompleto, no se puede procesar.\nDocumento %s' % document
			_logger.info('%s %s' % (object, message))
			raise UserError(message)

		return True


	@api.model
	def enviar_aceptacion(self, object):

		if not self._es_mensaje_aceptacion(object):
			_logger.info('%s no es documento aceptable por hacienda' % object)
			object.eicr_state = 'na'
			return False

		if not object.eicr_documento2_file:
			_logger.info('%s sin xml de proveedor' % object)
			object.eicr_state = 'na'
			return False

		if not object.eicr_documento_file:
			object.eicr_documento_file = self.get_xml(object)
			if object.eicr_documento_file:
				object.eicr_documento_fname = 'MensajeReceptor_' + object.number_electronic + '.xml'
				object.eicr_state = 'pendiente'
			else:
				object.eicr_state = 'na'



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

	def _es_mensaje_aceptacion(self, object):
		if object._name == 'account.invoice' and object.type in ('in_invoice', 'in_refund') \
			or object._name == 'hr.expense':
			return True
		else:
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

	def _fe_habilitado(self, company_id):
		return False if company_id.eicr_environment == 'disabled' else True

	def _get_consecutivo(self, object):
		# tipo de documento
		if object._name == 'account.invoice':
			receptor_valido = self._validar_receptor(object.partner_id)
			numeracion = object.number
			diario = object.journal_id
			tipo = '05'
			if object.type == 'out_invoice':
				tipo = '01'  # Factura Electrónica
				if object.company_id.eicr_version_id.name == 'v4.3' and not receptor_valido:
					tipo = '04' # Tiquete Electrónico
			elif object.type == 'out_refund' and object.amount_total_signed > 0:
				tipo = '02' # Nota Débito
			elif object.type == 'out_refund' and object.amount_total_signed <= 0:
				tipo = '03' # Nota Crédito
			elif object.type in ('in_invoice', 'in_refund'):
				if object.eicr_aceptacion == '1':
					tipo = '05' # Aceptado
				elif object.eicr_aceptacion == '2':
					tipo = '06' # Aceptado Parcialmente
				elif object.eicr_aceptacion == '3':
					tipo = '07' # Rechazado
		elif object._name == 'pos.order':
			numeracion = object.name
			diario = object.sale_journal
			tipo = '04'  # Tiquete Electrónico
		elif object._name == 'hr.expense':
			diario = self.env['account.journal'].search([('company_id', '=', object.company_id.id), ('type', '=', 'purchase')])
			if len(diario) > 1:
				diario = diario.sorted(key=lambda i: i.id)[0]
			numeracion = object.number or diario.sequence_id.next_by_id()
			_logger.info('%s %s' % (diario, numeracion))
			if object.eicr_aceptacion == '1' or object.eicr_aceptacion is None :
				tipo = '05'  # Aceptado
			elif object.eicr_aceptacion == '2':
				tipo = '06'  # Aceptado Parcialmente
			elif object.eicr_aceptacion == '3':
				tipo = '07'  # Rechazado
		else:
			return False

		# numeracion
		numeracion = re.sub('[^0-9]', '', numeracion)

		if len(numeracion) == 20:
			return numeracion
		elif len(numeracion) != 10:
			_logger.info('La numeración debe de tener 10 dígitos, revisar la secuencia de numeración.')
			return False

		# sucursal
		sucursal = re.sub('[^0-9]', '', str(diario.sucursal)).zfill(3)

		# terminal
		terminal = re.sub('[^0-9]', '', str(diario.terminal)).zfill(5)

		# consecutivo
		consecutivo = sucursal + terminal + tipo + numeracion

		if len(consecutivo) != 20:
			_logger.info('Algo anda mal con el consecutivo :( %s' % consecutivo)
			return False

		_logger.info('se genera el consecutivo %s para %s' % (consecutivo, object))

		return consecutivo

	def _get_clave(self, object):

		if (object._name == 'account.invoice' and object.type in ('in_invoice', 'in_refund')) \
			or object._name == 'hr.expense':
			return self._get_clave_de_xml(object.eicr_documento2_file)

		if object._name == 'account.invoice' and object.type in ('out_invoice', 'out_refund'):
			consecutivo = object.number

		if object._name == 'pos.order':
			consecutivo = object.name

		# f) consecutivo
		if len(consecutivo) != 20 or not consecutivo.isdigit():
			consecutivo = self._get_consecutivo(object)

		# a) código de pais
		codigo_de_pais = '506'

		# fecha
		fecha = datetime.strptime(object.fecha, '%Y-%m-%d %H:%M:%S')

		# b) día
		dia = fecha.strftime('%d')
		# c) mes
		mes = fecha.strftime('%m')
		# d) año
		anio = fecha.strftime('%y')

		# identificación
		identificacion = re.sub('[^0-9]', '', object.company_id.vat or '')

		if not object.company_id.identification_id:
			raise UserError('Seleccione el tipo de identificación del emisor en el perfil de la compañía')
		if object.company_id.identification_id.code == '01' and len(identificacion) != 9:
			raise UserError('La Cédula Física del emisor debe de tener 9 dígitos')
		elif object.company_id.identification_id.code == '02' and len(identificacion) != 10:
			raise UserError('La Cédula Jurídica del emisor debe de tener 10 dígitos')
		elif object.company_id.identification_id.code == '03' and not (
				len(identificacion) == 11 or len(identificacion) == 12):
			raise UserError('La identificación DIMEX del emisor debe de tener 11 o 12 dígitos')
		elif object.company_id.identification_id.code == '04' and len(identificacion) != 10:
			raise UserError('La identificación NITE del emisor debe de tener 10 dígitos')

		identificacion = identificacion.zfill(12)

		# g) situación
		situacion = '1'

		# h) código de seguridad
		codigo_de_seguridad = str(random.randint(1, 99999999)).zfill(8)

		# clave
		clave = codigo_de_pais + dia + mes + anio + identificacion + consecutivo + situacion + codigo_de_seguridad

		if len(clave) != 50:
			_logger.info('Algo anda mal con la clave :( %s' % clave)
			return False

		_logger.info('se genera la clave %s para %s' % (clave, object))
		return clave

	def _enviar_documento(self, object):

		if not self._fe_habilitado(object.company_id):
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

		if self._es_mensaje_aceptacion(object):
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

		if self._es_mensaje_aceptacion(object):
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

		if not self._fe_habilitado(object.company_id): return False

		if object.eicr_documento_file:
			xml = etree.tostring(etree.fromstring(base64.b64decode(object.eicr_documento_file))).decode()
			Documento = etree.fromstring(re.sub(' xmlns="[^"]+"', '', xml, count=1))
			clave = Documento.find('Clave').text
			if not object.eicr_date:
				object.eicr_date = self.date_time(Documento.find('FechaEmision').text)
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

		if self._es_mensaje_aceptacion(object):
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
			object.xml_eicr_mensaje_hacienda = respuesta['respuesta-xml']

			respuesta = etree.tostring(etree.fromstring(base64.b64decode(object.xml_eicr_mensaje_hacienda))).decode()
			respuesta = etree.fromstring(re.sub(' xmlns="[^"]+"', '', respuesta, count=1))
			object.eicr_mensaje_hacienda = respuesta.find('DetalleMensaje').text

		return True

	def _enviar_email(self, object):
		if object.eicr_state != 'aceptado':
			_logger.info('documento %s estado %s, no vamos a enviar el email' % (object, object.eicr_state))
			return False

		if not object.partner_id:
			_logger.info('documento %s sin cliente, no vamos a enviar el email' % object)
			return False

		if not object.partner_id.email:
			_logger.info('Cliente %s sin email, no vamos a enviar el email' % object.partner_id)
			return False

		if object._name == 'account.invoice' or object._name == 'hr.expense':
			email_template = self.env.ref('account.email_template_edi_invoice', False)
		if object._name == 'pos.order':
			email_template = self.env.ref('cr_pos_electronic_invoice.email_template_pos_invoice', False)

		comprobante = self.env['ir.attachment'].search(
			[('res_model', '=', object._name), ('res_id', '=', object.id),
			 ('res_field', '=', 'eicr_documento_file')], limit=1)
		comprobante.name = object.eicr_documento_fname
		comprobante.datas_fname = object.eicr_documento_fname

		attachments = comprobante

		if object.eicr_mensaje_hacienda_file:
			respuesta = self.env['ir.attachment'].search(
				[('res_model', '=', object._name), ('res_id', '=', object.id),
				 ('res_field', '=', 'eicr_mensaje_hacienda_file')], limit=1)
			respuesta.name = object.eicr_mensaje_hacienda_fname
			respuesta.datas_fname = object.eicr_mensaje_hacienda_fname

			attachments = attachments | respuesta

		email_template.attachment_ids = [(6, 0, attachments.mapped('id'))]

		email_to = object.partner_id.email_facturas or object.partner_id.email
		_logger.info('emailing to %s' % email_to)

		email_template.with_context(type='binary', default_type='binary').send_mail(object.id,
																					raise_exception=False,
																					force_send=True,
																					email_values={
																						'email_to': email_to})  # default_type='binary'

		email_template.attachment_ids = [(5)]

		if object._name == 'account.invoice': object.sent = True

	def _firmar_xml(self, xml, company_id):

		xml = base64.b64decode(xml).decode('utf-8')
		_logger.info('xml decoded %s' % xml)

		# directorio donde se encuentra el firmador de johann04 https://github.com/johann04/xades-signer-cr
		path = os.path.dirname(os.path.realpath(__file__))[:-6] + 'bin/'
		# nombres de archivos
		signer_filename = 'xadessignercr.jar'
		firma_filename = 'firma_%s.p12' % company_id.vat
		factura_filename = 'factura_%s.xml' % company_id.vat
		# El firmador es un ejecutable de java que necesita la firma y la factura en un archivo
		# 1) escribimos el xml de la factura en un archivo
		with open(path + factura_filename, 'w+') as file:
			file.write(xml)
		# 2) escribimos la firma en un archivo
		if not company_id.eicr_signature:
			raise UserError('Agregue la firma digital en el perfil de la compañía.')

		with open(path + firma_filename, 'w+b') as file:
			file.write(base64.b64decode(company_id.eicr_signature))
		# 3) firmamos el archivo con el signer
		subprocess.check_output(
			['java', '-jar', path + signer_filename, 'sign', path + firma_filename, company_id.eicr_pin,
			 path + factura_filename, path + factura_filename])
		# 4) leemos el archivo firmado
		with open(path + factura_filename, 'rb') as file:
			xml = file.read()

		xml_encoded = base64.b64encode(xml).decode('utf-8')
		return xml_encoded

	@api.model
	def _validahacienda(self, max_documentos=4):  # cron

		Invoice = self.env['account.invoice'] if self.module_installed('eicr_invoicing') else None
		Order = self.env['pos.order'] if self.module_installed('eicr_pos') else None
		Expense = self.env['hr.expense'] if self.module_installed('eicr_expense') else None

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

		Invoice = self.env['account.invoice'] if self.module_installed('eicr_invoicing') else None
		Order = self.env['pos.order'] if self.module_installed('eicr_pos') else None
		Expense = self.env['hr.expense'] if self.module_installed('eicr_expense') else None

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

	@api.model
	def _get_clave_de_xml(self, xml):
		try:
			xml = base64.b64decode(xml)
			Documento = etree.tostring(etree.fromstring(xml)).decode()
			Documento = etree.fromstring(re.sub(' xmlns="[^"]+"', '', Documento, count=1))
			Clave = Documento.find('Clave')
			return Clave.text
		except Exception as e:
			print('Error con % %' % (xml, e))
			return False

	@api.model
	def get_xml(self, object):
		object.ensure_one()
		if object._name == 'account.invoice':
			if object.type in ('out_invoice', 'out_refund'):
				if object.company_id.eicr_version_id.name == 'v4.2':
					Documento = self._get_xml_FE_NC_ND_42(object)
				elif object.company_id.eicr_version_id.name == 'v4.3':
					Documento = self._get_xml_FE_NC_ND_43(object)
			elif object.type in ('in_invoice', 'in_refund'):
				Documento = self._get_xml_MR_account_invoice(object)
		elif object._name == 'pos.order':
			Documento = self._get_xml_TE(object)
		elif object._name == 'hr.expense':
			Documento = self._get_xml_MR_hr_expense(object)

		if Documento is None or Documento is False:
			return False

		_logger.info ('Documento %s' % Documento)
		xml = etree.tostring(Documento, encoding='UTF-8', xml_declaration=True, pretty_print=True)
		xml_base64_encoded = base64.b64encode(xml).decode('utf-8')
		xml_base64_encoded_firmado = self._firmar_xml(xml_base64_encoded, object.company_id)

		return xml_base64_encoded_firmado

	@api.model
	def _get_xml_TE(self, order):

		if not order.name:
			_logger.error('Tiquete sin consecutivo %s' % order)
			return False

		if len(order.name) != 20:
			consecutivo = self._get_consecutivo(order)
			if not consecutivo:
				_logger.error('Error de consecutivo %s' % order.name)
				return False

			order.name = consecutivo

		if not order.number_electronic:
			clave = self._get_clave(order)
			if not clave:
				_logger.error('Error de clave %s' % order)
				return False

			order.number_electronic = clave

		if len(order.number_electronic) != 50:
			_logger.error('Error de clave %s' % order.number_electronic)
			return False

		emisor = order.company_id
		receptor = order.partner_id

		receptor_valido = self._validar_receptor(receptor)

		# TiqueteElectronico 4.3
		decimales = 2

		if receptor_valido:
			documento = 'FacturaElectronica'  # Factura Electrónica
			xmlns = 'https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.3/facturaElectronica'
			schemaLocation = 'https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.3/facturaElectronica  https://www.hacienda.go.cr/ATV/ComprobanteElectronico/docs/esquemas/2016/v4.3/FacturaElectronica_V4.3.xsd'
		else:
			documento = 'TiqueteElectronico'  # Tiquete Electrónico
			xmlns = 'https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.3/tiqueteElectronico'
			schemaLocation = 'https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.3/tiqueteElectronico  https://www.hacienda.go.cr/ATV/ComprobanteElectronico/docs/esquemas/2016/v4.3/TiqueteElectronico_V4.3.xsd'

		xsi = 'http://www.w3.org/2001/XMLSchema-instance'
		xsd = 'http://www.w3.org/2001/XMLSchema'
		ds = 'http://www.w3.org/2000/09/xmldsig#'

		nsmap = {None : xmlns, 'xsd': xsd, 'xsi': xsi, 'ds': ds}
		attrib = {'{'+xsi+'}schemaLocation':schemaLocation}

		Documento = etree.Element(documento, attrib=attrib, nsmap=nsmap)

		# Clave
		Clave = etree.Element('Clave')
		Clave.text = order.number_electronic
		Documento.append(Clave)

		# CodigoActividad
		CodigoActividad = etree.Element('CodigoActividad')
		CodigoActividad.text = order.company_id.eicr_activity_ids[0].code
		Documento.append(CodigoActividad)

		# NumeroConsecutivo
		NumeroConsecutivo = etree.Element('NumeroConsecutivo')
		NumeroConsecutivo.text = order.name # order.name
		Documento.append(NumeroConsecutivo)

		# FechaEmision
		FechaEmision = etree.Element('FechaEmision')
		FechaEmision.text = datetime.strptime(order.fecha, '%Y-%m-%d %H:%M:%S').strftime("%Y-%m-%dT%H:%M:%S")
		Documento.append(FechaEmision)

		# Emisor
		Emisor = etree.Element('Emisor')

		Nombre = etree.Element('Nombre')
		Nombre.text = emisor.name
		Emisor.append(Nombre)

		identificacion = re.sub('[^0-9]', '', emisor.vat or '')

		if not emisor.identification_id:
			raise UserError('Seleccione el tipo de identificación del emisor en el perfil de la compañía')
		elif emisor.identification_id.code == '01' and len(identificacion) != 9:
			raise UserError('La Cédula Física del emisor debe de tener 9 dígitos')
		elif emisor.identification_id.code == '02' and len(identificacion) != 10:
			raise UserError('La Cédula Jurídica del emisor debe de tener 10 dígitos')
		elif emisor.identification_id.code == '03' and not (len(identificacion) == 11 or len(identificacion) == 12):
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
		if not emisor.street:
			raise UserError('La dirección del emisor está incompleta, no se han digitado las señas de la dirección')

		Ubicacion = etree.Element('Ubicacion')

		Provincia = etree.Element('Provincia')
		Provincia.text = emisor.partner_id.state_id.code # state_id.code
		Ubicacion.append(Provincia)

		Canton = etree.Element('Canton')
		Canton.text = emisor.county_id.code # county_id.code
		Ubicacion.append(Canton)

		Distrito = etree.Element('Distrito')
		Distrito.text = emisor.district_id.code # district_id.code
		Ubicacion.append(Distrito)

		if emisor.partner_id.neighborhood_id and emisor.partner_id.neighborhood_id.code:
			Barrio = etree.Element('Barrio')
			Barrio.text = emisor.neighborhood_id.code # neighborhood_id.code
			Ubicacion.append(Barrio)

		OtrasSenas = etree.Element('OtrasSenas')
		OtrasSenas.text = emisor.street or 'Sin otras señas' # emisor.street
		Ubicacion.append(OtrasSenas)

		Emisor.append(Ubicacion)

		telefono = emisor.partner_id.phone or emisor.partner_id.mobile
		if telefono:
			telefono = re.sub('[^0-9]', '', telefono)
			if telefono and len(telefono) >= 8 and len(telefono) <= 20:
				Telefono = etree.Element('Telefono')

				CodigoPais = etree.Element('CodigoPais')
				CodigoPais.text = '506' # '506'
				Telefono.append(CodigoPais)

				NumTelefono = etree.Element('NumTelefono')
				NumTelefono.text = telefono[:8] # telefono

				Telefono.append(NumTelefono)

				Emisor.append(Telefono)

		if not emisor.email or not re.match('^[(a-z0-9\_\-\.)]+@[(a-z0-9\_\-\.)]+\.[(a-z)]{2,15}$', emisor.email.lower()):
			raise UserError('El correo electrónico del emisor es inválido.')

		CorreoElectronico = etree.Element('CorreoElectronico')
		CorreoElectronico.text = emisor.email.lower() # emisor.email
		Emisor.append(CorreoElectronico)

		Documento.append(Emisor)

		# Receptor
		if receptor_valido:

			Receptor = etree.Element('Receptor')

			Nombre = etree.Element('Nombre')
			Nombre.text = receptor.name
			Receptor.append(Nombre)

			identificacion = re.sub('[^0-9]', '', receptor.vat)

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

				if receptor.neighborhood_id:
					Barrio = etree.Element('Barrio')
					Barrio.text = receptor.neighborhood_id.code
					Ubicacion.append(Barrio)

				OtrasSenas = etree.Element('OtrasSenas')
				OtrasSenas.text = receptor.street
				Ubicacion.append(OtrasSenas)

				Receptor.append(Ubicacion)

			telefono = receptor.phone or receptor.mobile
			if telefono:
				telefono = re.sub('[^0-9]', '', telefono)
				if telefono and len(telefono) >= 8 and len(telefono) <= 20:
					Telefono = etree.Element('Telefono')

					CodigoPais = etree.Element('CodigoPais')
					CodigoPais.text = '506'
					Telefono.append(CodigoPais)

					NumTelefono = etree.Element('NumTelefono')
					NumTelefono.text = telefono[:8]
					Telefono.append(NumTelefono)

					Receptor.append(Telefono)

			if receptor.email and re.match('^[(a-z0-9\_\-\.)]+@[(a-z0-9\_\-\.)]+\.[(a-z)]{2,15}$', receptor.email.lower()):
				CorreoElectronico = etree.Element('CorreoElectronico')
				CorreoElectronico.text = receptor.email
				Receptor.append(CorreoElectronico)

			Documento.append(Receptor)


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
		servicio = True if impuestoServicio in order.lines.mapped('tax_ids_after_fiscal_position') else False

		indice = 1
		for linea in order.lines:

			LineaDetalle = etree.Element('LineaDetalle')

			NumeroLinea = etree.Element('NumeroLinea')
			NumeroLinea.text = '%s' % indice # indice + 1
			LineaDetalle.append(NumeroLinea)

			if linea.product_id.default_code:
				CodigoComercial = etree.Element('CodigoComercial')

				Tipo = etree.Element('Tipo')
				Tipo.text = '04' # Código de uso interno
				CodigoComercial.append(Tipo)

				Codigo = etree.Element('Codigo')
				Codigo.text = linea.product_id.default_code
				CodigoComercial.append(Codigo)

				LineaDetalle.append(CodigoComercial)

			Cantidad = etree.Element('Cantidad')
			Cantidad.text = str(linea.qty) # linea.qty
			LineaDetalle.append(Cantidad)

			UnidadMedida = etree.Element('UnidadMedida')
			UnidadMedida.text = 'Sp' if (linea.product_id and linea.product_id.type == 'service') else 'Unid'

			LineaDetalle.append(UnidadMedida)

			Detalle = etree.Element('Detalle')
			Detalle.text = linea.product_id.product_tmpl_id.name # product_tmpl_id.name
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
				LineaDetalle.append(MontoDescuento)

				NaturalezaDescuento = etree.Element('NaturalezaDescuento')
				NaturalezaDescuento.text =  'Descuento Comercial'
				LineaDetalle.append(NaturalezaDescuento)

			SubTotal = etree.Element('SubTotal')
			SubTotal.text = str(round(linea.price_subtotal, decimales))
			LineaDetalle.append(SubTotal)

			if linea.tax_ids_after_fiscal_position:
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
			MontoCargo.text = str(round((order.amount_total - order.amount_tax) * 10.0 / 100.0, decimales))
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
			TotalMercanciasGravadas.text = str(round(totalMercanciasGravadas + totalDescuentosMercanciasGravadas, decimales))
			ResumenFactura.append(TotalMercanciasGravadas)

		if totalMercanciasExentas:
			TotalMercanciasExentas = etree.Element('TotalMercanciasExentas')
			TotalMercanciasExentas.text = str(round(totalMercanciasExentas + totalDescuentosMercanciasExentas, decimales))
			ResumenFactura.append(TotalMercanciasExentas)

		if totalServiciosGravados + totalMercanciasGravadas:
			TotalGravado = etree.Element('TotalGravado')
			TotalGravado.text = str(round(totalServiciosGravados + totalDescuentosServiciosGravados + totalMercanciasGravadas + totalDescuentosMercanciasGravadas, decimales))
			ResumenFactura.append(TotalGravado)

		if totalServiciosExentos + totalMercanciasExentas:
			TotalExento = etree.Element('TotalExento')
			TotalExento.text = str(round(totalServiciosExentos + totalDescuentosServiciosExentos + totalMercanciasExentas + totalDescuentosMercanciasExentas, decimales))
			ResumenFactura.append(TotalExento)

		TotalVenta = etree.Element('TotalVenta')
		_logger.info('total %s tax %s' % (order.amount_total, order.amount_tax))
		totalVenta = order.amount_total - order.amount_tax
		totalVenta += totalDescuentosServiciosGravados + totalDescuentosMercanciasGravadas + totalDescuentosServiciosExentos + totalDescuentosMercanciasExentas

		TotalVenta.text = str(round(totalVenta, decimales))
		ResumenFactura.append(TotalVenta)

		if totalDescuentosServiciosGravados + totalDescuentosMercanciasGravadas + totalDescuentosServiciosExentos + totalDescuentosMercanciasExentas:
			TotalDescuentos = etree.Element('TotalDescuentos')
			TotalDescuentos.text = str(round(totalDescuentosServiciosGravados + totalDescuentosMercanciasGravadas + totalDescuentosServiciosExentos + totalDescuentosMercanciasExentas, decimales))
			ResumenFactura.append(TotalDescuentos)

		TotalVentaNeta = etree.Element('TotalVentaNeta')
		totalVentaNeta = order.amount_total - order.amount_tax

		TotalVentaNeta.text = str(round(totalVentaNeta, decimales))
		ResumenFactura.append(TotalVentaNeta)

		if order.amount_tax:
			TotalImpuesto = etree.Element('TotalImpuesto')
			TotalImpuesto.text = str(round(totalImpuesto, decimales))
			ResumenFactura.append(TotalImpuesto)

		if servicio:
			TotalOtrosCargos = etree.Element('TotalOtrosCargos')
			TotalOtrosCargos.text = str(round((order.amount_total - order.amount_tax) * 10.0 / 100.0, decimales))
			ResumenFactura.append(TotalOtrosCargos)

		TotalComprobante = etree.Element('TotalComprobante')
		TotalComprobante.text = str(round(order.amount_total, decimales))
		ResumenFactura.append(TotalComprobante)

		Documento.append(ResumenFactura)

		return Documento

	def _get_xml_MR_hr_expense(self, expense):
		expense.number = self._get_consecutivo(expense)
		return  self._get_xml_MR(expense, expense.number)

	def _get_xml_MR_account_invoice(self, invoice):
		if not invoice.number:
			_logger.error('Factura sin consecutivo %s', invoice)
			return False

		if not invoice.number.isdigit():
			_logger.error('Error de numeración %s', invoice.number)
			return False

		if len(invoice.number) != 20:
			consecutivo = self._get_consecutivo(invoice)
			if not consecutivo:
				_logger.error('Error de consecutivo %s' % invoice.number)
				return False

			invoice.number = consecutivo
		return  self._get_xml_MR(invoice, invoice.number)


	def _validar_receptor(self, partner_id):
		if not partner_id: return False
		if not partner_id.identification_id or not partner_id.vat: return False

		identificacion = re.sub('[^0-9]', '', partner_id.vat)

		if partner_id.identification_id.code == '01' and len(identificacion) != 9:
			return False
		elif partner_id.identification_id.code == '02' and len(identificacion) != 10:
			return False
		elif partner_id.identification_id.code == '03' and not (len(identificacion) == 11 or len(identificacion) == 12):
			return False
		elif partner_id.identification_id.code == '04' and len(identificacion) != 10:
			return False
		elif partner_id.identification_id.code == '05':
			return False

		return True


	def _get_xml_FE_NC_ND_43(self, invoice):

		if invoice.type not in ('out_invoice', 'out_refund'):
			_logger.error('No es factura de cliente %s', invoice)
			return False

		if not invoice.number:
			_logger.error('Factura sin consecutivo %s', invoice)
			return False

		if not invoice.number.isdigit():
			_logger.error('Error de numeración %s', invoice.number)
			return False

		if len(invoice.number) != 20:
			consecutivo = self._get_consecutivo(invoice)
			if not consecutivo:
				_logger.error('Error de consecutivo %s' % invoice.number)
				return False

			invoice.number = consecutivo

		if not invoice.number_electronic:
			clave = self._get_clave(invoice)
			if not clave:
				_logger.error('Error de clave %s' % invoice)
				return False

			invoice.number_electronic = clave

		if len(invoice.number_electronic) != 50:
			_logger.error('Error de clave %s' % invoice.number_electronic)
			return False

		emisor = invoice.company_id
		receptor = invoice.partner_id

		receptor_valido = self._validar_receptor(receptor)

		# FacturaElectronica 4.3 y Nota de Crédito 4.3
		decimales = 2

		if invoice.type == 'out_invoice':
			if receptor_valido:
				documento = 'FacturaElectronica' # Factura Electrónica
				xmlns = 'https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.3/facturaElectronica'
				schemaLocation = 'https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.3/facturaElectronica  https://www.hacienda.go.cr/ATV/ComprobanteElectronico/docs/esquemas/2016/v4.3/FacturaElectronica_V4.3.xsd'
			else:
				documento = 'TiqueteElectronico'  # Tiquete Electrónico
				xmlns = 'https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.3/tiqueteElectronico'
				schemaLocation = 'https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.3/tiqueteElectronico  https://www.hacienda.go.cr/ATV/ComprobanteElectronico/docs/esquemas/2016/v4.3/TiqueteElectronico_V4.3.xsd'

		elif invoice.type == 'out_refund':
			documento = 'NotaCreditoElectronica' # Nota de Crédito
			xmlns = 'https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.3/notaCreditoElectronica'
			schemaLocation = 'https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.3/notaCreditoElectronica  https://www.hacienda.go.cr/ATV/ComprobanteElectronico/docs/esquemas/2016/v4.3/NotaCreditoElectronica_V4.3.xsd'
		else:
			_logger.info('tipo de documento no implementado %s' % invoice.type)
			return False

		xsi = 'http://www.w3.org/2001/XMLSchema-instance'
		xsd = 'http://www.w3.org/2001/XMLSchema'
		ds = 'http://www.w3.org/2000/09/xmldsig#'

		nsmap = {None : xmlns, 'xsd': xsd, 'xsi': xsi, 'ds': ds}
		attrib = {'{'+xsi+'}schemaLocation':schemaLocation}

		Documento = etree.Element(documento, attrib=attrib, nsmap=nsmap)

		# Clave
		Clave = etree.Element('Clave')
		Clave.text = invoice.number_electronic
		Documento.append(Clave)

		# CodigoActividad
		CodigoActividad = etree.Element('CodigoActividad')
		CodigoActividad.text = invoice.company_id.eicr_activity_ids[0].code
		Documento.append(CodigoActividad)

		# NumeroConsecutivo
		NumeroConsecutivo = etree.Element('NumeroConsecutivo')
		NumeroConsecutivo.text = invoice.number
		Documento.append(NumeroConsecutivo)

		# FechaEmision
		FechaEmision = etree.Element('FechaEmision')
		FechaEmision.text = datetime.strptime(invoice.fecha, '%Y-%m-%d %H:%M:%S').strftime("%Y-%m-%dT%H:%M:%S")
		Documento.append(FechaEmision)

		# Emisor
		Emisor = etree.Element('Emisor')

		Nombre = etree.Element('Nombre')
		Nombre.text = emisor.name
		Emisor.append(Nombre)

		identificacion = re.sub('[^0-9]', '', emisor.vat or '')

		if not emisor.identification_id:
			raise UserError('Seleccione el tipo de identificación del emisor en el perfil de la compañía')
		elif emisor.identification_id.code == '01' and len(identificacion) != 9:
			raise UserError('La Cédula Física del emisor debe de tener 9 dígitos')
		elif emisor.identification_id.code == '02' and len(identificacion) != 10:
			raise UserError('La Cédula Jurídica del emisor debe de tener 10 dígitos')
		elif emisor.identification_id.code == '03' and not (len(identificacion) == 11 or len(identificacion) == 12):
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
		if not emisor.street:
			raise UserError('La dirección del emisor está incompleta, no se han digitado las señas de la dirección')

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
		OtrasSenas.text = emisor.street or 'Sin otras señas'
		Ubicacion.append(OtrasSenas)

		Emisor.append(Ubicacion)

		telefono = emisor.partner_id.phone or emisor.partner_id.mobile
		if telefono:
			telefono = re.sub('[^0-9]', '', telefono)
			if telefono and len(telefono) >= 8 and len(telefono) <= 20:
				Telefono = etree.Element('Telefono')

				CodigoPais = etree.Element('CodigoPais')
				CodigoPais.text = '506'
				Telefono.append(CodigoPais)

				NumTelefono = etree.Element('NumTelefono')
				NumTelefono.text = telefono[:8]

				Telefono.append(NumTelefono)

				Emisor.append(Telefono)

		if not emisor.email or not re.match('^[(a-z0-9\_\-\.)]+@[(a-z0-9\_\-\.)]+\.[(a-z)]{2,15}$', emisor.email.lower()):
			raise UserError('El correo electrónico del emisor es inválido.')

		CorreoElectronico = etree.Element('CorreoElectronico')
		CorreoElectronico.text = emisor.email.lower()
		Emisor.append(CorreoElectronico)

		Documento.append(Emisor)

		# Receptor
		if receptor_valido:

			Receptor = etree.Element('Receptor')

			Nombre = etree.Element('Nombre')
			Nombre.text = receptor.name
			Receptor.append(Nombre)

			identificacion = re.sub('[^0-9]', '', receptor.vat)

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

				if receptor.neighborhood_id:
					Barrio = etree.Element('Barrio')
					Barrio.text = receptor.neighborhood_id.code
					Ubicacion.append(Barrio)

				OtrasSenas = etree.Element('OtrasSenas')
				OtrasSenas.text = receptor.street
				Ubicacion.append(OtrasSenas)

				Receptor.append(Ubicacion)

			telefono = receptor.phone or receptor.mobile
			if telefono:
				telefono = re.sub('[^0-9]', '', telefono)
				if telefono and len(telefono) >= 8 and len(telefono) <= 20:
					Telefono = etree.Element('Telefono')

					CodigoPais = etree.Element('CodigoPais')
					CodigoPais.text = '506'
					Telefono.append(CodigoPais)

					NumTelefono = etree.Element('NumTelefono')
					NumTelefono.text = telefono[:8]
					Telefono.append(NumTelefono)

					Receptor.append(Telefono)

			if receptor.email and re.match('^[(a-z0-9\_\-\.)]+@[(a-z0-9\_\-\.)]+\.[(a-z)]{2,15}$', receptor.email.lower()):
				CorreoElectronico = etree.Element('CorreoElectronico')
				CorreoElectronico.text = receptor.email
				Receptor.append(CorreoElectronico)

			Documento.append(Receptor)

		# Condicion Venta
		CondicionVenta = etree.Element('CondicionVenta')
		if invoice.payment_term_id:
			CondicionVenta.text = '02'
			Documento.append(CondicionVenta)

			PlazoCredito = etree.Element('PlazoCredito')
			timedelta(7)
			fecha_de_factura = datetime.strptime(invoice.date_invoice, '%Y-%m-%d')
			fecha_de_vencimiento = datetime.strptime(invoice.date_due, '%Y-%m-%d')
			PlazoCredito.text = str((fecha_de_factura - fecha_de_vencimiento).days)
			Documento.append(PlazoCredito)
		else:
			CondicionVenta.text = '01'
			Documento.append(CondicionVenta)

		# MedioPago
		MedioPago = etree.Element('MedioPago')
		MedioPago.text = invoice.payment_methods_id.code if invoice.payment_methods_id else '01'
		Documento.append(MedioPago)

		# DetalleServicio
		DetalleServicio = etree.Element('DetalleServicio')

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

		for indice, linea in enumerate(invoice.invoice_line_ids.sorted(lambda l: l.code)):
			LineaDetalle = etree.Element('LineaDetalle')

			NumeroLinea = etree.Element('NumeroLinea')
			NumeroLinea.text = '%s' % (indice + 1)
			LineaDetalle.append(NumeroLinea)

			if linea.product_id.default_code:
				CodigoComercial = etree.Element('CodigoComercial')

				Tipo = etree.Element('Tipo')
				Tipo.text = '04' # Código de uso interno
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
				NaturalezaDescuento.text = linea.discount_note or 'Descuento Comercial'
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
						if invoice.payment_methods_id.code == '02':
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
			MontoTotalLinea.text = str(round(linea.price_total+ivaDevuelto, decimales))
			LineaDetalle.append(MontoTotalLinea)

			DetalleServicio.append(LineaDetalle)

			totalIVADevuelto += ivaDevuelto

		Documento.append(DetalleServicio)

		# ResumenFactura
		ResumenFactura = etree.Element('ResumenFactura')

		if invoice.currency_id.name != 'CRC':
			CodigoTipoMoneda = etree.Element('CodigoTipoMoneda')

			CodigoMoneda = etree.Element('CodigoMoneda')
			CodigoMoneda.text = invoice.currency_id.name
			CodigoTipoMoneda.append(CodigoMoneda)

			TipoCambio = etree.Element('TipoCambio')
			TipoCambio.text = str(round(1.0 / invoice.currency_id.rate, decimales))
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
			TotalMercanciasGravadas.text = str(round(totalMercanciasGravadas + totalDescuentosMercanciasGravadas, decimales))
			ResumenFactura.append(TotalMercanciasGravadas)

		if totalMercanciasExentas:
			TotalMercanciasExentas = etree.Element('TotalMercanciasExentas')
			TotalMercanciasExentas.text = str(round(totalMercanciasExentas + totalDescuentosMercanciasExentas, decimales))
			ResumenFactura.append(TotalMercanciasExentas)

		if totalServiciosGravados + totalMercanciasGravadas:
			TotalGravado = etree.Element('TotalGravado')
			TotalGravado.text = str(round(totalServiciosGravados + totalDescuentosServiciosGravados + totalMercanciasGravadas + totalDescuentosMercanciasGravadas, decimales))
			ResumenFactura.append(TotalGravado)

		if totalServiciosExentos + totalMercanciasExentas:
			TotalExento = etree.Element('TotalExento')
			TotalExento.text = str(round(totalServiciosExentos + totalDescuentosServiciosExentos + totalMercanciasExentas + totalDescuentosMercanciasExentas, decimales))
			ResumenFactura.append(TotalExento)

		TotalVenta = etree.Element('TotalVenta')
		TotalVenta.text = str(round(invoice.amount_untaxed + totalDescuentosServiciosGravados + totalDescuentosMercanciasGravadas + totalDescuentosServiciosExentos + totalDescuentosMercanciasExentas, decimales))
		ResumenFactura.append(TotalVenta)

		if totalDescuentosServiciosGravados + totalDescuentosMercanciasGravadas + totalDescuentosServiciosExentos + totalDescuentosMercanciasExentas:
			TotalDescuentos = etree.Element('TotalDescuentos')
			TotalDescuentos.text = str(round(totalDescuentosServiciosGravados + totalDescuentosMercanciasGravadas + totalDescuentosServiciosExentos + totalDescuentosMercanciasExentas, decimales))
			ResumenFactura.append(TotalDescuentos)

		TotalVentaNeta = etree.Element('TotalVentaNeta')
		TotalVentaNeta.text = str(round(invoice.amount_untaxed, decimales))
		ResumenFactura.append(TotalVentaNeta)

		if totalImpuesto:
			TotalImpuesto = etree.Element('TotalImpuesto')
			# TotalImpuesto.text = str(round(invoice.amount_tax, decimales))
			TotalImpuesto.text = str(round(totalImpuesto, decimales))
			ResumenFactura.append(TotalImpuesto)

			if totalIVADevuelto:
				TotalIVADevuelto = etree.Element('TotalIVADevuelto')
				TotalIVADevuelto.text = str(round(totalIVADevuelto, decimales))
				ResumenFactura.append(TotalIVADevuelto)


		TotalComprobante = etree.Element('TotalComprobante')
		TotalComprobante.text = str(round(invoice.amount_total, decimales))
		ResumenFactura.append(TotalComprobante)

		Documento.append(ResumenFactura)

		if invoice.type == 'out_refund':

			if invoice.refund_invoice_id.type == 'out_invoice':
				tipo = '01'
			elif invoice.refund_invoice_id.type == 'out_refund':
				tipo = '03'

			InformacionReferencia = etree.Element('InformacionReferencia')

			TipoDoc = etree.Element('TipoDoc')
			TipoDoc.text = tipo
			InformacionReferencia.append(TipoDoc)

			Numero = etree.Element('Numero')
			Numero.text = invoice.refund_invoice_id.number_electronic or invoice.refund_invoice_id.number
			InformacionReferencia.append(Numero)

			FechaEmision = etree.Element('FechaEmision')
			if not invoice.refund_invoice_id.eicr_date:
				invoice.refund_invoice_id.eicr_date = self.date_time()

			FechaEmision.text = self.date_string(invoice.refund_invoice_id.eicr_date)
			InformacionReferencia.append(FechaEmision)

			Codigo = etree.Element('Codigo')
			Codigo.text = invoice.reference_code_id.code
			InformacionReferencia.append(Codigo)

			Razon = etree.Element('Razon')
			Razon.text = invoice.name or 'Error en Factura'
			InformacionReferencia.append(Razon)

			Documento.append(InformacionReferencia)

		return Documento

	def _get_xml_MR_hr_expense(self, expense):
		expense.number = self._get_consecutivo(expense)
		return  self._get_xml_MR(expense, expense.number)

	def _get_xml_MR_account_invoice(self, invoice):
		if not invoice.number:
			_logger.error('Factura sin consecutivo %s', invoice)
			return False

		if not invoice.number.isdigit():
			_logger.error('Error de numeración %s', invoice.number)
			return False

		if len(invoice.number) != 20:
			consecutivo = self._get_consecutivo(invoice)
			if not consecutivo:
				_logger.error('Error de consecutivo %s' % invoice.number)
				return False

			invoice.number = consecutivo
		return  self._get_xml_MR(invoice, invoice.number)

	def _get_xml_MR(self, object, consecutivo):
		xml = base64.b64decode(object.eicr_documento2_file)
		_logger.info('xml %s' % xml)

		factura = etree.tostring(etree.fromstring(xml)).decode()

		if not self.validar_xml_proveedor(object):
			return False


		factura = etree.fromstring(re.sub(' xmlns="[^"]+"', '', factura, count=1))

		Emisor = factura.find('Emisor')
		Receptor = factura.find('Receptor')
		TotalImpuesto = factura.find('ResumenFactura').find('TotalImpuesto')
		TotalComprobante = factura.find('ResumenFactura').find('TotalComprobante')

		emisor = self.env.user.company_id

		# MensajeReceptor 4.3

		documento = 'MensajeReceptor'  # MensajeReceptor
		xmlns = 'https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.3/mensajeReceptor'
		schemaLocation = 'https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.3/mensajeReceptor  https://www.hacienda.go.cr/ATV/ComprobanteElectronico/docs/esquemas/2016/v4.3/MensajeReceptor_V4.3.xsd'

		xsi = 'http://www.w3.org/2001/XMLSchema-instance'
		xsd = 'http://www.w3.org/2001/XMLSchema'
		ds = 'http://www.w3.org/2000/09/xmldsig#'

		nsmap = {None: xmlns, 'xsd': xsd, 'xsi': xsi, 'ds': ds}
		attrib = {'{' + xsi + '}schemaLocation': schemaLocation}

		Documento = etree.Element(documento, attrib=attrib, nsmap=nsmap)

		# Clave
		Clave = etree.Element('Clave')
		Clave.text = factura.find('Clave').text
		object.number_electronic = Clave.text
		Documento.append(Clave)

		# NumeroCedulaEmisor
		NumeroCedulaEmisor = etree.Element('NumeroCedulaEmisor')
		NumeroCedulaEmisor.text = factura.find('Emisor').find('Identificacion').find('Numero').text
		Documento.append(NumeroCedulaEmisor)

		object.eicr_date = self.date_time()

		# FechaEmisionDoc
		FechaEmisionDoc = etree.Element('FechaEmisionDoc')
		FechaEmisionDoc.text = date_cr  # date_cr
		Documento.append(FechaEmisionDoc)

		# Mensaje
		Mensaje = etree.Element('Mensaje')
		Mensaje.text = object.eicr_aceptacion or '01'  # eicr_aceptacion
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
				CodigoActividad.text = object.company_id.eicr_activity_ids[0].code
				Documento.append(CodigoActividad)

				# CondicionImpuesto
				if not object.eicr_credito_iva_condicion: object.eicr_credito_iva_condicion = self.env.ref('cr_electronic_invoice.CreditConditions_1')
				CondicionImpuesto = etree.Element('CondicionImpuesto')
				CondicionImpuesto.text = object.eicr_credito_iva_condicion.code
				Documento.append(CondicionImpuesto)

				# MontoTotalImpuestoAcreditar
				if not object.eicr_credito_iva:
					object.eicr_credito_iva = 100.0
				MontoTotalImpuestoAcreditar = etree.Element('MontoTotalImpuestoAcreditar')
				montoTotalImpuestoAcreditar = float(TotalImpuesto.text) * object.eicr_credito_iva / 100.0
				MontoTotalImpuestoAcreditar.text = str(round(montoTotalImpuestoAcreditar, 2))
				Documento.append(MontoTotalImpuestoAcreditar)


		# TotalFactura
		TotalFactura = etree.Element('TotalFactura')
		TotalFactura.text = TotalComprobante.text  # TotalComprobante.text
		Documento.append(TotalFactura)

		identificacion = re.sub('[^0-9]', '', emisor.vat or '')

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

		# NumeroCedulaReceptor
		NumeroCedulaReceptor = etree.Element('NumeroCedulaReceptor')
		NumeroCedulaReceptor.text = identificacion
		Documento.append(NumeroCedulaReceptor)

		# NumeroConsecutivoReceptor
		NumeroConsecutivoReceptor = etree.Element('NumeroConsecutivoReceptor')
		NumeroConsecutivoReceptor.text = consecutivo
		Documento.append(NumeroConsecutivoReceptor)

		return Documento

	def _process_supplier_invoice(self, invoice):

		xml = etree.fromstring(base64.b64decode(invoice.eicr_documento2_file))
		namespace = xml.nsmap[None]
		xml = etree.tostring(xml).decode()
		xml = re.sub(' xmlns="[^"]+"', '', xml)
		xml = etree.fromstring(xml)
		document = xml.tag

		v42 = 'https://tribunet.hacienda.go.cr/docs/esquemas/2017/v4.2/facturaElectronica'
		v43 = 'https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.3/facturaElectronica'

		if document != 'FacturaElectronica':
			return {'value': {'eicr_documento2_file': False},
					'warning': {'title': 'Atención', 'message': 'El archivo xml no es una Factura Electrónica.'}}

		if not (namespace == v42 or namespace == v43):
			return {'value': {'eicr_documento2_file': False},
					'warning': {'title': 'Atención',
								'message': 'Versión de Factura Electrónica no soportada.\n%s' % namespace}}

		if (xml.find('Clave') is None or
			xml.find('FechaEmision') is None or
			xml.find('Emisor') is None or
			xml.find('Emisor').find('Identificacion') is None or
			xml.find('Emisor').find('Identificacion').find('Tipo') is None or
			xml.find('Emisor').find('Identificacion').find('Numero') is None or
			xml.find('Receptor') is None or
			xml.find('Receptor').find('Identificacion') is None or
			xml.find('Receptor').find('Identificacion').find('Tipo') is None or
			xml.find('Receptor').find('Identificacion').find('Numero') is None or
			xml.find('ResumenFactura') is None or
			xml.find('ResumenFactura').find('TotalComprobante') is None ):
			return {'value': {'eicr_documento2_file': False},
					'warning': {'title': 'Atención', 'message': 'El xml parece estar incompleto.'}}

		if namespace == v42:
			return self._proccess_supplier_invoicev42(invoice, xml)
		elif namespace == v43:
			return self._proccess_supplier_invoicev43(invoice, xml)
		else:
			return {'value': {'eicr_documento2_file': False},
					'warning': {'title': 'Atención',
								'message': 'Versión de Factura Electrónica no soportada.\n%s' % namespace}}

	def _proccess_supplier_invoicev42(self, invoice, xml):

		NumeroConsecutivo = xml.find('NumeroConsecutivo')
		Emisor = xml.find('Emisor')

		PlazoCredito = xml.find('PlazoCredito')

		emisor_vat = Emisor.find('Identificacion').find('Numero').text
		emisor_tipo = Emisor.find('Identificacion').find('Tipo').text

		supplier = self.env['res.partner'].search([('vat', '=', emisor_vat)])

		if not supplier:
			ctx = self.env.context.copy()
			ctx.pop('default_type', False)
			tipo = self.env['identification.type'].search([('code', '=', emisor_tipo)])

			is_company = True if tipo.code == '02' else False

			phone_code = ''
			if Emisor.find('Telefono') and Emisor.find('Telefono').find('CodigoPais'):
				phone_code = Emisor.find('Telefono').find('CodigoPais').text

			phone = ''
			if Emisor.find('Telefono') and Emisor.find('Telefono').find('NumTelefono'):
				phone = Emisor.find('Telefono').find('NumTelefono').text

			email = Emisor.find('CorreoElectronico').text
			name = Emisor.find('Nombre').text

			supplier = self.env['res.partner'].with_context(ctx).create({'name': name,
																		  'email': email,
																		  'phone_code': phone_code,
																		  'phone': phone,
																		  'vat': emisor_vat,
																		  'identification_id': tipo.id,
																		  'is_company': is_company,
																		  'customer': False,
																		  'supplier': True})
			_logger.info('nuevo proveedor %s' % supplier)

		invoice.partner_id = supplier
		invoice.date_invoice = xml.find('FechaEmision').text

		invoice.reference = NumeroConsecutivo.text

		if xml.find('CondicionVenta').text == '02':  # crédito
			fecha_de_factura = datetime.strptime(invoice.date_invoice, '%Y-%m-%d')
			plazo = 0
			try:
				plazo = int(re.sub('[^0-9]', '', PlazoCredito.text))
			except TypeError:
				_logger.info('%s no es un número' % PlazoCredito.text)
			fecha_de_vencimiento = fecha_de_factura + timedelta(days=plazo)
			invoice.date_due = fecha_de_vencimiento.strftime('%Y-%m-%d')
			_logger.info('date_due %s' % invoice.date_due)

		lineas = xml.find('DetalleServicio')
		for linea in lineas:
			_logger.info('linea %s de %s %s' % (lineas.index(linea) + 1, len(lineas), linea))

			impuestos = linea.findall('Impuesto')
			_logger.info('impuestos %s' % impuestos)
			taxes = self.env['account.tax']
			for impuesto in impuestos:
				_logger.info('impuesto %s de %s %s' % (impuestos.index(impuesto) + 1, len(impuestos), impuesto))

				codigo = impuesto.find('Codigo').text

				if codigo == '01':  # impuesto de ventas
					tax = self.env.ref('l10n_cr.1_account_tax_template_IV_1', False)
					_logger.info('tax %s' % tax)
					taxes += tax
				elif codigo == '02':  # ISC
					tax = self.env.ref('l10n_cr.1_account_tax_template_ISC_0', False)
					_logger.info('tax %s' % tax)
					taxes += tax

			if taxes:
				taxes = [(6, 0, taxes.mapped('id'))]
			_logger.info('taxes %s' % taxes)

			cantidad = linea.find('Cantidad').text
			precio_unitario = linea.find('PrecioUnitario').text
			descripcion = linea.find('Detalle').text
			total = linea.find('MontoTotal').text

			_logger.info('%s %s a %s = %s' % (cantidad, descripcion, precio_unitario, total))

			porcentajeDescuento = 0.0
			if linea.find('MontoDescuento') is not None:
				montoDescuento = float(linea.find('MontoDescuento').text)
				porcentajeDescuento = montoDescuento * 100 / float(total)
				_logger.info('descuento de %s %s ' % (porcentajeDescuento, montoDescuento))

			self.env['account.invoice.line'].new({
				'quantity': cantidad,
				'price_unit': precio_unitario,
				'invoice_id': invoice.id,
				'name': descripcion,
				'account_id': 75,
				'invoice_line_tax_ids': taxes,
				'discount': porcentajeDescuento
			})

	def _proccess_supplier_invoicev43(self, invoice, xml):

		NumeroConsecutivo = xml.find('NumeroConsecutivo')
		Emisor = xml.find('Emisor')

		PlazoCredito = xml.find('PlazoCredito')

		emisor_vat = Emisor.find('Identificacion').find('Numero').text
		emisor_tipo = Emisor.find('Identificacion').find('Tipo').text

		supplier = self.env['res.partner'].search([('vat', '=', emisor_vat)])

		if not supplier:
			ctx = self.env.context.copy()
			ctx.pop('default_type', False)
			tipo = self.env['identification.type'].search([('code', '=', emisor_tipo)])

			is_company = True if tipo.code == '02' else False

			phone_code = ''
			if Emisor.find('Telefono') and Emisor.find('Telefono').find('CodigoPais'):
				phone_code = Emisor.find('Telefono').find('CodigoPais').text

			phone = ''
			if Emisor.find('Telefono') and Emisor.find('Telefono').find('NumTelefono'):
				phone = Emisor.find('Telefono').find('NumTelefono').text

			email = Emisor.find('CorreoElectronico').text
			name = Emisor.find('Nombre').text

			supplier = self.env['res.partner'].with_context(ctx).create({'name': name,
																		  'email': email,
																		  'phone_code': phone_code,
																		  'phone': phone,
																		  'vat': emisor_vat,
																		  'identification_id': tipo.id,
																		  'is_company': is_company,
																		  'customer': False,
																		  'supplier': True})
			_logger.info('nuevo proveedor %s' % supplier)

		invoice.partner_id = supplier
		invoice.date_invoice = xml.find('FechaEmision').text

		invoice.reference = NumeroConsecutivo.text

		if xml.find('CondicionVenta').text == '02':  # crédito
			fecha_de_factura = datetime.strptime(invoice.date_invoice, '%Y-%m-%d')
			plazo = 0
			try:
				plazo = int(re.sub('[^0-9]', '', PlazoCredito.text))
			except TypeError:
				_logger.info('%s no es un número' % PlazoCredito.text)
			fecha_de_vencimiento = fecha_de_factura + timedelta(days=plazo)
			invoice.date_due = fecha_de_vencimiento.strftime('%Y-%m-%d')
			_logger.info('date_due %s' % invoice.date_due)

		lineas = xml.find('DetalleServicio')
		for linea in lineas:
			_logger.info('linea %s de %s %s' % (lineas.index(linea) + 1, len(lineas), linea))

			impuestos = linea.findall('Impuesto')
			_logger.info('impuestos %s' % impuestos)
			taxes = self.env['account.tax']
			for impuesto in impuestos:
				_logger.info('impuesto %s de %s %s' % (impuestos.index(impuesto) + 1, len(impuestos), impuesto))

				Codigo = impuesto.find('Codigo')

				if Codigo.text == '01':  # iva
					CodigoTarifa = impuesto.find('CodigoTarifa')
					tax = self.env['account.tax'].search([('type_tax_use','=','purchase'),('tax_code', '=', Codigo.text),('iva_tax_code', '=', CodigoTarifa.text)])
					_logger.info('tax %s' % tax)
					taxes += tax
				elif Codigo.text == '02':  # ISC
					tax = self.env.ref('l10n_cr.1_account_tax_template_ISC_0', False)
					_logger.info('tax %s' % tax)
					taxes += tax

			if taxes:
				taxes = [(6, 0, taxes.mapped('id'))]
			_logger.info('taxes %s' % taxes)

			cantidad = linea.find('Cantidad').text
			precio_unitario = linea.find('PrecioUnitario').text
			descripcion = linea.find('Detalle').text
			total = linea.find('MontoTotal').text

			_logger.info('%s %s a %s = %s' % (cantidad, descripcion, precio_unitario, total))

			porcentajeDescuento = 0.0
			Descuento = linea.find('Descuento')
			if Descuento is not None and Descuento.find('MontoDescuento') is not None:
				_logger.info('hay descuento')
				montoDescuento = float(Descuento.find('MontoDescuento').text)
				porcentajeDescuento = montoDescuento * 100 / float(total)
				_logger.info('descuento de %s %s ' % (porcentajeDescuento, montoDescuento))

			# default_account = self.env['ir.property'].get('property_account_payable_id', 'res.partner')

			self.env['account.invoice.line'].new({
				'quantity': cantidad,
				'price_unit': precio_unitario,
				'invoice_id': invoice.id,
				'name': descripcion,
				'account_id': 75,
				'invoice_line_tax_ids': taxes,
				'discount': porcentajeDescuento
			})

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



