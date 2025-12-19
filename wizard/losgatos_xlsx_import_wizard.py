# -*- coding: utf-8 -*-
import base64
import io
from collections import defaultdict
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError

try:
    import openpyxl
except ImportError:
    openpyxl = None


class LosgatosXlsxImportWizard(models.TransientModel):
    _name = "losgatos.xlsx.import.wizard"
    _description = "Los Gatos - Importador XLSX de Ventas"


    file_data = fields.Binary(string="Archivo XLSX", required=True)
    file_name = fields.Char(string="Nombre del archivo")

    def action_import(self):
        self.ensure_one()

        if not openpyxl:
            raise UserError(_("Instala openpyxl (pip install openpyxl)"))

        wb = openpyxl.load_workbook(
            io.BytesIO(base64.b64decode(self.file_data)),
            data_only=True
        )
        ws = wb.active

        # Agrupar filas por UUID (Columna C)
        sales = defaultdict(list)
        for row in ws.iter_rows(min_row=2):
            uuid = row[2].value  # Col C
            if uuid:
                sales[uuid].append(row)

        for uuid, rows in sales.items():
            first = rows[0]

            # Fecha (Col A)
            invoice_date = first[0].value
            if isinstance(invoice_date, datetime):
                invoice_date = invoice_date.date()

            # Diario factura (Tipo documento - Col B)
            journal_name = str(first[1].value).strip()
            journal = self.env["account.journal"].search([
                ("name", "=", journal_name),
                ("type", "=", "sale")
            ], limit=1)

            if not journal:
                raise UserError(_(
                    f"No existe el diario de ventas: {journal_name}"
                ))

            # Cliente
            vat = str(first[5].value).strip() if first[5].value else False  # Col F
            partner_name = str(first[6].value).strip()  # Col G

            partner = self.env["res.partner"].search(
                [("vat", "=", vat)], limit=1
            )

            if not partner:
                partner = self.env["res.partner"].create({
                    "name": partner_name,
                    "vat": vat,
                    "customer_rank": 1,
                })

            invoice_lines = []

            for row in rows:
                product_code = str(row[19].value).strip()  # Col T
                product_name = str(row[18].value).strip()  # Col S
                qty = row[20].value or 1.0               # Col U
                price = row[21].value or 0.0             # Col V
                discount = row[25].value or 0.0          # Col Z

                product = self.env["product.product"].search(
                    [("default_code", "=", product_code)],
                    limit=1
                )

                if not product:
                    product = self.env["product.product"].create({
                        "name": product_name,
                        "default_code": product_code,
                        "type": "product",
                    })

                invoice_lines.append((0, 0, {
                    "product_id": product.id,
                    "quantity": qty,
                    "price_unit": price,
                    "discount": discount,
                }))

            move = self.env["account.move"].create({
                "move_type": "out_invoice",
                "partner_id": partner.id,
                "journal_id": journal.id,
                "invoice_date": invoice_date,
                "ref": uuid,
                "invoice_line_ids": invoice_lines,
            })

            move.action_post()

            # ======================
            # Pago automático
            # Diario de pago = Col I + Col M
            # ======================
            payment_journal_name = f"{first[8].value}{first[12].value}"

            payment_journal = self.env["account.journal"].search([
                ("name", "=", payment_journal_name),
                ("type", "in", ["bank", "cash"])
            ], limit=1)

            if not payment_journal:
                raise UserError(_(
                    f"No existe el diario de pago: {payment_journal_name}"
                ))

            payment = self.env["account.payment"].create({
                "payment_type": "inbound",
                "partner_type": "customer",
                "partner_id": partner.id,
                "amount": move.amount_total,
                "journal_id": payment_journal.id,
                "date": invoice_date,
            })

            payment.action_post()

            # Conciliar
            (payment.line_ids + move.line_ids).filtered(
                lambda l: l.account_id == move.line_ids.filtered(
                    lambda x: x.account_id.internal_type == "receivable"
                )[0].account_id and not l.reconciled
            ).reconcile()

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Importación completa"),
                "message": _("Las facturas fueron creadas y pagadas correctamente."),
                "type": "success",
            }
        }
