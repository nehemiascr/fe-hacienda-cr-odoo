# -*- coding: utf-8 -*-
from odoo import models, api

import logging

EICR_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S-06:00"

_logger = logging.getLogger(__name__)


class ElectronicInvoiceCostaRicaTools(models.AbstractModel):
	_inherit = 'eicr.hacienda'
	_description = 'Herramienta de comunicación con Hacienda'

	@api.model
	def _validahacienda(self, max_documentos=4):  # cron

		super(ElectronicInvoiceCostaRicaTools, self)._validahacienda(max_documentos)

		gastos = self.env['hr.expense'].search([('eicr_state', 'in', ('pendiente',))],
								limit=max_documentos).sorted(key=lambda g: g.reference)
		_logger.info('Validando %s Gastos' % len(gastos))
		for indice, gasto in enumerate(gastos):
			_logger.info('Validando Gasto %s/%s %s' % (indice + 1, len(gastos), gasto))
			if not gasto.eicr_documento2_file:
				gasto.eicr_state = 'na'
				pass
			elif not gasto.eicr_documento_file: gasto.make_xml()
			if gasto.eicr_documento_file: self._enviar_documento(gasto)

	@api.model
	def _consultahacienda(self, max_documentos=4):  # cron

		super(ElectronicInvoiceCostaRicaTools, self)._consultahacienda(max_documentos)

		gastos = self.env['hr.expense'].search([('eicr_state', 'in', ('recibido', 'procesando', 'error'))], limit=max_documentos)
		_logger.info('Consultando %s Gastos' % len(gastos))
		for indice, gasto in enumerate(gastos):
			_logger.info('Consultando Gasto %s/%s %s' % (indice + 1, len(gastos), gasto))
			if gasto.eicr_documento_file: self._consultar_documento(gasto)