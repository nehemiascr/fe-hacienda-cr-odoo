# -*- coding: utf-8 -*-

import logging, re
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class IrSequence(models.Model):
    _inherit = 'ir.sequence'

    eicr_no = fields.Boolean("Disable for this sequence", default=False)
