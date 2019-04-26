# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models
import odoo.addons.decimal_precision as dp


class PosConfig(models.Model):
    _inherit = 'pos.config'

    @api.depends('sequence_id')
    def _compute_ticket_hacienda_sequence(self):
        for pos in self:
            seq = pos.sequence_id
            pos.ticket_hacienda_number = seq.number_next_actual
            pos.ticket_hacienda_prefix = seq.prefix
            pos.ticket_hacienda_padding = seq.padding

    iface_ticket_hacienda = fields.Boolean(
        string='Use simplified invoices for this POS',
    )

    ticket_hacienda_prefix = fields.Char(
        'Simplified Invoice prefix',
        readonly=True,
        compute='_compute_ticket_hacienda_sequence',
        oldname='ticket_hacienda_prefix',
    )

    ticket_hacienda_padding = fields.Integer(
        'Simplified Invoice padding',
        readonly=True,
        compute='_compute_ticket_hacienda_sequence',
        oldname='ticket_hacienda_limit',
    )

    ticket_hacienda_number = fields.Integer(
        'Sim.Inv number',
        readonly=True,
        compute='_compute_ticket_hacienda_sequence',
        oldname='ticket_hacienda_number',
    )

    return_sequence_id = fields.Many2one('ir.sequence', string='Order IDs Return Sequence', readonly=False,
        help="This sequence is automatically created by Odoo but you can change it "
        "to customize the reference numbers of your orders.", copy=False)
