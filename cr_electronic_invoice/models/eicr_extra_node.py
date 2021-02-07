# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from lxml import etree
import logging
from jinja2 import Environment, meta, Template

_logger = logging.getLogger(__name__)


class ElectronicInvoiceCostaRicaExtraNode(models.Model):
    _name = 'eicr.extra_node'
    _description = 'Definiciones de Nodos extra a agregar en los Documentos Electrónicos'

    name = fields.Char('Descripción', help='Descripción del Nodo extra')
    node_definition = fields.Text('Definición del Nodo', required=True, help='Estructura del Nodo (Jinja)')
    node_location = fields.Char('Posicion del Nodo', required=True, help='Ubicación del Nodo (XPath)')
    partner_ids = fields.Many2many('res.partner', 'extra_node_res_partner_rel', 
         'extra_node_id', 'partner_id', string='Contactos que incluyen el nodo', help='Contactos que agregan este Nodo')

    valid_definition = fields.Boolean('Definición Válida', compute='_compute_valid_definition', store=True)
    valid_location = fields.Boolean('Ubicación Válida', compute='_compute_valid_location', store=True)
    show_in_report = fields.Boolean('Mostrar en PDF')


    sequence = fields.Integer(default=10, string='Secuencia', help="Orden en que los nodos se agregan al Documento Electrónico.")

    
    def _validate_definition(self, definition=None):
        if not definition: definition = self.node_definition
        _logger.info('_validate_definition %s %s' % (self, definition))
        if not definition: return False
        # check if provided definition is valid
        definition = definition.strip()
        try:
            template = definition
            env = Environment()
            ast = env.parse(template)
            varnames = meta.find_undeclared_variables(ast)

            kwargs = {}
            if varnames:
                doc_id = self.env['account.invoice'].search([], order='id desc', limit=1)
                for varname in varnames:
                    kwargs[varname] = doc_id[varname]
            # validate fields
            t = Template(template)
            redenred_template = t.render(kwargs)
            _logger.info(redenred_template)
            # validate xml structure
            xml_string ='<root>%s</root>' % redenred_template
            tree = etree.fromstring(xml_string)
            for node in tree:
                _logger.info(node)
            
            self.definition = definition
            return True

        except Exception as e:
            _logger.info('error')
            _logger.error(e)
            return False


    @api.multi
    def write(self, values):
        if values.get('node_definition') and not self._validate_definition(values.get('node_definition')):
            raise UserError(_('La definición del Nodo es inválida'))
        if values.get('node_location') and not self._validate_location(values.get('node_location')):
            raise UserError(_('La ubicación del Nodo es inválida'))

        res = super(ElectronicInvoiceCostaRicaExtraNode, self).write(values)
        return res

        
    def _validate_location(self, location=None):
        if not location: location = self.node_location
        _logger.info('_validate_location %s %s' % (self, location))
        if not location: return False
        # check if provided location is valid
        location = location.strip()
        self.location = location
        return True

    @api.onchange('node_definition')
    def onchange_definition(self):
        _logger.info('onchange_definition %s' % self)
        self.valid_definition = True if self._validate_definition() else False

    @api.onchange('node_location')
    def onchange_location(self):
        _logger.info('onchange_location %s' % self)
        self.valid_location = True if self._validate_location() else False

    @api.multi
    @api.depends('node_definition')
    def _compute_valid_definition(self):
        for node in self:
            node.valid_definition = node._validate_definition()

    @api.multi
    @api.depends('node_location')
    def _compute_valid_location(self):
        for node in self:
            node.valid_location = node._validate_location()

    def get_node(self, doc_id):
        template = self.node_definition
        env = Environment()
        ast = env.parse(template)
        varnames = meta.find_undeclared_variables(ast)

        kwargs = {}
        if varnames:
            for varname in varnames:
                kwargs[varname] = doc_id[varname]
        # validate fields
        t = Template(template)
        redenred_template = t.render(kwargs)
        _logger.info(redenred_template)
        # validate xml structure
        xml_string ='<root>%s</root>' % redenred_template
        tree = etree.fromstring(xml_string)
        for node in tree:
            _logger.info(node)
        return tree