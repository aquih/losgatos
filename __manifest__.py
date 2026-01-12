# -*- coding: utf-8 -*-
{
    "name": "Los Gatos",
    "version": "1.2",
    "author": "aquíH",
    "category": "Accounting",
    "summary": "Importa ventas desde XLSX, crea facturas y las paga automáticamente",
    "depends": ["account", "sale", "stock", "product"],
    "data": [
        "security/ir.model.access.csv",
        "views/losgatos_xlsx_import_views.xml",
    ],
    "installable": True,
    "license": "LGPL-3",
}