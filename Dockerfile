FROM alpine/git as addons

RUN git clone https://github.com/nehemiascr/fe-hacienda-cr-odoo.git --branch eicr --single-branch /opt/fe-hacienda-cr-odoo


FROM odoo:12.0 

USER root

RUN set -x; \
    apt-get update \
    && apt-get -y install default-jre \
    && pip3 install unicodecsv phonenumbers

COPY --chown=odoo --from=addons /opt/fe-hacienda-cr-odoo/eicr_base /mnt/extra-addons/eicr_base
COPY --chown=odoo --from=addons /opt/fe-hacienda-cr-odoo/eicr_expense /mnt/extra-addons/eicr_expense
COPY --chown=odoo --from=addons /opt/fe-hacienda-cr-odoo/eicr_pos /mnt/extra-addons/eicr_pos
COPY --chown=odoo --from=addons /opt/fe-hacienda-cr-odoo/l10n_cr_country_codes /mnt/extra-addons/l10n_cr_country_codes
COPY --chown=odoo --from=addons /opt/fe-hacienda-cr-odoo/res_currency_cr_adapter /mnt/extra-addons/res_currency_cr_adapter




USER odoo

