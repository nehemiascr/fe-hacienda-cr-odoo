# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError
import xml.etree.ElementTree as ET
import base64
import re
import datetime
import pytz
import requests
from dateutil.parser import parse
from . import functions
from lxml import etree
import logging

_logger = logging.getLogger(__name__)


class AccountInvoiceElectronic(models.Model):
	_inherit = "account.invoice"

	number_electronic = fields.Char(string="Número electrónico", copy=False, index=True)
	date_issuance = fields.Char(string="Fecha de emisión", copy=False)
	fecha = fields.Datetime('Fecha de Emisión', readonly=True, default=fields.Datetime.now(), copy=False)
	state_send_invoice = fields.Selection([('aceptado', 'Aceptado'),
                                           ('rechazado', 'Rechazado'),
                                           ('error', 'Error'),
                                           ('ne', 'No Encontrado'),
                                           ('procesando', 'Procesando')],
                                          'Estado FE Proveedor', copy=False)
	state_tributacion = fields.Selection([('aceptado', 'Aceptado'),
										  ('rechazado', 'Rechazado'),
										  ('recibido', 'Recibido'),
		 								  ('error', 'Error'),
										  ('procesando', 'Procesando'),
										  ('na', 'No Aplica'),
										  ('ne', 'No Encontrado')],
										 'Estado FE', copy=False)
	state_invoice_partner = fields.Selection([('1', 'Aceptado'),
											  ('2', 'Aceptacion parcial'),
											  ('3', 'Rechazado'),],
											 'Respuesta del Cliente', copy=False)
	reference_code_id = fields.Many2one(comodel_name="reference.code", string="Código de referencia", copy=False)
	payment_methods_id = fields.Many2one(comodel_name="payment.methods", string="Métodos de Pago")
	invoice_id = fields.Many2one(comodel_name="account.invoice", string="Documento de referencia", copy=False)
	xml_respuesta_tributacion = fields.Binary(string="Respuesta Tributación XML", copy=False, attachment=True)
	fname_xml_respuesta_tributacion = fields.Char(string="Nombre de archivo XML Respuesta Tributación", copy=False)

	respuesta_tributacion = fields.Text(string="Mensaje en la Respuesta de Tributación", readonly=True, copy=False)
	xml_comprobante = fields.Binary(string="Comprobante XML", copy=False, attachment=True)
	fname_xml_comprobante = fields.Char(string="Nombre de archivo Comprobante XML", copy=False, attachment=True)
	xml_supplier_approval = fields.Binary(string="XML Proveedor", copy=False, attachment=True)
	fname_xml_supplier_approval = fields.Char(string="Nombre de archivo Comprobante XML proveedor", copy=False, attachment=True)
	amount_tax_electronic_invoice = fields.Monetary(string='Total de impuestos FE', readonly=True)
	amount_total_electronic_invoice = fields.Monetary(string='Total FE', readonly=True)
	tipo_comprobante = fields.Char(string='Tipo Comprobante', readonly=True, )

	state_email = fields.Selection([('no_email', 'Sin cuenta de correo'),
									('sent', 'Enviado'),
									('fe_error', 'Error FE')], 'Estado email', copy=False)


	_sql_constraints = [
		('number_electronic_uniq', 'unique (number_electronic)', "La clave de comprobante debe ser única"),
	]

	@api.onchange('xml_supplier_approval')
	def _onchange_xml_supplier_approval(self):
		_logger.info('cargando xml de proveedor')
		if self.xml_supplier_approval:
			root = ET.fromstring(
				re.sub(' xmlns="[^"]+"', '', base64.b64decode(self.xml_supplier_approval).decode("utf-8"), count=1))  # quita el namespace de los elementos

			if not root.findall('Clave'):
				return {'value': {'xml_supplier_approval': False},
						'warning': {'title': 'Atención',
									'message': 'El archivo xml no contiene el nodo Clave. Por favor cargue un archivo con el formato correcto.'
									}
						}
			if not root.findall('FechaEmision'):
				return {'value': {'xml_supplier_approval': False},
						'warning': {'title': 'Atención',
									'message': 'El archivo xml no contiene el nodo FechaEmision. Por favor cargue un archivo con el formato correcto.'
									}
						}
			if not root.findall('Emisor'):
				return {'value': {'xml_supplier_approval': False},
						'warning': {'title': 'Atención',
									'message': 'El archivo xml no contiene el nodo Emisor. Por favor cargue un archivo con el formato correcto.'
									}
						}
			if not root.findall('Emisor')[0].findall('Identificacion'):
				return {'value': {'xml_supplier_approval': False},
						'warning': {'title': 'Atención',
									'message': 'El archivo xml no contiene el nodo Identificacion. Por favor cargue un archivo con el formato correcto.'
									}
						}
			if not root.findall('Emisor')[0].findall('Identificacion')[0].findall('Tipo'):
				return {'value': {'xml_supplier_approval': False},
						'warning': {'title': 'Atención',
									'message': 'El archivo xml no contiene el nodo Tipo. Por favor cargue un archivo con el formato correcto.'
									}
						}
			if not root.findall('Emisor')[0].findall('Identificacion')[0].findall('Numero'):
				return {'value': {'xml_supplier_approval': False},
						'warning': {'title': 'Atención',
									'message': 'El archivo xml no contiene el nodo Numero. Por favor cargue un archivo con el formato correcto.'
									}
						}
			if not (root.findall('ResumenFactura') and root.findall('ResumenFactura')[0].findall('TotalComprobante')):
				return {'value': {'xml_supplier_approval': False},
						'warning': {'title': 'Atención',
									'message': 'No se puede localizar el nodo TotalComprobante. Por favor cargue un archivo con el formato correcto.'
									}
						}

			xml = base64.b64decode(self.xml_supplier_approval)
			_logger.info('xml %s' % xml)

			factura = etree.tostring(etree.fromstring(xml)).decode()
			factura = etree.fromstring(re.sub(' xmlns="[^"]+"', '', factura, count=1))

			Clave = factura.find('Clave')
			NumeroConsecutivo = factura.find('NumeroConsecutivo')
			FechaEmision = factura.find('FechaEmision')
			Emisor = factura.find('Emisor')
			Receptor = factura.find('Receptor')

			CondicionVenta = factura.find('CondicionVenta')
			PlazoCredito = factura.find('PlazoCredito')

			emisor = Emisor.find('Identificacion').find('Numero').text

			_logger.info('buscando %s' % emisor)
			proveedor = self.env['res.partner'].search([('vat', '=', emisor)])

			_logger.info('resultado %s' % proveedor)

			if not proveedor:
				ctx = self.env.context.copy()
				ctx.pop('default_type', False)
				tipo_de_identificacion = self.env['identification.type'].search([('code','=', Emisor.find('Identificacion').find('Tipo').text)])

				if tipo_de_identificacion.code == '02':
					is_company = True
				else:
					is_company = False

				proveedor = self.env['res.partner'].with_context(ctx).create({'name': Emisor.find('Nombre').text,
																			  'email': Emisor.find('CorreoElectronico').text,
																			  'phone_code': Emisor.find('Telefono').find('CodigoPais').text,
																			  'phone': Emisor.find('Telefono').find('NumTelefono').text,
																			  'vat':emisor,
																			  'identification_id': tipo_de_identificacion.id,
																			  'is_company': is_company,
																			  'customer': False,
																			  'supplier': True})
				_logger.info('nuevo proveedor %s' % proveedor)

			self.partner_id = proveedor
			_logger.info('fecha %s' % FechaEmision.text)
			self.date_invoice = FechaEmision.text

			_logger.info('NumeroConsecutivo %s' % NumeroConsecutivo)
			self.reference = NumeroConsecutivo.text

			if CondicionVenta.text == '02':
				fecha_de_factura = datetime.datetime.strptime(self.date_invoice, '%Y-%m-%d')
				plazo = int(PlazoCredito.text)
				fecha_de_vencimiento = fecha_de_factura + datetime.timedelta(days=plazo)
				self.date_due = fecha_de_vencimiento.strftime('%Y-%m-%d')
				_logger.info('date_due %s' % self.date_due)


		else:
			self.state_tributacion = False
			self.state_send_invoice = False
			self.xml_supplier_approval = False
			self.fname_xml_supplier_approval = False
			self.xml_respuesta_tributacion = False
			self.fname_xml_respuesta_tributacion = False
			self.date_issuance = False
			self.number_electronic = False
			self.state_invoice_partner = False




	@api.multi
	def charge_xml_data(self):
		if (self.type == 'out_invoice' or self.type == 'out_refund') and self.xml_comprobante:
			# remove any character not a number digit in the invoice number
			self.number = re.sub(r"[^0-9]+", "", self.number)
			self.currency_id = self.env['res.currency'].search(
				[('name', '=', root.find('ResumenFactura').find('CodigoMoneda').text)], limit=1).id

			root = ET.fromstring(re.sub(' xmlns="[^"]+"', '', base64.b64decode(self.xml_comprobante).decode("utf-8"),
										count=1))  # quita el namespace de los elementos

			partner_id = root.findall('Receptor')[0].find('Identificacion')[1].text
			date_issuance = root.findall('FechaEmision')[0].text
			consecutive = root.findall('NumeroConsecutivo')[0].text

			partner = self.env['res.partner'].search(
				[('vat', '=', partner_id)])
			if partner and self.partner_id.id != partner.id:
				raise UserError(
					'El cliente con identificación ' + partner_id + ' no coincide con el cliente de esta factura: ' + self.partner_id.vat)
			elif str(self.date_invoice) != date_issuance:
				raise UserError('La fecha del XML () ' + date_issuance + ' no coincide con la fecha de esta factura')
			elif self.number != consecutive:
				raise UserError('El número cosecutivo ' + consecutive + ' no coincide con el de esta factura')
			else:
				self.number_electronic = root.findall('Clave')[0].text
				self.date_issuance = date_issuance
				self.date_invoice = date_issuance


		elif self.xml_supplier_approval:
			root = ET.fromstring(
				re.sub(' xmlns="[^"]+"', '', base64.b64decode(self.xml_supplier_approval).decode("utf-8"),
					   count=1))  # quita el namespace de los elementos

			self.number_electronic = root.findall('Clave')[0].text
			self.date_issuance = root.findall('FechaEmision')[0].text
			self.date_invoice = parse(self.date_issuance)

			partner = self.env['res.partner'].search(
				[('vat', '=', root.findall('Emisor')[0].find('Identificacion')[1].text)])

			if partner:
				self.partner_id = partner.id
			else:
				raise UserError('El proveedor con identificación ' + root.findall('Emisor')[0].find('Identificacion')[
					1].text + ' no existe. Por favor creelo primero en el sistema.')

			self.reference = self.number_electronic[21:41]

			tax_node = root.findall('ResumenFactura')[0].findall('TotalImpuesto')
			if tax_node:
				self.amount_tax_electronic_invoice = tax_node[0].text
			self.amount_total_electronic_invoice = root.findall('ResumenFactura')[0].findall('TotalComprobante')[0].text

	@api.multi
	def send_acceptance_message(self):
		for invoice in self:
			if invoice.xml_supplier_approval:
				if not invoice.state_invoice_partner:
					raise UserError('Aviso!.\nDebe primero seleccionar el tipo de respuesta para el archivo cargado.')
				if invoice.company_id.frm_ws_ambiente != 'disabled' and invoice.state_invoice_partner:
					mensaje = self.env['facturacion_electronica'].get_xml2(invoice)

					if mensaje:
						invoice.xml_comprobante = mensaje
						invoice.fname_xml_comprobante = 'mensaje_' + invoice.number + '.xml'

						token = self.env['facturacion_electronica'].get_token()

						if token:
							if self.env['facturacion_electronica'].enviar_mensaje(invoice):
								_logger.info('enviado :) :::::::')
								# if self.env['facturacion_electronica'].consultar_factura(invoice):
								# 	self.env['facturacion_electronica'].enviar_email(invoice)
					else:
						_logger.info('Error generando mensaje %s' % mensaje)









	@api.multi
	@api.returns('self')
	def refund(self, date_invoice=None, date=None, description=None, journal_id=None, invoice_id=None, reference_code_id=None):
		if self.env.user.company_id.frm_ws_ambiente == 'disabled':
			new_invoices = super(AccountInvoiceElectronic, self).refund()
			return new_invoices
		else:
			new_invoices = self.browse()
			for invoice in self:
				# create the new invoice
				values = self._prepare_refund(invoice, date_invoice=date_invoice, date=date, description=description, journal_id=journal_id)
				values.update({'invoice_id': invoice_id, 'reference_code_id': reference_code_id})
				refund_invoice = self.create(values)

				invoice_type = {
					'out_invoice': ('customer invoices refund'),
					'in_invoice': ('vendor bill refund')
				}
				message = _(
					"This %s has been created from: <a href=# data-oe-model=account.invoice data-oe-id=%d>%s</a>") % (
							  invoice_type[invoice.type], invoice.id, invoice.number)
				refund_invoice.message_post(body=message)
				refund_invoice.payment_methods_id = invoice.payment_methods_id
				new_invoices += refund_invoice
			return new_invoices

	@api.onchange('partner_id', 'company_id')
	def _onchange_partner_id(self):
		super(AccountInvoiceElectronic, self)._onchange_partner_id()
		self.payment_methods_id = self.partner_id.payment_methods_id

	@api.multi
	def action_consultar_hacienda(self):
		if self.company_id.frm_ws_ambiente != 'disabled':

			for invoice in self:
				self.env['facturacion_electronica'].consultar_factura(invoice)

	@api.multi
	def action_invoice_open(self):
		super(AccountInvoiceElectronic, self).action_invoice_open()

		if self.company_id.frm_ws_ambiente != 'disabled':

			for invoice in self:

				now_utc = datetime.datetime.now(pytz.timezone('UTC'))
				now_cr = now_utc.astimezone(pytz.timezone('America/Costa_Rica'))

				invoice.fecha = now_cr.strftime('%Y-%m-%d %H:%M:%S')
				invoice.date_issuance = now_cr.strftime("%Y-%m-%dT%H:%M:%S-06:00")

				consecutivo = self.env['facturacion_electronica'].get_consecutivo(invoice)
				if not consecutivo:
					raise UserError('Error con el consecutivo de la factura %s' % consecutivo)
				invoice.number = consecutivo

				clave = self.env['facturacion_electronica'].get_clave(invoice)
				if not clave:
					raise UserError('Error con la clave de la factura %s' % clave)
				invoice.number_electronic = clave

				comprobante = self.env['facturacion_electronica'].get_xml(invoice)

				if comprobante:
					invoice.xml_comprobante = comprobante
					invoice.fname_xml_comprobante = 'comprobante_' + invoice.number_electronic + '.xml'

					token = self.env['facturacion_electronica'].get_token()

					if token:
						if self.env['facturacion_electronica'].enviar_factura(invoice):
							if self.env['facturacion_electronica'].consultar_factura(invoice):
								self.env['facturacion_electronica'].enviar_email(invoice)
				else:
					_logger.info('Error generando comprobante %s' % comprobante)
