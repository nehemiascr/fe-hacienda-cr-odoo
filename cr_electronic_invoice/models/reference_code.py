# -*- coding: utf-8 -*-
from odoo import models, fields
import logging

_logger = logging.getLogger(__name__)


class ReferenceCode(models.Model):
    _name = "reference.code"

    active = fields.Boolean("Activo", default=True)
    code = fields.Char("Código")
    name = fields.Char("Nombre")
