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

		tiquetes = self.env['pos.order'].search([('eicr_state', 'in', ('pendiente',))],
									limit=max_documentos).sorted(key=lambda o: o.name)
		_logger.info('Validando %s Ordenes' % len(tiquetes))
		for indice, tiquete in enumerate(tiquetes):
			_logger.info('Validando Orden %s/%s %s' % (indice+1, len(tiquetes), tiquete))
			if not tiquete.eicr_documento_file:
				tiquete.eicr_state = 'na'
				pass
			self._enviar_documento(tiquete)

	@api.model
	def _consultahacienda(self, max_documentos=4):  # cron

		super(ElectronicInvoiceCostaRicaTools, self)._consultahacienda(max_documentos)

		tiquetes = self.env['pos.order'].search([('eicr_state', 'in', ('recibido', 'procesando', 'error'))], limit=max_documentos)
		_logger.info('Consultando %s Ordenes' % len(tiquetes))
		for indice, tiquete in enumerate(tiquetes):
			_logger.info('Consultando Orden %s/%s %s' % (indice+1, len(tiquetes), tiquete))
			if not tiquete.eicr_documento_file:
				pass
			if self._consultar_documento(tiquete):
				self.env['eicr.tools']._enviar_email(tiquete)