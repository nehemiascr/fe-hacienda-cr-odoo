# -*- coding: utf-8 -*-

from odoo import fields, models, api
from odoo.exceptions import UserError
import requests
import json
import copy
import datetime
from lxml import etree
import logging
import re
import random
import os
import subprocess
import base64
import pytz
from . import functions

_logger = logging.getLogger(__name__)


class FacturacionElectronica(models.TransientModel):
	_name = 'facturacion_electronica'

	token = fields.Text('token de sesión con el sistema del Ministerio de Hacienda')

	@api.model
	def conexion_con_hacienda(self):
		return True if self.get_token() else False

	@api.model
	def get_token(self):

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
			tipo = '03' # Nota de Crédito
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
	def get_clave(self, invoice):

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
	def enviar_factura(self, invoice):

		if self.env.user.company_id.frm_ws_ambiente == 'api-stag':
			url = 'https://api.comprobanteselectronicos.go.cr/recepcion-sandbox/v1/recepcion/'
		elif self.env.user.company_id.frm_ws_ambiente == 'api-prod':
			url = 'https://api.comprobanteselectronicos.go.cr/recepcion/v1/recepcion/'

		xml = base64.b64decode(invoice.xml_comprobante)
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
		comprobante['emisor']['tipoIdentificacion'] = Emisor.find('Identificacion').find('Tipo').text
		comprobante['emisor']['numeroIdentificacion'] = Emisor.find('Identificacion').find('Numero').text
		if Receptor is not None and Receptor.find('Identificacion') is not None:
			comprobante['receptor'] = {}
			comprobante['receptor']['tipoIdentificacion'] = Receptor.find('Identificacion').find('Tipo').text
			comprobante['receptor']['numeroIdentificacion'] = Receptor.find('Identificacion').find('Numero').text

		comprobante['comprobanteXml'] = base64.b64encode(xml).decode('utf-8')

		token = self.get_token()
		if not token:
			_logger.info('No hay conexión con hacienda')
			return False

		headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer {}'.format(token)}

		try:
			response = requests.post(url, data=json.dumps(comprobante), headers=headers)

		except requests.exceptions.RequestException as e:
			_logger.info('Exception %s' % e)
			raise Exception(e)

		if response.status_code == 202:
			_logger.info('factura recibida por hacienda %s' % response.__dict__)
			return True
		elif response.status_code == 301:
			_logger.info('Error 301 %s' % response.headers['X-Error-Cause'])
			return False
		elif response.status_code == 400:
			_logger.info('Error 400 %s' % response.headers['X-Error-Cause'])
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
		attachment = self.env['ir.attachment'].search(
			[('res_model', '=', 'account.invoice'), ('res_id', '=', invoice.id),
			 ('res_field', '=', 'xml_comprobante')], limit=1)
		attachment.name = invoice.fname_xml_comprobante
		attachment.datas_fname = invoice.fname_xml_comprobante

		attachment_resp = self.env['ir.attachment'].search(
			[('res_model', '=', 'account.invoice'), ('res_id', '=', invoice.id),
			 ('res_field', '=', 'xml_respuesta_tributacion')], limit=1)
		attachment_resp.name = invoice.fname_xml_respuesta_tributacion
		attachment_resp.datas_fname = invoice.fname_xml_respuesta_tributacion

		email_template.attachment_ids = [(6, 0, [attachment.id, attachment_resp.id])]

		email_template.with_context(type='binary', default_type='binary').send_mail(invoice.id,
																					raise_exception=False,
																					force_send=True)  # default_type='binary'

		email_template.attachment_ids = [(5)]


	def get_mensaje(self, invoice):
		_logger.info('\n\n\n\n\n\n%s' % base64.b64decode(invoice.xml_comprobante))
		_logger.info('\n\n\n\n\n\n%s' % base64.b64decode(invoice.xml_respuesta_tributacion))

	@api.model
	def consultar_factura(self, invoice):

		if invoice.company_id.frm_ws_ambiente == 'api-stag':
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
			_logger.info('no vamos a continuar, factura sin xml ni clave')
			return False

		token = self.get_token()
		if not token:
			_logger.info('No hay conexión con hacienda')
			return False

		headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer {}'.format(token)}

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
			return False
		elif response.status_code != 200:
			_logger.info('no vamos a continuar, algo inesperado sucedió %s' % response.__dict__)
			return False

		respuesta = response.json()

		_logger.info('respuesta de hacienda\njson %s\nresponse %s\ndict %s\n' % (respuesta, response, response.__dict__))

		if 'ind-estado' not in respuesta:
			_logger.info('no vamos a continuar, no se entiende la respuesta de hacienda')
			return False

		# Se actualiza la factura con la respuesta de hacienda
		invoice.state_tributacion = respuesta['ind-estado']
		
		if 'respuesta-xml' in respuesta:
			invoice.fname_xml_respuesta_tributacion = 'respuesta_' + respuesta['clave'] + '.xml'
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

		# _logger.info('xml frimado from file %s' % xml)

		xml_encoded = base64.b64encode(xml).decode('utf-8')

		# _logger.info('xml firmado encoded\n%s' % xml_encoded)
		#
		# _logger.info('xml firmado decoded to show\n%s' % base64.b64decode(xml_encoded))
		#
		# _logger.info('xml firmado decoded2\n%s' % base64.b64decode(xml_encoded).decode())

		return xml_encoded


	@api.model
	def _validahacienda(self, max_invoices=10):  # cron
		invoices = self.env['account.invoice'].search([('type', 'in', ('out_invoice', 'out_refund')),
													   ('state', 'in', ('open', 'paid')),
													   ('date_invoice', '>=', '2018-10-01'),
													   ('state_tributacion', '=', False)], limit=max_invoices)
		total_invoices = len(invoices)
		current_invoice = 0
		_logger.error('Valida Hacienda - Invoices to check: %s', total_invoices)

		for invoice in invoices:

			current_invoice += 1
			_logger.error('Valida Hacienda - Invoice %s / %s', current_invoice, total_invoices)

			if not invoice.number.isdigit():
				_logger.error('Valida Hacienda - Error de Consecutivo - skipped Invoice %s', invoice.number)
				continue

			if not invoice.xml_comprobante:

				comprobante = self.get_xml(invoice)

				if not comprobante:
					_logger.error('Valida Hacienda - Error de creación de comprobante - skipped Invoice %s', invoice.number)
					continue

				invoice.xml_comprobante = comprobante
				invoice.fname_xml_comprobante = invoice.number_electronic + '.xml'

			token = self.get_token()

			if token:
				if self.enviar_factura(invoice):
					if self.consultar_factura(invoice):
						self.enviar_email(invoice)

		_logger.error('Valida Hacienda - Finalizado Exitosamente')

	@api.model
	def _consultahacienda(self, max_invoices=10):  # cron

		invoices = self.env['account.invoice'].search(
			[('type', 'in', ('out_invoice', 'out_refund')), ('state', 'in', ('open', 'paid')),
			 ('state_tributacion', 'in', ('recibido', 'procesando'))])

		total_invoices = len(invoices)
		current_invoice = 0
		_logger.error('Consulta Hacienda - Invoices to check: %s', total_invoices)

		for invoice in invoices:

			current_invoice += 1
			_logger.error('Consulta Hacienda - Invoice %s / %s', current_invoice, total_invoices)

			self.consultar_factura(invoice)

		_logger.error('Consulta Hacienda - Finalizado Exitosamente')



	@api.model
	def get_xml(self, invoice):

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

		if invoice.type == 'out_invoice':
			documento = 'FacturaElectronica' # Factura Electrónica
			xmlns = 'https://tribunet.hacienda.go.cr/docs/esquemas/2017/v4.2/facturaElectronica'
			schemaLocation = 'https://tribunet.hacienda.go.cr/docs/esquemas/2017/v4.2/facturaElectronica  https://tribunet.hacienda.go.cr/docs/esquemas/2017/v4.2/FacturaElectronica_V.4.2.xsd'

		elif invoice.type == 'out_refund':
			documento = 'NotaCreditoElectronica' # Nota de Crédito
			xmlns = 'https://tribunet.hacienda.go.cr/docs/esquemas/2017/v4.2/notaCreditoElectronica'
			schemaLocation = 'https://tribunet.hacienda.go.cr/docs/esquemas/2017/v4.2/notaCreditoElectronica  https://tribunet.hacienda.go.cr/docs/esquemas/2017/v4.2/NotaCreditoElectronica_V4.2.xsd'

		# FacturaElectronica 4.2
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

		telefono = emisor.partner_id.phone or emisor.partner_id.mobile
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

		Documento.append(Emisor)

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
				elif receptor.identification_id.code == '03' and (
						len(identificacion) != 11 or len(identificacion) != 12):
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
		MedioPago.text = '01'
		Documento.append(MedioPago)

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
					# Codigo.text = impuesto.code
					Codigo.text = '01'
					Impuesto.append(Codigo)

					if linea.product_id.type == 'service' and impuesto.tax_code != '07':
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

		Documento.append(DetalleServicio)

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
