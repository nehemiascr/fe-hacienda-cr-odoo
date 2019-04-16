# -*- coding: utf-8 -*-

from odoo import fields, models, api
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

		return self.refresh_token()

		if self.env.user.company_id.token:
			token = ast.literal_eval(self.env.user.company_id.token)

			token_timestamp = datetime.strptime(token['timestamp'], '%Y-%m-%d %H:%M:%S')

			token_expires_on = token_timestamp + timedelta(seconds=token['expires_in'])

			now = datetime.now()

			if token_expires_on > (now - timedelta(seconds=100)):
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

			respuesta = response.json()

			respuesta['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

			_logger.info('token length %s type %s' % (len(respuesta['access_token']), respuesta['token_type']) if 'acces_token' in respuesta else 'No hay conexión con hacienda')
			# self.env.user.company_id.token = respuesta

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
	def _get_consecutivo(self, object):

		# tipo de documento
		if object._name == 'account.invoice':
			numeracion = object.number
			diario = object.journal_id
			if object.type == 'out_invoice':
				tipo = '01'  # Factura Electrónica
			elif object.type == 'out_refund' and object.amount_total_signed > 0:
				tipo = '02' # Nota Débito
			elif object.type == 'out_refund' and object.amount_total_signed <= 0:
				tipo = '03' # Nota Crédito
			elif object.type in ('in_invoice', 'in_refund'):
				if object.state_invoice_partner == '1':
					tipo = '05' # Aceptado
				elif object.state_invoice_partner == '2':
					tipo = '06' # Aceptado Parcialmente
				elif object.state_invoice_partner == '3':
					tipo = '07' # Rechazado
		elif object._name == 'pos.order':
			numeracion = object.name
			diario = object.sale_journal
			tipo = '04'  # Tiquete Electrónico
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
		elif invoice.type in ('in_invoice', 'in_refund'):
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

	@api.model
	def _get_clave(self, object):

		if object._name == 'account.invoice':
			if object.type in ('in_invoice', 'in_refund'):
				if not object.xml_supplier_approval:
					_logger.info('Para la clave de los mensajes de aceptación es necesario el xml')
					return False
				xml = base64.b64decode(object.xml_supplier_approval)
				factura = etree.tostring(etree.fromstring(xml)).decode()
				factura = etree.fromstring(re.sub(' xmlns="[^"]+"', '', factura, count=1))
				return factura.find('Clave').text
			elif object.type in ('out_invoice', 'out_refund'):
				consecutivo = object.number
		elif object._name == 'pos.order':
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
		elif object.company_id.identification_id.code == '03' and (
				len(identificacion) != 11 or len(identificacion) != 12):
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

	@api.multi
	def _enviar_documento(self, object):

		if object.company_id.frm_ws_ambiente == 'disabled':
			return False
		elif object.company_id.frm_ws_ambiente == 'api-stag':
			url = 'https://api.comprobanteselectronicos.go.cr/recepcion-sandbox/v1/recepcion/'
		elif object.company_id.frm_ws_ambiente == 'api-prod':
			url = 'https://api.comprobanteselectronicos.go.cr/recepcion/v1/recepcion/'

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

		if object._name == 'account.invoice' and object.type in ('in_invoice', 'in_refund'):
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

		if object._name == 'account.invoice' and object.type in ('in_invoice', 'in_refund'):
			mensaje['consecutivoReceptor'] = Documento.find('NumeroConsecutivoReceptor').text

		token = self.get_token()
		if not token:
			_logger.info('No hay conexión con hacienda')
			return False

		headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer {}'.format(token)}

		try:
			_logger.info('validando %s' % Clave.text)
			response = requests.post(url, data=json.dumps(mensaje), headers=headers)
			_logger.info('Respuesta de hacienda\n%s' % response)

		except requests.exceptions.RequestException as e:
			_logger.info('Exception %s' % e)
			raise Exception(e)

		if response.status_code == 202:
			_logger.info('documento recibido por hacienda %s' % response)
			if object._name == 'account.invoice' and object.type in ('in_invoice', 'in_refund'):
				object.state_tributacion = 'aceptado'
			else:
				object.state_tributacion = 'recibido'
			return True
		else:
			_logger.info('Error %s %s' % (response.status_code, response.headers['X-Error-Cause'] if 'X-Error-Cause' in response else response.headers))
			_logger.info('no vamos a continuar, algo inesperado sucedió %s' % response)
			object.state_tributacion = 'error'
			object.respuesta_tributacion = response.headers['X-Error-Cause'] if response.headers and 'X-Error-Cause' in response.headers else 'No hay de Conexión con Hacienda'

			if 'ya fue recibido anteriormente' in object.respuesta_tributacion:
				object.state_tributacion = 'aceptado' if object._name == 'account.invoice' and object.type in ('in_invoice', 'in_refund') else 'recibido'

			if 'no ha sido recibido' in object.respuesta_tributacion:
				object.state_tributacion = 'pendiente'

			return False

	@api.model
	def _enviar_email(self, object):
		if object.state_tributacion != 'aceptado':
			_logger.info('documento %s estado %s, no vamos a enviar el email' % (object, object.state_tributacion))
			return False

		if not object.partner_id:
			_logger.info('documento %s sin cliente, no vamos a enviar el email' % object)
			return False

		if not object.partner_id.email:
			_logger.info('Cliente %s sin email, no vamos a enviar el email' %  object.partner_id)
			return False

		email_template = self.env.ref('account.email_template_edi_invoice', False)

		comprobante = self.env['ir.attachment'].search(
			[('res_model', '=', object._name), ('res_id', '=', object.id),
			 ('res_field', '=', 'xml_comprobante')], limit=1)
		comprobante.name = object.fname_xml_comprobante
		comprobante.datas_fname = object.fname_xml_comprobante

		attachments = comprobante

		if object.xml_respuesta_tributacion:
			respuesta = self.env['ir.attachment'].search(
				[('res_model', '=', object._name), ('res_id', '=', object.id),
				 ('res_field', '=', 'xml_respuesta_tributacion')], limit=1)
			respuesta.name = object.fname_xml_respuesta_tributacion
			respuesta.datas_fname = object.fname_xml_respuesta_tributacion

			attachments = attachments | respuesta

		email_template.attachment_ids = [(6, 0, attachments.mapped('id'))]

		email_to = object.partner_id.email_facturas or object.partner_id.email
		_logger.info('emailing to %s' % email_to)

		email_template.with_context(type='binary', default_type='binary').send_mail(object.id,
																					raise_exception=False,
																					force_send=True,
																					email_values={'email_to':email_to})  # default_type='binary'

		email_template.attachment_ids = [(5)]

		if object._name == 'account.invoice': object.sent = True


	@api.model
	def _consultar_documento(self, object):

		if object.company_id.frm_ws_ambiente == 'disabled':
			_logger.info('FE deshabilitada, no se consultará el documento %s' % object)
			return False
		elif object.company_id.frm_ws_ambiente == 'api-stag':
			url = 'https://api.comprobanteselectronicos.go.cr/recepcion-sandbox/v1/recepcion/'
		elif object.company_id.frm_ws_ambiente == 'api-prod':
			url = 'https://api.comprobanteselectronicos.go.cr/recepcion/v1/recepcion/'


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

		token = self.get_token()
		if not token:
			_logger.error('No hay conexión con hacienda')
			return False

		headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer {}'.format(token)}

		if 'type' in object and object.type in ('in_invoice','in_refund'): clave += '-' + object.number

		try:
			_logger.info('preguntando a %s por %s' % (url, clave))
			response = requests.get(url + '/' + clave, data=json.dumps({'clave': clave}), headers=headers)

		except requests.exceptions.RequestException as e:
			_logger.info('no vamos a continuar, Exception %s' % e)
			return False

		if response.status_code in (301, 400):
			_logger.info('Error %s %s' % (response.status_code, response.headers['X-Error-Cause']))
			_logger.info('no vamos a continuar, algo inesperado sucedió %s' % response.__dict__)
			object.state_tributacion = 'error'
			object.respuesta_tributacion = response.headers['X-Error-Cause'] if response.headers and 'X-Error-Cause' in response.headers else 'No hay de Conexión con Hacienda'
			if 'ya fue recibido anteriormente' in object.respuesta_tributacion: object.state_tributacion = 'recibido'
			if 'no ha sido recibido' in object.respuesta_tributacion: object.state_tributacion = 'pendiente'
			return False

		respuesta = response.json()

		if 'ind-estado' not in respuesta:
			_logger.info('no vamos a continuar, no se entiende la respuesta de hacienda')
			return False

		_logger.info('respuesta de hacienda %s' %  response)
		_logger.info('respuesta para %s %s' % (object, respuesta['ind-estado']))

		object.state_tributacion = respuesta['ind-estado']

		# Se actualiza la factura con la respuesta de hacienda

		if 'respuesta-xml' in respuesta:
			object.fname_xml_respuesta_tributacion = 'MensajeHacienda_' + respuesta['clave'] + '.xml'
			object.xml_respuesta_tributacion = respuesta['respuesta-xml']

			respuesta = etree.tostring(etree.fromstring(base64.b64decode(object.xml_respuesta_tributacion))).decode()
			respuesta = etree.fromstring(re.sub(' xmlns="[^"]+"', '', respuesta, count=1))
			object.respuesta_tributacion = respuesta.find('DetalleMensaje').text

		return True

	@api.model
	def firmar_xml(self, xml):

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
	def _validahacienda(self, max_documentos=4):  # cron

		if self.env.user.company_id.frm_ws_ambiente == 'disabled':
			_logger.info('Facturación Electrónica deshabilitada, nada que validar')
			return

		try:
			invoice = self.env['account.invoice']
		except KeyError as e:
			_logger.info('KeyError %s' % e)
			invoice = None
		except:
			_logger.info('unknown error %s' % sys.exc_info()[0])

		try:
			order = self.env['pos.order']
		except KeyError as e:
			_logger.info('KeyError %s' % e)
			order = None
		except:
			_logger.info('unknown error %s' % sys.exc_info()[0])

		if invoice != None:
			facturas = invoice.search([('state', 'in', ('open', 'paid')),
									   ('state_tributacion', 'in', ('pendiente',))], limit=max_documentos)
			_logger.info('Validando %s FacturaElectronica' % len(facturas))
			for indice, factura in enumerate(facturas):
				_logger.info('Validando FacturaElectronica %s / %s ' % (indice+1, len(facturas)))
				if not factura.xml_comprobante:
					pass
				self._enviar_documento(factura)
				max_documentos -= 1

		if order != None:
			tiquetes = order.search([('state_tributacion', 'in', ('pendiente',))], limit=max_documentos)
			_logger.info('Validando %s TiqueteElectronico' % len(tiquetes))
			for indice, tiquete in enumerate(tiquetes):
				_logger.info('Validando TiqueteElectronico %s / %s ' % (indice+1, len(tiquetes)))
				if not tiquete.xml_comprobante:
					pass
				self._enviar_documento(tiquete)

		_logger.info('Valida - Finalizado Exitosamente')

	@api.model
	def _consultahacienda(self, max_documentos=4):  # cron

		if self.env.user.company_id.frm_ws_ambiente == 'disabled':
			_logger.info('Facturación Electrónica deshabilitada, nada que validar')
			return

		try:
			invoice = self.env['account.invoice']
		except KeyError:
			invoice = None

		try:
			order = self.env['pos.order']
		except KeyError:
			order = None

		if invoice != None:
			facturas = invoice.search([('type', 'in', ('out_invoice', 'out_refund')),
									   ('state', 'in', ('open', 'paid')),
									   ('state_tributacion', 'in', ('recibido', 'procesando', 'error'))], limit=max_documentos)

			for indice, factura in enumerate(facturas):
				_logger.info('Consultando documento %s / %s ' % (indice+1, len(facturas)))
				if not factura.xml_comprobante:
					pass
				if self._consultar_documento(factura):
					self._enviar_email(factura)
				max_documentos -= 1

		if order != None:
			tiquetes = order.search([('state_tributacion', 'in', ('recibido', 'procesando', 'error'))], limit=max_documentos)

			for indice, tiquete in enumerate(tiquetes):
				_logger.info('Consultando documento %s / %s ' % (indice+1, len(tiquetes)))
				if not tiquete.xml_comprobante:
					pass
				if self._consultar_documento(tiquete):
					self._enviar_email(tiquete)

		_logger.info('Consulta Hacienda - Finalizado Exitosamente')

	@api.model
	def get_xml(self, object):
		object.ensure_one()

		if object._name == 'account.invoice':
			if object.type in ('out_invoice', 'out_refund'):
				Documento = self._get_xml_FE_NC_ND(object)
			elif object.type in ('in_invoice', 'in_refund'):
				Documento = self._get_xml_MR(object)
		elif object._name == 'pos.order':
			Documento = self._get_xml_TE(object)

		_logger.info ('Documento %s' % Documento)
		xml = etree.tostring(Documento, encoding='UTF-8', xml_declaration=True, pretty_print=True)
		xml_base64_encoded = base64.b64encode(xml).decode('utf-8')
		xml_base64_encoded_firmado = self.firmar_xml(xml_base64_encoded)

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

		# TiqueteElectronico 4.2
		decimales = 2

		documento = 'TiqueteElectronico' # Tiquete Electronico
		xmlns = 'https://tribunet.hacienda.go.cr/docs/esquemas/2017/v4.2/tiqueteElectronico'
		schemaLocation = 'https://tribunet.hacienda.go.cr/docs/esquemas/2017/v4.2/tiqueteElectronico https://tribunet.hacienda.go.cr/docs/esquemas/2016/v4.2/TiqueteElectronico_V4.2.xsd'

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
		if receptor:

			Receptor = etree.Element('Receptor')

			Nombre = etree.Element('Nombre')
			Nombre.text = receptor.name # receptor.name
			Receptor.append(Nombre)

			if receptor.identification_id and receptor.vat:
				identificacion = re.sub('[^0-9]', '', receptor.vat)

				if receptor.identification_id.code == '05':
					IdentificacionExtranjero = etree.Element('IdentificacionExtranjero')
					IdentificacionExtranjero.text = identificacion[:20] # identificacion
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
					Tipo.text = receptor.identification_id.code # receptor.identification_id
					Identificacion.append(Tipo)

					Numero = etree.Element('Numero')
					Numero.text = identificacion # identificacion
					Identificacion.append(Numero)

					Receptor.append(Identificacion)

			if receptor.state_id and receptor.county_id and receptor.district_id and receptor.street:
				Ubicacion = etree.Element('Ubicacion')

				Provincia = etree.Element('Provincia')
				Provincia.text = receptor.state_id.code # receptor.state_id
				Ubicacion.append(Provincia)

				Canton = etree.Element('Canton')
				Canton.text = receptor.county_id.code # receptor.county_id
				Ubicacion.append(Canton)

				Distrito = etree.Element('Distrito')
				Distrito.text = receptor.district_id.code # receptor.district_id
				Ubicacion.append(Distrito)

				if receptor.neighborhood_id:
					Barrio = etree.Element('Barrio')
					Barrio.text = receptor.neighborhood_id.code # receptor.neighborhood_id
					Ubicacion.append(Barrio)

				OtrasSenas = etree.Element('OtrasSenas')
				OtrasSenas.text = receptor.street # receptor.street
				Ubicacion.append(OtrasSenas)

				Receptor.append(Ubicacion)

			telefono = receptor.phone or receptor.mobile
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

					Receptor.append(Telefono)

			if receptor.email and re.match('^[(a-z0-9\_\-\.)]+@[(a-z0-9\_\-\.)]+\.[(a-z)]{2,15}$', receptor.email.lower()):
				CorreoElectronico = etree.Element('CorreoElectronico')
				CorreoElectronico.text = receptor.email # receptor.email
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

		totalServiciosGravados = round(0.0, decimales)
		totalServiciosExentos = round(0.0, decimales)
		totalMercanciasGravadas = round(0.0, decimales)
		totalMercanciasExentas = round(0.0, decimales)

		totalDescuentosMercanciasExentas = round(0.0, decimales)
		totalDescuentosMercanciasGravadas = round(0.0, decimales)
		totalDescuentosServiciosExentos = round(0.0, decimales)
		totalDescuentosServiciosGravados = round(0.0, decimales)

		totalImpuesto = round(0.0, decimales)

		impuestoServicio = self.env['account.tax'].search([('tax_code', '=', 'IS')])
		servicio = True if impuestoServicio in order.lines.mapped('tax_ids_after_fiscal_position') else False

		indice = 1
		for linea in order.lines:

			LineaDetalle = etree.Element('LineaDetalle')

			NumeroLinea = etree.Element('NumeroLinea')
			NumeroLinea.text = '%s' % indice # indice + 1
			LineaDetalle.append(NumeroLinea)

			if linea.product_id.default_code:
				Codigo = etree.Element('Codigo')

				Tipo = etree.Element('Tipo')
				Tipo.text = '02' if linea.product_id and linea.product_id.type == 'service' else '01'

				Codigo.append(Tipo)

				Codigo2 = etree.Element('Codigo')
				Codigo2.text = linea.product_id.default_code # product_id.default_code
				Codigo.append(Codigo2)

				LineaDetalle.append(Codigo)

			Cantidad = etree.Element('Cantidad')
			Cantidad.text = str(linea.qty) # linea.qty
			LineaDetalle.append(Cantidad)

			UnidadMedida = etree.Element('UnidadMedida')
			UnidadMedida.text = 'Sp' if (linea.product_id and linea.product_id.type == 'service') else 'Unid'

			LineaDetalle.append(UnidadMedida)

			Detalle = etree.Element('Detalle')
			Detalle.text = linea.product_id.product_tmpl_id.name # product_tmpl_id.name
			LineaDetalle.append(Detalle)

			precioUnitario = round(linea.price_unit, decimales)

			PrecioUnitario = etree.Element('PrecioUnitario')
			PrecioUnitario.text = str(precioUnitario)
			LineaDetalle.append(PrecioUnitario)

			MontoTotal = etree.Element('MontoTotal')
			montoTotal = precioUnitario * round(linea.qty, decimales)
			MontoTotal.text = str(round(montoTotal, decimales))

			LineaDetalle.append(MontoTotal)

			if linea.discount:
				MontoDescuento = etree.Element('MontoDescuento')
				montoDescuento = round(round(montoTotal, decimales) * round(linea.discount, decimales) / round(100.00, decimales), decimales)
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
				LineaDetalle.append(MontoDescuento)

				NaturalezaDescuento = etree.Element('NaturalezaDescuento')
				NaturalezaDescuento.text = linea.discount_note or 'Descuento Comercial'
				LineaDetalle.append(NaturalezaDescuento)

			SubTotal = etree.Element('SubTotal')
			SubTotal.text = str(round(linea.price_subtotal, decimales))
			LineaDetalle.append(SubTotal)

			if linea.tax_ids_after_fiscal_position:
				for impuesto in linea.tax_ids_after_fiscal_position:

					if impuesto.tax_code != 'IS':
						Impuesto = etree.Element('Impuesto')

						Codigo = etree.Element('Codigo')

						Codigo.text = impuesto.tax_code
						Impuesto.append(Codigo)

						if linea.product_id.type == 'service':
							raise UserError('No se puede aplicar impuesto de ventas a los servicios')

						Tarifa = etree.Element('Tarifa')
						Tarifa.text = str(round(impuesto.amount, decimales))
						Impuesto.append(Tarifa)

						Monto = etree.Element('Monto')
						monto = round(round(linea.price_subtotal, decimales) * round(impuesto.amount, decimales) / round(100.00, decimales), decimales)
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
				montoTotalLinea -= montoTotalLinea * 10.0 / (100.0 + sum(linea.tax_ids_after_fiscal_position.mapped('amount')))
			MontoTotalLinea.text = str(round(montoTotalLinea, decimales))
			LineaDetalle.append(MontoTotalLinea)

			DetalleServicio.append(LineaDetalle)
			indice += 1

		if servicio:
			LineaDetalle = etree.Element('LineaDetalle')

			NumeroLinea = etree.Element('NumeroLinea')
			NumeroLinea.text = '%s' % indice  # indice
			LineaDetalle.append(NumeroLinea)

			Cantidad = etree.Element('Cantidad')
			Cantidad.text = '1'
			LineaDetalle.append(Cantidad)

			UnidadMedida = etree.Element('UnidadMedida')
			UnidadMedida.text = 'Unid'

			LineaDetalle.append(UnidadMedida)

			Detalle = etree.Element('Detalle')
			Detalle.text = 'Cargo de Servicio (10%)'
			LineaDetalle.append(Detalle)

			PrecioUnitario = etree.Element('PrecioUnitario')
			PrecioUnitario.text = str(round((order.amount_total - order.amount_tax) * 10.0 / 100.0, decimales))
			LineaDetalle.append(PrecioUnitario)

			MontoTotal = etree.Element('MontoTotal')
			MontoTotal.text = PrecioUnitario.text
			LineaDetalle.append(MontoTotal)

			SubTotal = etree.Element('SubTotal')
			SubTotal.text = PrecioUnitario.text
			LineaDetalle.append(SubTotal)

			MontoTotalLinea = etree.Element('MontoTotalLinea')
			MontoTotalLinea.text = PrecioUnitario.text
			LineaDetalle.append(MontoTotalLinea)

			DetalleServicio.append(LineaDetalle)

			totalMercanciasExentas += round((order.amount_total - order.amount_tax) * 10.0 / 100.0, decimales)


		Documento.append(DetalleServicio)

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
		totalVenta = order.amount_total - order.amount_tax
		if servicio:
			totalVenta += (order.amount_total - order.amount_tax) * 10.0 / 100.0
		TotalVenta.text = str(round(totalVenta, decimales))
		ResumenFactura.append(TotalVenta)

		if totalDescuentosServiciosGravados + totalDescuentosMercanciasGravadas + totalDescuentosServiciosExentos + totalDescuentosMercanciasExentas:
			TotalDescuentos = etree.Element('TotalDescuentos')
			TotalDescuentos.text = str(round(totalDescuentosServiciosGravados + totalDescuentosMercanciasGravadas + totalDescuentosServiciosExentos + totalDescuentosMercanciasExentas, decimales))
			ResumenFactura.append(TotalDescuentos)

		TotalVentaNeta = etree.Element('TotalVentaNeta')
		totalVentaNeta = order.amount_total - order.amount_tax
		if servicio:
			totalVentaNeta += (order.amount_total - order.amount_tax) * 10.0 / 100.0
		TotalVentaNeta.text = str(round(totalVentaNeta, decimales))
		ResumenFactura.append(TotalVentaNeta)

		if order.amount_tax:
			TotalImpuesto = etree.Element('TotalImpuesto')
			totalImpuesto = order.amount_tax
			if servicio:
				totalImpuesto -= (order.amount_total - order.amount_tax) * 10.0 / 100.0
			TotalImpuesto.text = str(round(totalImpuesto, decimales))
			ResumenFactura.append(TotalImpuesto)

		TotalComprobante = etree.Element('TotalComprobante')
		TotalComprobante.text = str(round(order.amount_total, decimales))
		ResumenFactura.append(TotalComprobante)

		Documento.append(ResumenFactura)

		# Normativa
		Normativa = etree.Element('Normativa')

		NumeroResolucion = etree.Element('NumeroResolucion')
		NumeroResolucion.text = 'DGT-R-48-2016'
		Normativa.append(NumeroResolucion)

		FechaResolucion = etree.Element('FechaResolucion')
		FechaResolucion.text = '07-10-2016 08:00:00'
		Normativa.append(FechaResolucion)


		Documento.append(Normativa)

		return Documento

	def _get_xml_FE_NC_ND(self, invoice):

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

		# FacturaElectronica 4.2 y Nota de Crédito 4.2
		decimales = 2

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
		MedioPago.text = invoice.payment_methods_id.sequence if invoice.payment_methods_id else '01'
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

		for indice, linea in enumerate(invoice.invoice_line_ids.sorted(lambda l: l.sequence)):
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
			Detalle.text = linea.product_id.name
			LineaDetalle.append(Detalle)

			PrecioUnitario = etree.Element('PrecioUnitario')
			PrecioUnitario.text = str(round(linea.price_unit, decimales))
			LineaDetalle.append(PrecioUnitario)

			MontoTotal = etree.Element('MontoTotal')
			montoTotal = round(linea.price_unit, decimales) * round(linea.quantity, decimales)
			MontoTotal.text = str(round(montoTotal, decimales))

			LineaDetalle.append(MontoTotal)

			if linea.discount:
				MontoDescuento = etree.Element('MontoDescuento')
				montoDescuento = round(round(montoTotal, decimales) * round(linea.discount, decimales) / round(100.00, decimales), decimales)
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
				LineaDetalle.append(MontoDescuento)

				NaturalezaDescuento = etree.Element('NaturalezaDescuento')
				NaturalezaDescuento.text = linea.discount_note or 'Descuento Comercial'
				LineaDetalle.append(NaturalezaDescuento)

			SubTotal = etree.Element('SubTotal')
			SubTotal.text = str(round(linea.price_subtotal, decimales))
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
					Tarifa.text = str(round(impuesto.amount, decimales))
					Impuesto.append(Tarifa)

					Monto = etree.Element('Monto')
					monto = round(round(linea.price_subtotal, decimales) * round(impuesto.amount, decimales) / round(100.00, decimales), decimales)
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
			MontoTotalLinea.text = str(round(linea.price_total, decimales))
			LineaDetalle.append(MontoTotalLinea)

			DetalleServicio.append(LineaDetalle)

		Documento.append(DetalleServicio)

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
		TotalVenta.text = str(round(invoice.amount_untaxed + totalDescuentosServiciosGravados + totalDescuentosMercanciasGravadas + totalDescuentosServiciosExentos + totalDescuentosMercanciasExentas, decimales))
		ResumenFactura.append(TotalVenta)

		if totalDescuentosServiciosGravados + totalDescuentosMercanciasGravadas + totalDescuentosServiciosExentos + totalDescuentosMercanciasExentas:
			TotalDescuentos = etree.Element('TotalDescuentos')
			TotalDescuentos.text = str(round(totalDescuentosServiciosGravados + totalDescuentosMercanciasGravadas + totalDescuentosServiciosExentos + totalDescuentosMercanciasExentas, decimales))
			ResumenFactura.append(TotalDescuentos)

		TotalVentaNeta = etree.Element('TotalVentaNeta')
		TotalVentaNeta.text = str(round(invoice.amount_untaxed, decimales))
		ResumenFactura.append(TotalVentaNeta)

		if invoice.amount_tax:
			TotalImpuesto = etree.Element('TotalImpuesto')
			# TotalImpuesto.text = str(round(invoice.amount_tax, decimales))
			TotalImpuesto.text = str(round(totalImpuesto, decimales))
			ResumenFactura.append(TotalImpuesto)

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
			if not invoice.refund_invoice_id.date_issuance:
				now_utc = datetime.now(pytz.timezone('UTC'))
				now_cr = now_utc.astimezone(pytz.timezone('America/Costa_Rica'))
				invoice.refund_invoice_id.fecha = now_cr.strftime('%Y-%m-%d %H:%M:%S')
				invoice.refund_invoice_id.date_issuance = now_cr.strftime("%Y-%m-%dT%H:%M:%S-06:00")

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

		return Documento

	@api.model
	def _get_xml_MR(self, invoice):

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

		now_utc = datetime.now(pytz.timezone('UTC'))
		now_cr = now_utc.astimezone(pytz.timezone('America/Costa_Rica'))
		date_cr = now_cr.strftime("%Y-%m-%dT%H:%M:%S-06:00")

		# FechaEmisionDoc
		FechaEmisionDoc = etree.Element('FechaEmisionDoc')
		FechaEmisionDoc.text = date_cr # date_cr
		Documento.append(FechaEmisionDoc)

		# Mensaje
		Mensaje = etree.Element('Mensaje')
		Mensaje.text = invoice.state_invoice_partner # state_invoice_partner
		Documento.append(Mensaje)

		# DetalleMensaje
		DetalleMensaje = etree.Element('DetalleMensaje')
		DetalleMensaje.text = 'Mensaje de ' + emisor.name # emisor.name
		Documento.append(DetalleMensaje)

		if TotalImpuesto is not None:
			# MontoTotalImpuesto
			MontoTotalImpuesto = etree.Element('MontoTotalImpuesto')
			MontoTotalImpuesto.text = TotalImpuesto.text # TotalImpuesto.text
			Documento.append(MontoTotalImpuesto)

		# TotalFactura
		TotalFactura = etree.Element('TotalFactura')
		TotalFactura.text = TotalComprobante.text # TotalComprobante.text
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

		return Documento

