# -*- coding: utf-8 -*-
from odoo import models, fields
import logging


_logger = logging.getLogger(__name__)


class CodeTypeProduct(models.Model):
    _name = "code.type.product"

    code = fields.Char("Código")
    name = fields.Char("Nombre")
