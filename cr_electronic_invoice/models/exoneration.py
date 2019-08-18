# -*- coding: utf-8 -*-
from odoo import models, fields
import logging

_logger = logging.getLogger(__name__)


class Exoneration(models.Model):
    _name = "exoneration"

    name = fields.Char("Nombre")
    code = fields.Char("Código")
    type = fields.Char("Tipo")
    exoneration_number = fields.Char("Número de exoneración")
    name_institution = fields.Char("Nombre de institución")
    date = fields.Date("Fecha")
    percentage_exoneration = fields.Float("Porcentaje de exoneración")
