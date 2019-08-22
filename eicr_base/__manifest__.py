# -*- coding: utf-8 -*-

{
	'name': 'Base - Facturación Electrónica de Costa Rica',
	'version': '11.0.0',
	'author': 'Automatuanis.com',
	'license': 'OPL-1',
	'website': 'https://www.automatuanis.com/',
	'category': 'Invoicing Management',
	'description':
		'''
		Facturación Electrónica de Costa Rica, este módulo es la base para crear documentos electrónicos tributarios de Costa Rica a partir de objetos de odoo.
		i.e. FacturaElectronica de account.invoice 
		''',
	'depends': ['base', 'account', 'l10n_cr_country_codes', 'res_currency_cr_adapter', ],
	'data': [
		'data/account_account_tag_data.xml',
		'data/account_tax_group_data.xml',
		'data/account_tax_data.xml',

		'data/account_tax_template_data.xml',
		'data/eicr_economic_activity_data.xml',
		'data/eicr_identification_type_data.xml',
		'data/eicr_iva_credit_condition_data.xml',
		'data/eicr_payment_method_data.xml',
		'data/eicr_product_code_data.xml',
		'data/eicr_reference_code_data.xml',
		'data/eicr_reference_document_data.xml',
		'data/eicr_sale_condition_data.xml',
		'data/eicr_version_data.xml',
		'data/eicr_schema_4_2_data.xml',
		'data/eicr_schema_4_3_data.xml',
		'data/ir_cron_data.xml',
		# 'data/ir_sequence_data.xml',
		'data/mail_template_data.xml',

		'views/account_journal.xml',
		'views/account_tax_views.xml',
		'views/eicr_views.xml',
		'views/eicr_economic_activity_views.xml',
		'views/eicr_identification_type_views.xml',
		'views/eicr_iva_credit_condition_views.xml',
		'views/eicr_payment_method_views.xml',
		'views/eicr_product_code_views.xml',
		'views/eicr_reference_code_views.xml',
		'views/eicr_reference_document_views.xml',
		'views/eicr_sale_condition_views.xml',
		'views/eicr_schema_views.xml',
		'views/eicr_version_views.xml',
		'views/res_company_views.xml',
		'views/res_partner_views.xml',

		'security/ir.model.access.csv',

	         ],
	'installable': True,
	'application': True,
}
