# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "POS Electronico Costa Rica",
    "category": "Point Of Sale",
    "author": "Jason Ulloa Hernandez, "
              "TechMicro Inc S.A.",
    "website": "https://www.techmicrocr.com",
    "license": "AGPL-3",
    "version": "1.0",
    "depends": [
        "point_of_sale", "cr_electronic_invoice"
    ],
    "data": [
        "data/data.xml",
        "views/pos_templates.xml",
        "views/pos_views.xml",
        "views/electronic_invoice_views.xml",
    ],
    "qweb": [
        "static/src/xml/pos.xml",
    ],
    "installable": True
}
