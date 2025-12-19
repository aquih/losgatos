# -*- coding: utf-8 -*-
{
    "name": "Los Gatos",
    "version": "18.0.1.0.0",
    "category": "Accounting",
    "summary": "Importa ventas desde XLSX, crea facturas y las paga automáticamente",
    "depends": ["account", "product"],
    "data": [
        "security/ir.model.access.csv",
        "views/sale_xlsx_import_views.xml",
    ],
    "installable": True,
    "license": "LGPL-3",
}