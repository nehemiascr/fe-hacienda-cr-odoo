{
    'name': 'Gastos - Facturación Electrónica de Costa Rica',
    'version': '11.0.0',
    'author': 'Automatuanis.com',
    'license': 'OPL-1',
    'website': 'https://www.automatuanis.com/',
    'category': 'Human Resources',
    'depends': [
        'hr_expense', 'eicr_base'
    ],
    'data': [
        'views/hr_expense_views.xml',
    ],
    'installable': True,
    'application': True,

}