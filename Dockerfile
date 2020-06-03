FROM alpine/git as addons

# Facturación Electrónica
RUN git clone https://github.com/nehemiascr/fe-hacienda-cr-odoo.git --branch 4.3 --single-branch /opt/nehemiascr/fe-hacienda-cr-odoo \
 && git clone https://github.com/OCA/web.git --branch 11.0 --single-branch /opt/OCA/web \
 && git clone https://github.com/odoocr/res_currency_cr_adapter.git --branch 11.0 --single-branch /opt/odoocr/res_currency_cr_adapter \
 # Material/United Backend Theme
 && git clone https://github.com/Openworx/backend_theme.git --branch 11.0 --single-branch /opt/Openworx/backend_theme \
 # POS Multi sesion
 && git clone https://github.com/it-projects-llc/pos-addons.git --branch 11.0 --single-branch /opt/it-projects-llc/pos-addons \
 # Reporting Engine
 && git clone https://github.com/OCA/reporting-engine.git --branch 11.0 --single-branch /opt/OCA/reporting-engine \
 # multi-company
 && git clone https://github.com/ingadhoc/multi-company.git --branch 11.0 --single-branch  /opt/ingadhoc/multi-company


FROM odoo:11

LABEL maintainer="info@automatuanis.com"

USER root

RUN set -x; \
    apt-get update \
    && apt-get install -y default-jre \
    && pip3 install unicodecsv \
    && pip3 install phonenumbers \
    && pip3 install xlsxwriter \
    && pip3 install xlrd

# Facturación Electrónica
COPY --chown=odoo --from=addons /opt/nehemiascr/fe-hacienda-cr-odoo/cr_electronic_invoice /mnt/extra-addons/cr_electronic_invoice
COPY --chown=odoo --from=addons /opt/nehemiascr/fe-hacienda-cr-odoo/cr_pos_electronic_invoice /mnt/extra-addons/cr_pos_electronic_invoice
COPY --chown=odoo --from=addons /opt/nehemiascr/fe-hacienda-cr-odoo/hr_expense_cr_electronic_invoice /mnt/extra-addons/hr_expense_cr_electronic_invoice
COPY --chown=odoo --from=addons /opt/nehemiascr/fe-hacienda-cr-odoo/l10n_cr_country_codes /mnt/extra-addons/l10n_cr_country_codes
COPY --chown=odoo --from=addons /opt/odoocr/res_currency_cr_adapter /mnt/extra-addons/res_currency_cr_adapter
# Material/United Backend Theme
COPY --chown=odoo --from=addons /opt/OCA/web/web_responsive /mnt/extra-addons/web_responsive
COPY --chown=odoo --from=addons /opt/Openworx/backend_theme/backend_theme_v11 /mnt/extra-addons/backend_theme_v11
# POS Multi sesion
COPY --chown=odoo --from=addons /opt/it-projects-llc/pos-addons/pos_multi_session_sync /mnt/extra-addons/pos_multi_session_sync
COPY --chown=odoo --from=addons /opt/it-projects-llc/pos-addons/pos_multi_session_restaurant /mnt/extra-addons/pos_multi_session_restaurant
COPY --chown=odoo --from=addons /opt/it-projects-llc/pos-addons/pos_multi_session_menu /mnt/extra-addons/pos_multi_session_menu
COPY --chown=odoo --from=addons /opt/it-projects-llc/pos-addons/pos_multi_session /mnt/extra-addons/pos_multi_session
COPY --chown=odoo --from=addons /opt/it-projects-llc/pos-addons/pos_disable_payment /mnt/extra-addons/pos_disable_payment
COPY --chown=odoo --from=addons /opt/it-projects-llc/pos-addons/pos_restaurant_base /mnt/extra-addons/pos_restaurant_base
COPY --chown=odoo --from=addons /opt/it-projects-llc/pos-addons/pos_longpolling /mnt/extra-addons/pos_longpolling
# Report Engine
COPY --chown=odoo --from=addons /opt/OCA/reporting-engine/report_xlsx /mnt/extra-addons/report_xlsx
# Multi-Company
COPY --chown=odoo --from=addons /opt/ingadhoc/multi-company/account_multic_fix /mnt/extra-addons/account_multic_fix
COPY --chown=odoo --from=addons /opt/ingadhoc/multi-company/account_multicompany_ux /mnt/extra-addons/account_multicompany_ux
COPY --chown=odoo --from=addons /opt/ingadhoc/multi-company/purchase_multic_fix /mnt/extra-addons/purchase_multic_fix
COPY --chown=odoo --from=addons /opt/ingadhoc/multi-company/sale_multic_fix /mnt/extra-addons/sale_multic_fix
COPY --chown=odoo --from=addons /opt/ingadhoc/multi-company/sale_stock_multic_fix /mnt/extra-addons/sale_stock_multic_fix

USER odoo
