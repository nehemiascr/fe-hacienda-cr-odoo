# -*- coding: utf-8 -*-

{
	'name': 'Facturación electrónica Costa Rica',
	'version': '0.1',
	'author': 'CRLibre.org',
	'license': 'AGPL-3',
	'website': 'https://crlibre.org/',
	'category': 'Account',
	'description':
		'''
		Facturación electronica Costa Rica.
		''',
	'depends': ['base', 'account', 'l10n_cr_country_codes', 'res_currency_cr_adapter', ],
	'data': [
		    'security/ir.model.access.csv',
			'security/ir_module_category.xml',
		    'security/res_groups.xml',
		    'security/ir_rule.xml',

			'views/account_invoice.xml',
			'views/account_journal.xml',
			'views/electronic_invoice_views.xml',
			'views/res_company.xml',
			'views/res_partner.xml',

			'data/data.xml',
	        'data/code.type.product.csv',
	        'data/identification.type.csv',
	        'data/payment.methods.csv',
	        'data/reference.code.csv',
	        'data/reference.document.csv',
	        'data/sale.conditions.csv',
	        'data/product.uom.csv',
			'data/mail_template_data.xml',
			'data/sequence.xml',



			'data/account_data.xml',
			'data/account_tax_template_data.xml'

	         ],
	'installable': True,
}
