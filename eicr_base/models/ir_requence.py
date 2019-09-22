# -*- coding: utf-8 -*-

import logging, re
from odoo import models, fields, api, _


_logger = logging.getLogger(__name__)


class IrSequence(models.Model):
    _inherit = 'ir.sequence'

    sucursal = fields.Integer('Sucursal', default='1')
    terminal = fields.Integer('Terminal', default='1')