import base64
import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class EICRRemakeXMLWizard(models.TransientModel):
    _name = 'eicr.remake_xml'
    _description = 'Asistente de Regeneración de XML '

    invoice_id = fields.Many2one('account.invoice', string='Factura')
    keep_clave = fields.Boolean(string='Mantener Clave', default=True, help="Solo se generará un nuevo código de seguridad de la clave")
    keep_date = fields.Boolean(string='Mantener Fecha', default=True)
    new_date = fields.Date(string='Nueva Fecha de Emisión')

    eicr_mensaje_hacienda = fields.Text(related='invoice_id.respuesta_tributacion_preview', readonly=True)
    eicr_date = fields.Datetime(related='invoice_id.fecha', readonly=True)
    number_electronic = fields.Char(related='invoice_id.number_electronic', readonly=True)

    @api.multi
    def action_remake_xml_confirm(self):
        _logger.info(self)
        if self.keep_clave:
            self.invoice_id.number_electronic = str(int(self.invoice_id.number_electronic) + 1)
        else:
            self.invoice_id.number_electronic = None
        
        if not self.keep_date:
            self.invoice_id.fecha = new_date
        
        self.invoice_id.xml_comprobante = False
        self.invoice_id._action_out_invoice_open(self.invoice_id)

        return self.invoice_id
