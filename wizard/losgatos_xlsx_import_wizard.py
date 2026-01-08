# -*- coding: utf-8 -*-
import base64
import io
from collections import defaultdict
from datetime import datetime, date

from odoo import models, fields, _
from odoo.exceptions import UserError

try:
    import openpyxl
except ImportError:
    openpyxl = None


class LosgatosXlsxImportWizard(models.TransientModel):
    _name = "losgatos.xlsx.import.wizard"
    _description = "Los Gatos - Importador XLSX de Ventas de Combustible"

    file_data = fields.Binary(string="Archivo XLSX", required=True)
    file_name = fields.Char(string="Nombre del archivo")

    def action_import(self):
        self.ensure_one()

        if not openpyxl:
            raise UserError(_("Instala la librería openpyxl (pip install openpyxl)"))

        if not self.file_data:
            raise UserError(_("Debes cargar un archivo XLSX"))

        wb = openpyxl.load_workbook(
            io.BytesIO(base64.b64decode(self.file_data)),
            data_only=True
        )
        ws = wb.active

        # ======================================================
        # Agrupar filas por UUID (Columna C)
        # ======================================================
        grouped_rows = defaultdict(list)

        for row in ws.iter_rows(min_row=2):
            uuid = row[2].value  # Col C
            if uuid:
                grouped_rows[str(uuid).strip()].append(row)

        if not grouped_rows:
            raise UserError(_("El archivo no contiene datos válidos"))

        for uuid, rows in grouped_rows.items():
            with self.env.cr.savepoint():

                first = rows[0]

                # ------------------------------
                # Fecha factura / SO (Col A)
                # ------------------------------
                invoice_date = first[0].value
                uuid_pos_fel = first[2].value
                numero_fel = first[3].value
                serie_fel = first[4].value
                state = first[7].value
                if isinstance(invoice_date, datetime):
                    invoice_date = invoice_date.date()

                # ------------------------------
                # Cliente (Col F = NIT, Col G = Nombre)
                # ------------------------------
                vat = str(first[5].value).strip() if first[5].value else False
                partner_name = str(first[6].value).strip()

                partner = self.env["res.partner"].search(
                    [("vat", "=", vat)], limit=1
                )

                if not partner:
                    partner = self.env["res.partner"].create({
                        "name": partner_name,
                        "vat": vat,
                        "customer_rank": 1,
                    })

                # ======================================================
                # Líneas de la orden de venta
                # ======================================================
                order_lines = []

                for row in rows:
                    product_name = str(row[18].value).strip()   # Col S
                    product_code = str(row[19].value).strip()   # Col T
                    qty = row[20].value or 1.0                  # Col U
                    price = row[21].value or 0.0                # Col V
                    discount = row[25].value or 0.0             # Col Z

                    product = self.env["product.product"].search(
                        [("default_code", "=", product_code)],
                        limit=1
                    )

                    if not product:
                        product = self.env["product.product"].create({
                            "name": product_name,
                            "default_code": product_code,
                            "type": "consu",  # 👈 CORRECTO
                            "is_storable": True,
                        })

                    order_lines.append((0, 0, {
                        "product_id": product.id,
                        "product_uom_qty": qty,
                        "price_unit": price,
                        "discount": discount,
                    }))

                if not order_lines:
                    continue

                # ======================================================
                # Crear orden de venta
                # ======================================================


                raw_date = first[0].value  # Columna A

                if isinstance(raw_date, datetime):
                    order_datetime = raw_date
                elif isinstance(raw_date, date):
                    order_datetime = datetime.combine(raw_date, datetime.min.time())
                elif isinstance(raw_date, str):
                    # XLSX a veces devuelve string
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y"):
                        try:
                            order_datetime = datetime.strptime(raw_date, fmt)
                            break
                        except ValueError:
                            continue
                    else:
                        raise UserError(_(f"Formato de fecha inválido: {raw_date}"))
                else:
                    raise UserError(_("Tipo de fecha inválido en XLSX"))

                order_date = order_datetime.date()

                sale_order = self.env["sale.order"].create({
                    "partner_id": partner.id,
                    "date_order": order_datetime,
                    "client_order_ref": uuid,
                    "order_line": order_lines,
                })

                # Confirmar SO
                sale_order.action_confirm()

                # ======================================================
                # Validar albaranes (stock.picking)
                # ======================================================
                for picking in sale_order.picking_ids.filtered(
                        lambda p: p.state not in ("done", "cancel")):

                    picking.action_confirm()
                    picking.action_assign()

                    for move_line in picking.move_line_ids:
                        if move_line.quantity == 0:
                            move_line.quantity = move_line.product_uom_qty

                    if state == "Certificada":
                        picking.button_validate()

                # ======================================================
                # Crear factura desde la orden
                # ======================================================
                invoice = sale_order._create_invoices()
                invoice.invoice_date = order_date
                invoice.uuid_pos_fel = uuid_pos_fel
                invoice.numero_fel = numero_fel
                invoice.serie_fel = serie_fel
                invoice.action_post()
                if state != "Certificada":
                    invoice.button_draft()
                    invoice.button_cancel()
                    sale_order.button_cancel()
                    sale_order.action_cancel()
                

                # ======================================================
                # Diario de pago = Col I + Col M
                # ======================================================
                payment_journal_name = f"{first[8].value} {first[12].value}"

                payment_journal = self.env["account.journal"].search([
                    ("name", "=", payment_journal_name),
                    ("type", "in", ["bank", "cash"])
                ], limit=1)

                if not payment_journal:
                    raise UserError(
                        _(f"No existe el diario de pago: {payment_journal_name}")
                    )

                # ======================================================
                # Registrar pago
                # ======================================================

                if state == "Certificada":
                    payment_register = self.env['account.payment.register'].with_context(
                        active_model='account.move',
                        active_ids=invoice.ids,
                    ).create({
                        'journal_id': payment_journal.id,
                        'amount': invoice.amount_total,
                        'payment_date': order_date,
                    })

                    payment_register.action_create_payments()

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Importación completada"),
                "message": _("Las órdenes, entregas, facturas y pagos fueron creados correctamente."),
                "type": "success",
            }
        }

