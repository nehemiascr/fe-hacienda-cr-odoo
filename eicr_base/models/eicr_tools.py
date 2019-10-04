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
	def datetime_str(self, datetime_obj=None):
		if datetime_obj is None:
			now_utc = datetime.now(pytz.timezone('UTC'))
			datetime_obj = now_utc.astimezone(pytz.timezone('America/Costa_Rica'))
		return datetime_obj.strftime(EICR_DATE_FORMAT)

	@api.model
	@api.model
	def datetime_obj(self, datetime_str=None):
		if datetime_str is None:
			datetime_str = self.datetime_str()
		return datetime.strptime(datetime_str,EICR_DATE_FORMAT)

	def update_company_info(self, company_id):
		info = self.env['eicr.hacienda'].get_info_contribuyente(company_id.vat)
		if info:
			company_id.eicr_id_type = self.env['eicr.identification_type'].search([('code', '=', info['tipoIdentificacion'])])
			actividades = [a['codigo'] for a in info['actividades'] if a['estado'] == 'A']
			company_id.eicr_activity_ids = self.env['eicr.economic_activity'].search([('code', 'in', actividades)])

			if not company_id.state_id:
				company_id.state_id = self.env.ref('l10n_cr.state_SJ')
			if not company_id.county_id:
				company_id.county_id = self.env.ref('l10n_cr_country_codes.county_San José_SJ')
			if not company_id.district_id:
				company_id.district_id = self.env.ref('l10n_cr_country_codes.district_Carmen_San José_SJ')
			if not company_id.street:
				company_id.street = 'Sin Otras Señas'

	@api.model
	def actualizar_info(self, partner_id):
		_logger.info('selff %s name %s' % (partner_id, partner_id.name))
		info = self.env['eicr.hacienda'].get_info_contribuyente(partner_id.vat)
		if info:
			# tipo de identificación
			partner_id.eicr_id_type = self.env['eicr.identification_type'].search([('code', '=', info['tipoIdentificacion'])])
			if info['tipoIdentificacion'] in ('01', '03', '04'):
				partner_id.is_company = False
			elif info['tipoIdentificacion'] in ('02'):
				partner_id.is_company = True
			# actividad económica
			actividades = [a['codigo'] for a in info['actividades'] if a['estado'] == 'A']
			partner_id.eicr_activity_ids = self.env['eicr.economic_activity'].search([('code', 'in', actividades)])
			# nombre
			if partner_id.name in ('', 'My Company', None, False): partner_id.name = info['nombre']
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
				object.eicr_documento_fname = 'MensajeReceptor_' + object.eicr_clave + '.xml'
				object.eicr_state = 'pendiente'
			else:
				object.eicr_state = 'na'

	@api.model
	def _es_mensaje_aceptacion(self, object):
		if object.eicr_documento_tipo == self.env.ref('eicr_base.MensajeReceptor_V_4_3'):
			return True
		else:
			return False

	@api.model
	def eicr_habilitado(self, company_id):
		return False if company_id.eicr_environment == 'disabled' else True

	@api.model
	def _enviar_email(self, object):
		if object.eicr_state != 'aceptado':
			_logger.info('documento %s estado %s, no vamos a enviar el email' % (object, object.eicr_state))
			return False

		if not object.partner_id:
			_logger.info('documento %s sin cliente, no vamos a enviar el email' % object)
			return False

		email_to = object.partner_id.email_facturas or object.partner_id.email
		_logger.info('emailing to %s' % email_to)
		if not email_to:
			_logger.info('Cliente %s sin email, no vamos a enviar el email' % object.partner_id)
			return False

		if object._name == 'account.invoice' or object._name == 'hr.expense':
			email_template = self.env.ref('account.email_template_edi_invoice', False)
		if object._name == 'pos.order':
			email_template = self.env.ref('cr_pos_electronic_invoice.email_template_pos_invoice', False)

		# agregamos los adjuntos solo si el comprobante fue aceptado
		if self.eicr_state in ('aceptado'):
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
		else:
			email_template.attachment_ids = [(5)]



		email_template.with_context(type='binary', default_type='binary').send_mail(object.id,
																					raise_exception=False,
																					force_send=True,
																					email_values={
																						'email_to': email_to})  # default_type='binary'

		email_template.attachment_ids = [(5)]

		if object._name == 'account.invoice': object.sent = True

	@api.model
	def firmar_xml(self, xml, company_id):

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
	def get_clave_from_xml(self, xml):
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
	def validar_receptor(self, partner_id):
		if partner_id in (None, False): return False
		if not partner_id.vat: return False
		identificacion = re.sub('[^0-9]', '', partner_id.vat)
		if not partner_id.eicr_id_type: partner_id.action_update_info()
		if not partner_id.eicr_id_type: return False

		if partner_id.eicr_id_type.code == '01' and len(identificacion) != 9:
			return False
		elif partner_id.eicr_id_type.code == '02' and len(identificacion) != 10:
			return False
		elif partner_id.eicr_id_type.code == '03' and not (len(identificacion) == 11 or len(identificacion) == 12):
			return False
		elif partner_id.eicr_id_type.code == '04' and len(identificacion) != 10:
			return False
		elif partner_id.eicr_id_type.code == '05':
			return False

		return True

	@api.model
	def validar_emisor(self, company_id):
		if not company_id.vat:
			raise UserError('Debe de digitar el número de identificación de %s en el perfil de la compañía para poder facturar.' % company_id.name)
		if not company_id.eicr_id_type: self.env['eicr.tools'].update_company_info(company_id)
		identificacion = re.sub('[^0-9]', '', company_id.vat)
		if company_id.eicr_id_type.code == '01' and len(identificacion) != 9:
			raise UserError('La Cédula Física del emisor debe de tener 9 dígitos')
		elif company_id.eicr_id_type.code == '02' and len(identificacion) != 10:
			raise UserError('La Cédula Jurídica del emisor debe de tener 10 dígitos')
		elif company_id.eicr_id_type.code == '03' and not (
				len(identificacion) == 11 or len(identificacion) == 12):
			raise UserError('La identificación DIMEX del emisor debe de tener 11 o 12 dígitos')
		elif company_id.eicr_id_type.code == '04' and len(identificacion) != 10:
			raise UserError('La identificación NITE del emisor debe de tener 10 dígitos')
		return True

	@api.model
	def get_nodo_emisor(self, company_id):
		self.validar_emisor(company_id)
		# Emisor
		Emisor = etree.Element('Emisor')

		Nombre = etree.Element('Nombre')
		Nombre.text = company_id.name
		Emisor.append(Nombre)

		Identificacion = etree.Element('Identificacion')

		Tipo = etree.Element('Tipo')
		Tipo.text = company_id.eicr_id_type.code
		Identificacion.append(Tipo)

		Numero = etree.Element('Numero')
		Numero.text = re.sub('[^0-9]', '', company_id.vat)
		Identificacion.append(Numero)

		Emisor.append(Identificacion)

		Ubicacion = etree.Element('Ubicacion')

		Provincia = etree.Element('Provincia')
		Provincia.text = company_id.state_id.code if company_id.state_id else self.env.ref('l10n_cr.state_SJ').code
		Ubicacion.append(Provincia)

		Canton = etree.Element('Canton')
		Canton.text = company_id.county_id.code if company_id.county_id else self.env.ref('l10n_cr_country_codes.county_San José_SJ').code
		Ubicacion.append(Canton)

		Distrito = etree.Element('Distrito')
		Distrito.text = company_id.district_id.code if company_id.district_id else self.env.ref('l10n_cr_country_codes.district_Carmen_San José_SJ').code
		Ubicacion.append(Distrito)

		if company_id.partner_id.neighborhood_id:
			Barrio = etree.Element('Barrio')
			Barrio.text = company_id.neighborhood_id.code
			Ubicacion.append(Barrio)

		OtrasSenas = etree.Element('OtrasSenas')
		OtrasSenas.text = company_id.street or 'Sin otras señas'
		Ubicacion.append(OtrasSenas)

		Emisor.append(Ubicacion)

		telefono = re.sub('[^0-9]', '', company_id.phone)
		if telefono and len(telefono) >= 8 and len(telefono) <= 20:
			Telefono = etree.Element('Telefono')

			CodigoPais = etree.Element('CodigoPais')
			CodigoPais.text = '506'
			Telefono.append(CodigoPais)

			NumTelefono = etree.Element('NumTelefono')
			NumTelefono.text = telefono[:8]

			Telefono.append(NumTelefono)

			Emisor.append(Telefono)

		if not company_id.email or not re.match('^[(a-z0-9\_\-\.)]+@[(a-z0-9\_\-\.)]+\.[(a-z)]{2,15}$', company_id.email.lower()):
			raise UserError('El correo electrónico del emisor es inválido.')

		CorreoElectronico = etree.Element('CorreoElectronico')
		CorreoElectronico.text = company_id.email.lower()
		Emisor.append(CorreoElectronico)

		return Emisor

	@api.model
	def get_nodo_receptor(self, partner_id):
		if not self.validar_receptor(partner_id): return False
		# Receptor
		Receptor = etree.Element('Receptor')

		Nombre = etree.Element('Nombre')
		Nombre.text = partner_id.name
		Receptor.append(Nombre)

		Identificacion = etree.Element('Identificacion')

		Tipo = etree.Element('Tipo')
		Tipo.text = partner_id.eicr_id_type.code
		Identificacion.append(Tipo)

		Numero = etree.Element('Numero')
		Numero.text = re.sub('[^0-9]', '', partner_id.vat)
		Identificacion.append(Numero)

		Receptor.append(Identificacion)

		if partner_id.state_id and partner_id.county_id and partner_id.district_id and partner_id.street:
			Ubicacion = etree.Element('Ubicacion')

			Provincia = etree.Element('Provincia')
			Provincia.text = partner_id.state_id.code
			Ubicacion.append(Provincia)

			Canton = etree.Element('Canton')
			Canton.text = partner_id.county_id.code
			Ubicacion.append(Canton)

			Distrito = etree.Element('Distrito')
			Distrito.text = partner_id.district_id.code
			Ubicacion.append(Distrito)

			if partner_id.neighborhood_id:
				Barrio = etree.Element('Barrio')
				Barrio.text = partner_id.neighborhood_id.code
				Ubicacion.append(Barrio)

			OtrasSenas = etree.Element('OtrasSenas')
			OtrasSenas.text = partner_id.street
			Ubicacion.append(OtrasSenas)

			Receptor.append(Ubicacion)

		telefono = partner_id.phone or partner_id.mobile
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

		email = partner_id.email_facturas or partner_id.email
		if email and re.match('^[(a-z0-9\_\-\.)]+@[(a-z0-9\_\-\.)]+\.[(a-z)]{2,15}$', email.lower()):
			CorreoElectronico = etree.Element('CorreoElectronico')
			CorreoElectronico.text = email
			Receptor.append(CorreoElectronico)

		return Receptor

	@api.model
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

	@api.model
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
			tipo = self.env['eicr.identification_type'].search([('code', '=', emisor_tipo)])

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
																		  'eicr_id_type': tipo.id,
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

	@api.model
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
			tipo = self.env['eicr.identification_type'].search([('code', '=', emisor_tipo)])

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
																		  'eicr_id_type': tipo.id,
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

	@api.model
	def get_partner_emisor(self, base64_decoded_xml):
		xml = base64.b64decode(base64_decoded_xml)
		factura = etree.tostring(etree.fromstring(xml)).decode()
		factura = etree.fromstring(re.sub(' xmlns="[^"]+"', '', factura, count=1))
		Emisor = factura.find('Emisor')
		vat = Emisor.find('Identificacion').find('Numero').text
		return self.env['res.partner'].search([('vat', '=', vat)])
