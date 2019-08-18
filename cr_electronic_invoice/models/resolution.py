# -*- coding: utf-8 -*-
from odoo import models, fields
import logging

_logger = logging.getLogger(__name__)


class Resolution(models.Model):
    _name = "resolution"

    active = fields.Boolean("Activo", default=True)
    name = fields.Char("Nombre")
    date_resolution = fields.Date("Fecha de resolución")
