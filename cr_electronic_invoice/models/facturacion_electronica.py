# -*- coding: utf-8 -*-

from odoo import fields, models, api
from odoo.exceptions import UserError
import requests
import json
import datetime
from lxml import etree
import logging
import re
import random
import os
import subprocess
import base64
import pytz, ast

_logger = logging.getLogger(__name__)


class FacturacionElectronica(models.TransientModel):
	_name = 'facturacion_electronica'

	token = fields.Text('token de sesión para el sistema de recepción de comprobantes del Ministerio de Hacienda')
	timestamp = fields.Datetime('Hora en que fue recibido el token actua', readonly=True)
	ttl = fields.Integer('Tiempo de validez del token')

	@api.model
	def conexion_con_hacienda(self):
		return True if self.get_token() else False

	@api.model
	def get_token(self):

		if self.env.user.company_id.token:
			token = ast.literal_eval(self.env.user.company_id.token)

			token_timestamp = datetime.datetime.strptime(token['timestamp'], '%Y-%m-%d %H:%M:%S')

			token_expires_on = token_timestamp + datetime.timedelta(seconds=token['expires_in'])

			now = datetime.datetime.now()

			if token_expires_on > (now - datetime.timedelta(seconds=100)):
				_logger.info('token actual con ttl %s' % (token_expires_on - now).total_seconds())
				return token['access_token']
			else:
				_logger.info('token vencido hace %s' % (now - token_expires_on).total_seconds())
				return self.refresh_token()
		else:
			return self.refresh_token()

	@api.model
	def refresh_token(self):
		if self.env.user.company_id.frm_ws_ambiente == 'api-stag':
			url = 'https://idp.comprobanteselectronicos.go.cr/auth/realms/rut-stag/protocol/openid-connect/token'
		elif self.env.user.company_id.frm_ws_ambiente == 'api-prod':
			url = 'https://idp.comprobanteselectronicos.go.cr/auth/realms/rut/protocol/openid-connect/token'

		data = {
			'client_id': self.env.user.company_id.frm_ws_ambiente,
			'client_secret': '',
			'grant_type': 'password',
			'username': self.env.user.company_id.frm_ws_identificador,
			'password': self.env.user.company_id.frm_ws_password}

		try:
			response = requests.post(url, data=data)
			_logger.info('token response %s' % response.__dict__)

			respuesta = response.json()

			respuesta['timestamp'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

			_logger.info('response respuesta %s' % respuesta)
			self.env.user.company_id.token = respuesta

			return respuesta['access_token']

		except requests.exceptions.RequestException as e:
			_logger.info('RequestException\n%s' % e)
			return False

		except KeyError as e:
			_logger.info('KeyError\n%s' % e)
			return False

		except Exception as e:
			_logger.info('Exception\n%s' % e)
			return False


	@api.model
	def get_consecutivo(self, invoice):

		if len(invoice.number) == 20:
			return invoice.number

		# sucursal
		sucursal = re.sub('[^0-9]', '', str(invoice.journal_id.sucursal)).zfill(3)

		# terminal
		terminal = re.sub('[^0-9]', '', str(invoice.journal_id.terminal)).zfill(5)

		# tipo de documento
		if invoice.type == 'out_invoice':
			tipo = '01' # Factura Electrónica
		elif invoice.type == 'out_refund':
			tipo = '03' # Nota Crédito
		elif invoice.type == 'in_invoice':
			if invoice.state_invoice_partner == '1':
				tipo = '05'  # Aceptado
			elif invoice.state_invoice_partner == '2':
				tipo = '06'  # Aceptado Parcialmente
			elif invoice.state_invoice_partner == '3':
				tipo = '07'  # Rechazado
			else:
				raise UserError('Aviso!.\nDebe primero seleccionar el tipo de respuesta para el archivo cargado.')
		else:
			return False

		# numeracion
		numeracion = re.sub('[^0-9]', '', invoice.number)

		if len(numeracion) != 10:
			_logger.info('La numeración debe de tener 10 dígitos, revisar la secuencia de numeración.')
			return False

		consecutivo = sucursal + terminal + tipo + invoice.number

		if len(consecutivo) != 20:
			_logger.info('Algo anda mal con el consecutivo :( %s' % consecutivo)
			return False

		_logger.info('se genera el consecutivo %s para invoice id %s' % (consecutivo, invoice.id))

		return consecutivo

	def get_clave_in_invoice(self, invoice):

		if not invoice.xml_supplier_approval:
			_logger.info('Para la clave de los mensajes de aceptación es necesario el xml')
			return False

		xml = base64.b64decode(invoice.xml_supplier_approval)

		factura = etree.tostring(etree.fromstring(xml)).decode()
		factura = etree.fromstring(re.sub(' xmlns="[^"]+"', '', factura, count=1))

		return factura.find('Clave').text


	@api.model
	def get_clave(self, invoice):

		if invoice.type == 'in_invoice':
			return self.get_clave_in_invoice(invoice)

		# a) código de pais
		codigo_de_pais = '506'

		# fecha
		fecha = datetime.datetime.strptime(invoice.fecha , '%Y-%m-%d %H:%M:%S')

		# b) día
		dia = fecha.strftime('%d')
		# c) mes
		mes = fecha.strftime('%m')
		# d) año
		anio = fecha.strftime('%y')

		# identificación
		identificacion = re.sub('[^0-9]', '', invoice.company_id.vat or '')

		if not invoice.company_id.identification_id:
			raise UserError('Seleccione el tipo de identificación del emisor en el perfil de la compañía')
		if invoice.company_id.identification_id.code == '01' and len(identificacion) != 9:
			raise UserError('La Cédula Física del emisor debe de tener 9 dígitos')
		elif invoice.company_id.identification_id.code == '02' and len(identificacion) != 10:
			raise UserError('La Cédula Jurídica del emisor debe de tener 10 dígitos')
		elif invoice.company_id.identification_id.code == '03' and (
				len(identificacion) != 11 or len(identificacion) != 12):
			raise UserError('La identificación DIMEX del emisor debe de tener 11 o 12 dígitos')
		elif invoice.company_id.identification_id.code == '04' and len(identificacion) != 10:
			raise UserError('La identificación NITE del emisor debe de tener 10 dígitos')

		identificacion = identificacion.zfill(12)

		# f) consecutivo
		if len(invoice.number) == 20 and invoice.number.isdigit():
			consecutivo = invoice.number
		else:
			consecutivo = self.get_consecutivo(invoice)

		# g) situación
		situacion = '1'

		# h) código de seguridad
		codigo_de_seguridad = str(random.randint(1, 99999999)).zfill(8)

		# clave
		clave = codigo_de_pais + dia + mes + anio + identificacion + consecutivo + situacion + codigo_de_seguridad

		if len(clave) != 50:
			_logger.info('Algo anda mal con la clave :( %s' % clave)
			return False

		_logger.info('se genera la clave %s para invoice id %s' % (clave, invoice.id))
		return clave


	@api.multi
	def enviar_mensaje(self, invoice):

		if self.env.user.company_id.frm_ws_ambiente == 'api-stag':
			url = 'https://api.comprobanteselectronicos.go.cr/recepcion-sandbox/v1/recepcion/'
		elif self.env.user.company_id.frm_ws_ambiente == 'api-prod':
			url = 'https://api.comprobanteselectronicos.go.cr/recepcion/v1/recepcion/'

		if invoice.state_tributacion:
			_logger.info('Se esta intentando enviar una factura que ya parece haber sido enviada, no la vamos a enviar, pero vamos a decir que lo hicimos')
			return True

		xml = base64.b64decode(invoice.xml_supplier_approval)
		_logger.info('xml %s' % xml)

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
		comprobante['emisor']['tipoIdentificacion'] = Receptor.find('Identificacion').find('Tipo').text
		comprobante['emisor']['numeroIdentificacion'] = Receptor.find('Identificacion').find('Numero').text
		if Emisor is not None and Emisor.find('Identificacion') is not None:
			comprobante['receptor'] = {}
			comprobante['receptor']['tipoIdentificacion'] = Emisor.find('Identificacion').find('Tipo').text
			comprobante['receptor']['numeroIdentificacion'] = Emisor.find('Identificacion').find('Numero').text


		comprobante['consecutivoReceptor'] = invoice.number

		xml2 = base64.b64decode(invoice.xml_comprobante)

		comprobante['comprobanteXml'] = base64.b64encode(xml2).decode('utf-8')

		token = self.get_token()
		if not token:
			_logger.info('No hay conexión con hacienda')
			return False

		headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer {}'.format(token)}

		try:
			response = requests.post(url, data=json.dumps(comprobante), headers=headers)
			_logger.info('Respuesta de hacienda\n%s' % response.__dict__)

		except requests.exceptions.RequestException as e:
			_logger.info('Exception %s' % e)
			raise Exception(e)

		if response.status_code == 202:
			_logger.info('factura recibida por hacienda %s' % response.__dict__)
			invoice.state_tributacion = 'recibido'
			return True
		elif response.status_code == 301:
			_logger.info('Error 301 %s' % response.headers['X-Error-Cause'])
			return False
		elif response.status_code == 400:
			_logger.info('Error 400 %s' % response.headers['X-Error-Cause'])
			invoice.state_tributacion = 'error'
			return False
		else:
			_logger.info('no vamos a continuar, algo inesperado sucedió %s' % response.__dict__)
			if (response.headers and 'X-Error-Cause' in response.headers):
				_logger.info('Error %s : %s' % (response.status_code, response.headers['X-Error-Cause']))
			return False

	@api.multi
	def enviar_factura(self, invoice):

		if invoice.company_id.frm_ws_ambiente == 'disabled':
			return False
		elif invoice.company_id.frm_ws_ambiente == 'api-stag':
			url = 'https://api.comprobanteselectronicos.go.cr/recepcion-sandbox/v1/recepcion/'
		elif invoice.company_id.frm_ws_ambiente == 'api-prod':
			url = 'https://api.comprobanteselectronicos.go.cr/recepcion/v1/recepcion/'

		if invoice.state_tributacion != 'pendiente':
			_logger.info('Solo enviamos pendientes, no se va a enviar %s' % invoice.number)
			return False

		xml = invoice.xml_supplier_approval if invoice.type == 'in_invoice' else invoice.xml_comprobante
		xml = base64.b64decode(xml)

		_logger.info('xml %s' % xml)

		factura = etree.tostring(etree.fromstring(xml)).decode()
		factura = etree.fromstring(re.sub(' xmlns="[^"]+"', '', factura, count=1))

		Clave = factura.find('Clave').text

		if invoice.type == 'in_invoice':
			if not invoice.xml_comprobante:
				invoice.xml_comprobante = self.get_xml2(invoice)
			xml_comprobante = base64.b64decode(invoice.xml_comprobante)
			comprobante = etree.tostring(etree.fromstring(xml_comprobante)).decode()
			comprobante = etree.fromstring(re.sub(' xmlns="[^"]+"', '', comprobante, count=1))
			FechaEmision = comprobante.find('FechaEmisionDoc')
		else:
			FechaEmision = factura.find('FechaEmision')

		Emisor = factura.find('Emisor')
		Receptor = factura.find('Receptor')

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

		if invoice.type == 'in_invoice':
			mensaje['comprobanteXml'] = base64.b64encode(base64.b64decode(invoice.xml_comprobante)).decode('utf-8')
			mensaje['consecutivoReceptor'] = comprobante.find('NumeroConsecutivoReceptor').text
		else:
			mensaje['comprobanteXml'] = base64.b64encode(xml).decode('utf-8')

		token = self.get_token()
		if not token:
			_logger.info('No hay conexión con hacienda')
			return False

		headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer {}'.format(token)}

		try:
			_logger.info('validando %s' % Clave)
			response = requests.post(url, data=json.dumps(mensaje), headers=headers)
			_logger.info('Respuesta de hacienda\n%s' % response.__dict__)

		except requests.exceptions.RequestException as e:
			_logger.info('Exception %s' % e)
			raise Exception(e)

		if response.status_code == 202:
			_logger.info('documento recibido por hacienda %s' % response.__dict__)
			invoice.state_tributacion = 'recibido'
			if invoice.type == 'in_invoice':
				invoice.state_tributacion = 'aceptado'
			return True
		elif response.status_code == 301:
			_logger.info('Error 301 %s' % response.headers['X-Error-Cause'])
			return False
		elif response.status_code == 400:
			_logger.info('Error 400 %s' % response.headers['X-Error-Cause'])
			invoice.state_tributacion = 'error'
			return False
		else:
			_logger.info('no vamos a continuar, algo inesperado sucedió %s' % response.__dict__)
			if (response.headers and 'X-Error-Cause' in response.headers):
				_logger.info('Error %s : %s' % (response.status_code, response.headers['X-Error-Cause']))
			return False

	@api.model
	def enviar_email(self, invoice):
		if invoice.state_tributacion != 'aceptado':
			_logger.info('La factura %s está en estado %s, no vamos a enviar el email' % (invoice.number, invoice.state_tributacion))
			return False

		email_template = self.env.ref('account.email_template_edi_invoice', False)

		comprobante = self.env['ir.attachment'].search(
			[('res_model', '=', 'account.invoice'), ('res_id', '=', invoice.id),
			 ('res_field', '=', 'xml_comprobante')], limit=1)
		comprobante.name = invoice.fname_xml_comprobante
		comprobante.datas_fname = invoice.fname_xml_comprobante

		attachments = comprobante

		if invoice.xml_respuesta_tributacion:
			respuesta = self.env['ir.attachment'].search(
				[('res_model', '=', 'account.invoice'), ('res_id', '=', invoice.id),
				 ('res_field', '=', 'xml_respuesta_tributacion')], limit=1)
			respuesta.name = invoice.fname_xml_respuesta_tributacion
			respuesta.datas_fname = invoice.fname_xml_respuesta_tributacion

			attachments = attachments | respuesta

		email_template.attachment_ids = [(6, 0, attachments.mapped('id'))]

		email_template.with_context(type='binary', default_type='binary').send_mail(invoice.id,
																					raise_exception=False,
																					force_send=True)  # default_type='binary'

		email_template.attachment_ids = [(5)]


	def get_mensaje(self, invoice):
		_logger.info('\n\n\n\n\n\n%s' % base64.b64decode(invoice.xml_comprobante))
		_logger.info('\n\n\n\n\n\n%s' % base64.b64decode(invoice.xml_respuesta_tributacion))

	@api.model
	def consultar_factura(self, invoice):

		if invoice.company_id.frm_ws_ambiente == 'disabled':
			_logger.info('FE deshabilitada, no se consultará la factura %s' % invoice)
			return False
		elif invoice.company_id.frm_ws_ambiente == 'api-stag':
			url = 'https://api.comprobanteselectronicos.go.cr/recepcion-sandbox/v1/recepcion/'
		elif invoice.company_id.frm_ws_ambiente == 'api-prod':
			url = 'https://api.comprobanteselectronicos.go.cr/recepcion/v1/recepcion/'

		if invoice.xml_comprobante:
			factura = etree.tostring(etree.fromstring(base64.b64decode(invoice.xml_comprobante))).decode()
			factura = etree.fromstring(re.sub(' xmlns="[^"]+"', '', factura, count=1))
			clave = factura.find('Clave').text
			if not invoice.date_issuance:
				invoice.date_issuance = factura.find('FechaEmision').text
		elif invoice.number_electronic:
			clave = invoice.number_electronic
		else:
			_logger.error('no vamos a continuar, factura sin xml ni clave')
			return False

		token = self.get_token()
		if not token:
			_logger.error('No hay conexión con hacienda')
			return False

		headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer {}'.format(token)}

		if invoice.type == 'in_invoice': clave += '-' + invoice.number

		try:
			_logger.info('preguntando a %s por %s' % (url, clave))
			response = requests.get(url + '/' + clave, data=json.dumps({'clave': clave}), headers=headers)

		except requests.exceptions.RequestException as e:
			_logger.info('no vamos a continuar, Exception %s' % e)
			return False

		if response.status_code == 301:
			_logger.info('Error 301 %s' % response.headers['X-Error-Cause'])
			return False
		elif response.status_code == 400:
			_logger.info('Error 400 %s' % response.headers['X-Error-Cause'])
			invoice.respuesta_tributacion = response.headers['X-Error-Cause']
			invoice.state_tributacion = 'error'
			return False
		elif response.status_code != 200:
			_logger.info('no vamos a continuar, algo inesperado sucedió %s' % response.__dict__)
			return False

		respuesta = response.json()

		_logger.info('respuesta de hacienda\njson %s\nresponse %s\ndict %s\n' % (respuesta, response, response.__dict__))

		if 'ind-estado' not in respuesta:
			_logger.info('no vamos a continuar, no se entiende la respuesta de hacienda')
			return False



		if invoice.type == 'in_invoice':
			invoice.state_send_invoice = respuesta['ind-estado']
		else:
			invoice.state_tributacion = respuesta['ind-estado']

		# Se actualiza la factura con la respuesta de hacienda

		
		if 'respuesta-xml' in respuesta:
			invoice.fname_xml_respuesta_tributacion = 'MensajeHacienda_' + respuesta['clave'] + '.xml'
			invoice.xml_respuesta_tributacion = respuesta['respuesta-xml']

			respuesta = etree.tostring(etree.fromstring(base64.b64decode(invoice.xml_respuesta_tributacion))).decode()
			respuesta = etree.fromstring(re.sub(' xmlns="[^"]+"', '', respuesta, count=1))
			invoice.respuesta_tributacion = respuesta.find('DetalleMensaje').text

		return True

	@api.model
	def firmar_xml(self, invoice, xml):

		xml = base64.b64decode(xml).decode('utf-8')
		_logger.info('xml decoded %s' % xml)

		# directorio donde se encuentra el firmador de johann04 https://github.com/johann04/xades-signer-cr
		path = os.path.dirname(os.path.realpath(__file__))[:-6] + 'bin/'
		# nombres de archivos
		signer_filename = 'xadessignercr.jar'
		firma_filename = 'firma.p12'
		factura_filename = 'factura.xml'
		# El firmador es un ejecutable de java que necesita la firma y la factura en un archivo
		# 1) escribimos el xml de la factura en un archivo
		with open(path + factura_filename, 'w+') as file:
			file.write(xml)
		# 2) escribimos la firma en un archivo
		if not self.env.user.company_id.signature:
			raise UserError('Agregue la firma digital en el perfil de la compañía.')

		with open(path + firma_filename, 'w+b') as file:
			file.write(base64.b64decode(self.env.user.company_id.signature))
		# 3) firmamos el archivo con el signer
		subprocess.check_output(
			['java', '-jar', path + signer_filename, 'sign', path + firma_filename, self.env.user.company_id.frm_pin,
			 path + factura_filename, path + factura_filename])
		# 4) leemos el archivo firmado
		with open(path + factura_filename, 'rb') as file:
			xml = file.read()

		xml_encoded = base64.b64encode(xml).decode('utf-8')

		return xml_encoded

	@api.model
	def _validahacienda(self, max_invoices=10):  # cron

		if self.env.user.company_id.frm_ws_ambiente == 'disabled':
			_logger.info('Facturación Electrónica deshabilitada, nada que validar')
			return

		invoices = self.env['account.invoice'].search([('type', 'in', ('out_invoice', 'out_refund')),
													   ('state', 'in', ('open', 'paid')),
													   ('date_invoice', '>=', '2018-10-01'),
													   ('state_tributacion', 'in', ('pendiente',))], limit=max_invoices)
		total_invoices = len(invoices)
		current_invoice = 0
		_logger.info('Valida Hacienda - Invoices to check: %s', total_invoices)

		for invoice in invoices:

			current_invoice += 1
			_logger.info('Valida Hacienda - Invoice %s / %s', current_invoice, total_invoices)

			if not invoice.number.isdigit():
				_logger.info('Valida Hacienda - Error de Consecutivo - skipped Invoice %s', invoice.number)
				continue

			if not invoice.xml_comprobante:

				comprobante = self.get_xml(invoice)

				if not comprobante:
					_logger.info('Valida Hacienda - Error de creación de comprobante - skipped Invoice %s', invoice.number)
					continue

				sufijo = ''
				if invoice.type == 'out_invoice':
					sufijo = 'FacturaElectronica_'
				elif invoice.type == 'out_refund':
					sufijo = 'NotaCreditoElectronica'
				elif invoice.type == 'in_invoice':
					sufijo = 'MensajeReceptor'

				invoice.xml_comprobante = comprobante
				invoice.fname_xml_comprobante = sufijo + invoice.number_electronic + '.xml'

			token = self.get_token()

			if token:
				if self.enviar_factura(invoice):
					if self.consultar_factura(invoice):
						self.enviar_email(invoice)

		_logger.info('Valida Hacienda - Finalizado Exitosamente')

	@api.model
	def _consultahacienda(self, max_invoices=10):  # cron

		if self.env.user.company_id.frm_ws_ambiente == 'disabled':
			_logger.info('Facturación Electrónica deshabilitada, nada que consultar')
			return

		invoices = self.env['account.invoice'].search(
			[('type', 'in', ('out_invoice', 'out_refund')), ('state', 'in', ('open', 'paid')),
			 ('state_tributacion', 'in', ('recibido', 'procesando', 'error'))])

		total_invoices = len(invoices)
		current_invoice = 0
		_logger.info('Consulta Hacienda - Invoices to check: %s', total_invoices)

		for invoice in invoices:

			current_invoice += 1
			_logger.info('Consulta Hacienda - Invoice %s / %s', current_invoice, total_invoices)

			if self.consultar_factura(invoice):
				self.enviar_email(invoice)

		_logger.info('Consulta Hacienda - Finalizado Exitosamente')

	@api.model
	def get_xml2(self, invoice):

		if not invoice.number:
			_logger.error('Factura sin consecutivo %s', invoice)
			return False

		if not invoice.number.isdigit():
			_logger.error('Error de numeración %s', invoice.number)
			return False

		if len(invoice.number) != 20:
			consecutivo = self.get_consecutivo(invoice)
			if not consecutivo:
				_logger.error('Error de consecutivo %s' % invoice.number)
				return False

			invoice.number = consecutivo

		xml = base64.b64decode(invoice.xml_supplier_approval)
		_logger.info('xml %s' % xml)

		factura = etree.tostring(etree.fromstring(xml)).decode()
		factura = etree.fromstring(re.sub(' xmlns="[^"]+"', '', factura, count=1))

		Emisor = factura.find('Emisor')
		Receptor = factura.find('Receptor')
		TotalImpuesto = factura.find('ResumenFactura').find('TotalImpuesto')
		TotalComprobante = factura.find('ResumenFactura').find('TotalComprobante')

		emisor = invoice.company_id

		# MensajeReceptor 4.2

		documento = 'MensajeReceptor' # MensajeReceptor
		xmlns = 'https://tribunet.hacienda.go.cr/docs/esquemas/2017/v4.2/mensajeReceptor'
		schemaLocation = 'https://tribunet.hacienda.go.cr/docs/esquemas/2017/v4.2/mensajeReceptor  https://tribunet.hacienda.go.cr/docs/esquemas/2017/v4.2/MensajeReceptor_4.2.xsd'

		xsi = 'http://www.w3.org/2001/XMLSchema-instance'
		xsd = 'http://www.w3.org/2001/XMLSchema'
		ds = 'http://www.w3.org/2000/09/xmldsig#'

		nsmap = {None : xmlns, 'xsd': xsd, 'xsi': xsi, 'ds': ds}
		attrib = {'{'+xsi+'}schemaLocation':schemaLocation}

		Documento = etree.Element(documento, attrib=attrib, nsmap=nsmap)

		# Clave
		Clave = etree.Element('Clave')
		Clave.text = factura.find('Clave').text
		Documento.append(Clave)

		# NumeroCedulaEmisor
		NumeroCedulaEmisor = etree.Element('NumeroCedulaEmisor')
		NumeroCedulaEmisor.text = factura.find('Emisor').find('Identificacion').find('Numero').text
		Documento.append(NumeroCedulaEmisor)

		now_utc = datetime.datetime.now(pytz.timezone('UTC'))
		now_cr = now_utc.astimezone(pytz.timezone('America/Costa_Rica'))
		date_cr = now_cr.strftime("%Y-%m-%dT%H:%M:%S-06:00")

		# FechaEmisionDoc
		FechaEmisionDoc = etree.Element('FechaEmisionDoc')
		FechaEmisionDoc.text = date_cr
		Documento.append(FechaEmisionDoc)

		# Mensaje
		Mensaje = etree.Element('Mensaje')
		Mensaje.text = invoice.state_invoice_partner
		Documento.append(Mensaje)

		# DetalleMensaje
		DetalleMensaje = etree.Element('DetalleMensaje')
		DetalleMensaje.text = 'Mensaje de ' + emisor.name
		Documento.append(DetalleMensaje)

		if TotalImpuesto is not None:
			# MontoTotalImpuesto
			MontoTotalImpuesto = etree.Element('MontoTotalImpuesto')
			MontoTotalImpuesto.text = TotalImpuesto.text
			Documento.append(MontoTotalImpuesto)

		# TotalFactura
		TotalFactura = etree.Element('TotalFactura')
		TotalFactura.text = TotalComprobante.text
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
		NumeroConsecutivoReceptor.text = invoice.number
		Documento.append(NumeroConsecutivoReceptor)

		xml = etree.tostring(Documento, encoding='UTF-8', xml_declaration=True, pretty_print=True)

		xml_encoded = base64.b64encode(xml).decode('utf-8')

		xml_firmado = self.firmar_xml(invoice, xml_encoded)

		return xml_firmado

	@api.model
	def get_xml(self, invoice):

		if invoice.type == 'in_invoice':
			return self.get_xml2(invoice)

		if not invoice.number:
			_logger.error('Factura sin consecutivo %s', invoice)
			return False

		if not invoice.number.isdigit():
			_logger.error('Error de numeración %s', invoice.number)
			return False

		if len(invoice.number) != 20:
			consecutivo = self.get_consecutivo(invoice)
			if not consecutivo:
				_logger.error('Error de consecutivo %s' % invoice.number)
				return False

			invoice.number = consecutivo

		if not invoice.number_electronic:
			clave = self.get_clave(invoice)
			if not clave:
				_logger.error('Error de clave %s' % invoice)
				return False

			invoice.number_electronic = clave

		if len(invoice.number_electronic) != 50:
			_logger.error('Error de clave %s' % invoice.number_electronic)
			return False

		emisor = invoice.company_id
		receptor = invoice.partner_id

		# FacturaElectronica 4.2

		if invoice.type == 'out_invoice':
			documento = 'FacturaElectronica' # Factura Electrónica
			xmlns = 'https://tribunet.hacienda.go.cr/docs/esquemas/2017/v4.2/facturaElectronica'
			schemaLocation = 'https://tribunet.hacienda.go.cr/docs/esquemas/2017/v4.2/facturaElectronica  https://tribunet.hacienda.go.cr/docs/esquemas/2017/v4.2/FacturaElectronica_V.4.2.xsd'

		elif invoice.type == 'out_refund':
			documento = 'NotaCreditoElectronica' # Nota de Crédito
			xmlns = 'https://tribunet.hacienda.go.cr/docs/esquemas/2017/v4.2/notaCreditoElectronica'
			schemaLocation = 'https://tribunet.hacienda.go.cr/docs/esquemas/2017/v4.2/notaCreditoElectronica  https://tribunet.hacienda.go.cr/docs/esquemas/2017/v4.2/NotaCreditoElectronica_V4.2.xsd'
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

		# NumeroConsecutivo
		NumeroConsecutivo = etree.Element('NumeroConsecutivo')
		NumeroConsecutivo.text = invoice.number
		Documento.append(NumeroConsecutivo)

		# FechaEmision
		FechaEmision = etree.Element('FechaEmision')
		FechaEmision.text = datetime.datetime.strptime(invoice.fecha, '%Y-%m-%d %H:%M:%S').strftime("%Y-%m-%dT%H:%M:%S")
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
		if receptor:

			Receptor = etree.Element('Receptor')

			Nombre = etree.Element('Nombre')
			Nombre.text = receptor.name
			Receptor.append(Nombre)

			if receptor.identification_id and receptor.vat:
				identificacion = re.sub('[^0-9]', '', receptor.vat)

				if receptor.identification_id.code == '05':
					IdentificacionExtranjero = etree.Element('IdentificacionExtranjero')
					IdentificacionExtranjero.text = identificacion[:20]
					Receptor.append(IdentificacionExtranjero)
				else:
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
			datetime.timedelta(7)
			fecha_de_factura = datetime.datetime.strptime(invoice.date_invoice, '%Y-%m-%d')
			fecha_de_vencimiento = datetime.datetime.strptime(invoice.date_due, '%Y-%m-%d')
			PlazoCredito.text = str((fecha_de_factura - fecha_de_vencimiento).days)
			Documento.append(PlazoCredito)
		else:
			CondicionVenta.text = '01'
			Documento.append(CondicionVenta)

		# MedioPago
		MedioPago = etree.Element('MedioPago')
		MedioPago.text = invoice.payment_methods_id.sequence
		Documento.append(MedioPago)

		# DetalleServicio
		DetalleServicio = etree.Element('DetalleServicio')

		totalServiciosGravados = 0
		totalServiciosExentos = 0
		totalMercanciasGravadas = 0
		totalMercanciasExentas = 0

		totalDescuentosMercanciasExentas = 0
		totalDescuentosMercanciasGravadas = 0
		totalDescuentosServiciosExentos = 0
		totalDescuentosServiciosGravados = 0

		totalImpuesto = 0

		for indice, linea in enumerate(invoice.invoice_line_ids):
			LineaDetalle = etree.Element('LineaDetalle')

			NumeroLinea = etree.Element('NumeroLinea')
			NumeroLinea.text = '%s' % (indice + 1)
			LineaDetalle.append(NumeroLinea)

			if linea.product_id.default_code:
				Codigo = etree.Element('Codigo')

				Tipo = etree.Element('Tipo')
				Tipo.text = '02' if linea.product_id and linea.product_id.type == 'service' else '01'

				Codigo.append(Tipo)

				Codigo2 = etree.Element('Codigo')
				Codigo2.text = linea.product_id.default_code
				Codigo.append(Codigo2)

				LineaDetalle.append(Codigo)

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
			PrecioUnitario.text = str(round(linea.price_unit, 2))
			LineaDetalle.append(PrecioUnitario)

			MontoTotal = etree.Element('MontoTotal')
			montoTotal = linea.price_unit * linea.quantity
			MontoTotal.text = str(round(montoTotal, 2))

			LineaDetalle.append(MontoTotal)

			if linea.discount:
				MontoDescuento = etree.Element('MontoDescuento')
				montoDescuento = round(montoTotal * linea.discount / 100, 2)
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
				LineaDetalle.append(MontoDescuento)

				NaturalezaDescuento = etree.Element('NaturalezaDescuento')
				NaturalezaDescuento.text = linea.discount_note or 'Descuento Comercial'
				LineaDetalle.append(NaturalezaDescuento)

			SubTotal = etree.Element('SubTotal')
			SubTotal.text = str(round(linea.price_subtotal, 2))
			LineaDetalle.append(SubTotal)

			if linea.invoice_line_tax_ids:
				for impuesto in linea.invoice_line_tax_ids:

					Impuesto = etree.Element('Impuesto')

					Codigo = etree.Element('Codigo')
					# Codigo.text = impuesto.code
					Codigo.text = '01'
					Impuesto.append(Codigo)

					if linea.product_id.type == 'service' and impuesto.tax_code != '07':
						raise UserError('No se puede aplicar impuesto de ventas a los servicios')

					Tarifa = etree.Element('Tarifa')
					Tarifa.text = str(round(impuesto.amount, 2))
					Impuesto.append(Tarifa)

					Monto = etree.Element('Monto')
					monto = round(linea.price_subtotal * impuesto.amount / 100.0, 2)
					totalImpuesto += monto
					Monto.text = str(monto)
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
			MontoTotalLinea.text = str(round(linea.price_total, 2))
			LineaDetalle.append(MontoTotalLinea)

			DetalleServicio.append(LineaDetalle)

		Documento.append(DetalleServicio)

		# ResumenFactura
		ResumenFactura = etree.Element('ResumenFactura')

		if totalServiciosGravados:
			TotalServGravados = etree.Element('TotalServGravados')
			TotalServGravados.text = str(round(totalServiciosGravados + totalDescuentosServiciosGravados, 2))
			ResumenFactura.append(TotalServGravados)

		if totalServiciosExentos:
			TotalServExentos = etree.Element('TotalServExentos')
			TotalServExentos.text = str(round(totalServiciosExentos + totalDescuentosServiciosExentos, 2))
			ResumenFactura.append(TotalServExentos)

		if totalMercanciasGravadas:
			TotalMercanciasGravadas = etree.Element('TotalMercanciasGravadas')
			TotalMercanciasGravadas.text = str(round(totalMercanciasGravadas + totalDescuentosMercanciasGravadas, 2))
			ResumenFactura.append(TotalMercanciasGravadas)

		if totalMercanciasExentas:
			TotalMercanciasExentas = etree.Element('TotalMercanciasExentas')
			TotalMercanciasExentas.text = str(round(totalMercanciasExentas + totalDescuentosMercanciasExentas, 2))
			ResumenFactura.append(TotalMercanciasExentas)

		if totalServiciosGravados + totalMercanciasGravadas:
			TotalGravado = etree.Element('TotalGravado')
			TotalGravado.text = str(round(totalServiciosGravados + totalDescuentosServiciosGravados + totalMercanciasGravadas + totalDescuentosMercanciasGravadas, 2))
			ResumenFactura.append(TotalGravado)

		if totalServiciosExentos + totalMercanciasExentas:
			TotalExento = etree.Element('TotalExento')
			TotalExento.text = str(round(totalServiciosExentos + totalDescuentosServiciosExentos + totalMercanciasExentas + totalDescuentosMercanciasExentas, 2))
			ResumenFactura.append(TotalExento)

		TotalVenta = etree.Element('TotalVenta')
		TotalVenta.text = str(round(invoice.amount_untaxed + totalDescuentosServiciosGravados + totalDescuentosMercanciasGravadas + totalDescuentosServiciosExentos + totalDescuentosMercanciasExentas, 2))
		ResumenFactura.append(TotalVenta)

		if totalDescuentosServiciosGravados + totalDescuentosMercanciasGravadas + totalDescuentosServiciosExentos + totalDescuentosMercanciasExentas:
			TotalDescuentos = etree.Element('TotalDescuentos')
			TotalDescuentos.text = str(round(totalDescuentosServiciosGravados + totalDescuentosMercanciasGravadas + totalDescuentosServiciosExentos + totalDescuentosMercanciasExentas, 2))
			ResumenFactura.append(TotalDescuentos)

		TotalVentaNeta = etree.Element('TotalVentaNeta')
		TotalVentaNeta.text = str(round(invoice.amount_untaxed, 2))
		ResumenFactura.append(TotalVentaNeta)

		if invoice.amount_tax:
			TotalImpuesto = etree.Element('TotalImpuesto')
			# TotalImpuesto.text = str(round(invoice.amount_tax, 2))
			TotalImpuesto.text = str(round(totalImpuesto, 2))
			ResumenFactura.append(TotalImpuesto)

		TotalComprobante = etree.Element('TotalComprobante')
		TotalComprobante.text = str(round(invoice.amount_total, 2))
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
			Numero.text = invoice.refund_invoice_id.number_electronic
			InformacionReferencia.append(Numero)

			FechaEmision = etree.Element('FechaEmision')
			FechaEmision.text = invoice.refund_invoice_id.date_issuance
			InformacionReferencia.append(FechaEmision)

			Codigo = etree.Element('Codigo')
			Codigo.text = invoice.reference_code_id.code
			InformacionReferencia.append(Codigo)

			Razon = etree.Element('Razon')
			Razon.text = invoice.name or 'Error en Factura'
			InformacionReferencia.append(Razon)

			Documento.append(InformacionReferencia)

		# Normativa
		Normativa = etree.Element('Normativa')

		NumeroResolucion = etree.Element('NumeroResolucion')
		NumeroResolucion.text = 'DGT-R-48-2016'
		Normativa.append(NumeroResolucion)

		FechaResolucion = etree.Element('FechaResolucion')
		FechaResolucion.text = '07-10-2016 08:00:00'
		Normativa.append(FechaResolucion)

		Documento.append(Normativa)

		xml = etree.tostring(Documento,encoding='UTF-8', xml_declaration=True, pretty_print=True)

		xml_encoded = base64.b64encode(xml).decode('utf-8')

		xml_firmado = self.firmar_xml(invoice, xml_encoded)

		return xml_firmado

	@api.model
	def get_te(self, order):
		_logger.info('order %s' % order)
		# _logger.info('order %s' % order.__dict__)
		_logger.info(order.sequence_number)
		_logger.info(order.company_id)
		_logger.info(order.partner_id)
		_logger.info(order.partner_id)
		for linea in order.lines:
			_logger.info(linea.product_id)
			_logger.info(linea.qty)
			_logger.info(linea.name)
			_logger.info(linea.price_unit)
		_logger.info(order.amount_total)
		_logger.info(order.amount_paid)
		_logger.info(order.amount_tax)
		_logger.info(order.nb_print)
		_logger.info(order.invoice_id)

		Invoice = self.env['account.invoice']
		Order = self.env['pos.order']

		local_context = dict(Order.env.context, force_company=order.company_id.id, company_id=order.company_id.id)

		invoice = Invoice.new(order._prepare_invoice())
		invoice._onchange_partner_id()
		invoice.fiscal_position_id = order.fiscal_position_id

		inv = invoice._convert_to_write({name: invoice[name] for name in invoice._cache})
		new_invoice = Invoice.with_context(local_context).sudo().create(inv)

		Invoice += new_invoice

		for line in order.lines:
			Order.with_context(local_context)._action_create_invoice_line(line, new_invoice.id)

		new_invoice.with_context(local_context).sudo().compute_taxes()

		_logger.info(new_invoice)

		xml = self.get_xml(new_invoice)

		order.xml_comprobante = xml
		order.fname_xml_comprobante = 'archivo.xml'


		# raise UserError('Suave')

		return order