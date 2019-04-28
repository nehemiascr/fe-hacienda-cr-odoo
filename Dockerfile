FROM odoo:11
MAINTAINER yo@nehemiascr.com

USER root

RUN set -x; \
    apt-get update \
    && apt-get -y install default-jre \
    && pip3 install unicodecsv \
    && pip3 install phonenumbers \
    && pip3 install pysftp \
    && pip3 install xlsxwriter \
    && pip3 install xlrd \
    && pip3 install suds-py3

COPY --chown=odoo ./l10n_cr_country_codes /mnt/extra-addons/l10n_cr_country_codes
COPY --chown=odoo ./res_currency_cr_adapter /mnt/extra-addons/res_currency_cr_adapter
COPY --chown=odoo ./cr_electronic_invoice /mnt/extra-addons/cr_electronic_invoice
COPY --chown=odoo ./cr_pos_electronic_invoice /mnt/extra-addons/cr_pos_electronic_invoice

COPY --chown=odoo ./account_invoice_import /mnt/extra-addons/account_invoice_import
COPY --chown=odoo ./account_invoice_import_fe_cr /mnt/extra-addons/account_invoice_import_fe_cr
COPY --chown=odoo ./account_payment_mode /mnt/extra-addons/account_payment_mode
COPY --chown=odoo ./account_payment_partner /mnt/extra-addons/account_payment_partner
COPY --chown=odoo ./account_tax_unece /mnt/extra-addons/account_tax_unece
COPY --chown=odoo ./base_business_document_import /mnt/extra-addons/base_business_document_import
COPY --chown=odoo ./base_fe_cr /mnt/extra-addons/base_fe_cr
COPY --chown=odoo ./base_unece /mnt/extra-addons/base_unece
COPY --chown=odoo ./base_vat_sanitized /mnt/extra-addons/base_vat_sanitized
COPY --chown=odoo ./cr_electronic_invoice_pos /mnt/extra-addons/cr_electronic_invoice_pos
COPY --chown=odoo ./onchange_helper /mnt/extra-addons/onchange_helper
COPY --chown=odoo ./product_uom_unece /mnt/extra-addons/product_uom_unece
COPY --chown=odoo ./sales_invoice_qweb_fe /mnt/extra-addons/sales_invoice_qweb_fe

USER odoo