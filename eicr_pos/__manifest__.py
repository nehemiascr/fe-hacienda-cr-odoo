{
    'name': 'eicr - punto de venta',
    'version': '11.0.0',
    'author': 'Automatización',
    'license': 'OPL-1',
    'website': 'https://www.fakturacion.com/',
    'category': 'pos',
    'depends': [
        'point_of_sale', 'eicr_base'
    ],
    'data': [
        'views/pos_order_view.xml',
    ],
    'installable': True,
    'application': True,

}