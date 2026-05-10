// Accountant Custody DocType — Client-side controller (v2)
// Dynamic settlement dialog with three pathways: Advance Deduction, Direct Payment, Mixed.
frappe.ui.form.on("Accountant Custody", {
    // ── Form lifecycle ────────────────────────────────────────────────────
    refresh: function (frm) {
        setup_form_intro(frm);
        setup_action_buttons(frm);
    },

    custody_request: function (frm) {
        if (frm.doc.custody_request) {
            frappe.db.get_value(
                "Custody Request",
                frm.doc.custody_request,
                ["custodian", "advance_amount", "paid_amount", "unallocated_amount"],
                function (r) {
                    if (r) {
                        if (!frm.doc.custodian) frm.set_value("custodian", r.custodian);
                        frm.set_value("custody_request_balance", r.unallocated_amount || 0);
                    }
                }
            );
        }
    },

    custodian: function (frm) {
        if (frm.doc.custodian) {
            frappe.db.get_value(
                "Custodian",
                frm.doc.custodian,
                ["employee", "employee_name", "company", "dedicated_supplier"],
                function (r) {
                    if (r) {
                        if (!frm.doc.company) frm.set_value("company", r.company);
                    }
                }
            );
        }
    },
});

// ── Child table events ────────────────────────────────────────────────────────
frappe.ui.form.on("Accountant Custody Item", {
    qty: function (frm, cdt, cdn) {
        calculate_item_amount(frm, cdt, cdn);
    },
    rate: function (frm, cdt, cdn) {
        calculate_item_amount(frm, cdt, cdn);
    },
    custody_items_remove: function (frm) {
        update_totals(frm);
    }
});

// ── Form Intro ────────────────────────────────────────────────────────────────
function setup_form_intro(frm) {
    if (!frm.doc.docstatus) return;
    var status_messages = {
        "Pending":          ["blue",   "Awaiting Purchase Receipt creation."],
        "Partly Received":  ["orange", "Some items received. Create remaining receipts."],
        "Fully Received":   ["blue",   "All items received. Ready to generate Purchase Invoice."],
        "Partly Invoiced":  ["orange", "Partially invoiced. Complete remaining invoices."],
        "Fully Invoiced":   ["blue",   "Fully invoiced. Ready to settle."],
        "Partly Settled":   ["orange", "Partially settled. Complete the settlement."],
        "Fully Settled":    ["green",  "All amounts settled. No further action required."],
        "Closed":           ["green",  "Closed."],
        "Cancelled":        ["red",    "Cancelled."],
    };
    var info = status_messages[frm.doc.status];
    if (info) {
        frm.set_intro(info[1], info[0]);
    }
}

// ── Action Buttons ────────────────────────────────────────────────────────────
function setup_action_buttons(frm) {
    if (frm.doc.docstatus !== 1) return;

    var status = frm.doc.status;

    // ── Create Purchase Receipt ───────────────────────────────────────────
    if (["Pending", "Partly Received"].indexOf(status) !== -1) {
        frm.add_custom_button(__("Create Purchase Receipt"), function () {
            frappe.call({
                method: "create_purchase_receipt",
                doc: frm.doc,
                freeze: true,
                freeze_message: __("Creating Purchase Receipt..."),
                callback: function (r) {
                    if (!r.exc) {
                        frm.reload_doc();
                        frappe.set_route("Form", "Purchase Receipt", r.message);
                    }
                }
            });
        }, __("Procurement"));
    }

    // ── Generate Purchase Invoice ─────────────────────────────────────────
    if (["Fully Received", "Partly Invoiced"].indexOf(status) !== -1) {
        frm.add_custom_button(__("Generate Purchase Invoice"), function () {
            frappe.call({
                method: "generate_purchase_invoice",
                doc: frm.doc,
                freeze: true,
                freeze_message: __("Generating Purchase Invoice..."),
                callback: function (r) {
                    if (!r.exc) {
                        frm.reload_doc();
                        frappe.set_route("Form", "Purchase Invoice", r.message);
                    }
                }
            });
        }, __("Procurement"));
    }

    // ── Settle ────────────────────────────────────────────────────────────
    if (["Fully Invoiced", "Partly Settled"].indexOf(status) !== -1) {
        frm.add_custom_button(__("Settle"), function () {
            open_settlement_dialog(frm);
        }).addClass("btn-primary");
    }
}

// ── Settlement Dialog (v2 — dynamic, no static settlement_type) ──────────────
function open_settlement_dialog(frm) {
    var billed_amount = flt(frm.doc.total_billed_amount || 0);
    var settled_amount = flt(frm.doc.total_settled_amount || 0);
    var remaining_to_settle = billed_amount - settled_amount;
    var request_balance = flt(frm.doc.custody_request_balance || 0);

    if (remaining_to_settle <= 0) {
        frappe.msgprint(__("This Accountant Custody is already fully settled."));
        return;
    }

    var d = new frappe.ui.Dialog({
        title: __("Settle Accountant Custody"),
        fields: [
            // ── Summary HTML ──────────────────────────────────────────────
            {
                fieldname: "summary_html",
                fieldtype: "HTML",
                options: (
                    '<div class="alert alert-info" style="margin-bottom:12px">' +
                    '<table class="table table-condensed" style="margin:0">' +
                    '<tr><td><strong>' + __("Total Billed") + '</strong></td>' +
                    '<td class="text-right">' + format_currency(billed_amount) + '</td></tr>' +
                    '<tr><td><strong>' + __("Already Settled") + '</strong></td>' +
                    '<td class="text-right">' + format_currency(settled_amount) + '</td></tr>' +
                    '<tr><td><strong>' + __("Remaining to Settle") + '</strong></td>' +
                    '<td class="text-right"><strong>' + format_currency(remaining_to_settle) + '</strong></td></tr>' +
                    (frm.doc.custody_request
                        ? '<tr><td>' + __("Available Advance Balance") + '</td>' +
                          '<td class="text-right">' + format_currency(request_balance) + '</td></tr>'
                        : '') +
                    '</table></div>'
                )
            },
            // ── Settlement method selector ────────────────────────────────
            {
                fieldname: "settlement_method",
                fieldtype: "Select",
                label: __("Settlement Method"),
                options: [
                    "",
                    __("Advance Deduction (Journal Entry)"),
                    __("Direct Payment (Payment Entry)"),
                    __("Mixed Settlement"),
                ].join("\n"),
                reqd: 1,
                onchange: function () {
                    var method = d.get_value("settlement_method");
                    var adv_max = Math.min(remaining_to_settle, request_balance);

                    if (method === __("Advance Deduction (Journal Entry)")) {
                        d.set_value("advance_amount_allocated", adv_max);
                        d.set_value("direct_payment_amount", 0);
                        d.toggle_display("advance_amount_allocated", true);
                        d.toggle_display("direct_payment_amount", false);
                    } else if (method === __("Direct Payment (Payment Entry)")) {
                        d.set_value("advance_amount_allocated", 0);
                        d.set_value("direct_payment_amount", remaining_to_settle);
                        d.toggle_display("advance_amount_allocated", false);
                        d.toggle_display("direct_payment_amount", true);
                    } else if (method === __("Mixed Settlement")) {
                        d.set_value("advance_amount_allocated", adv_max);
                        d.set_value("direct_payment_amount", remaining_to_settle - adv_max);
                        d.toggle_display("advance_amount_allocated", true);
                        d.toggle_display("direct_payment_amount", true);
                    } else {
                        d.toggle_display("advance_amount_allocated", false);
                        d.toggle_display("direct_payment_amount", false);
                    }
                }
            },
            // ── Amount fields ─────────────────────────────────────────────
            {
                fieldname: "advance_amount_allocated",
                fieldtype: "Currency",
                label: __("Advance Amount Allocated"),
                default: 0,
                hidden: 1,
                description: __("Amount deducted from the custodian advance (generates Journal Entry)."),
                onchange: function () {
                    var adv = flt(d.get_value("advance_amount_allocated") || 0);
                    var method = d.get_value("settlement_method");
                    if (method === __("Mixed Settlement")) {
                        var direct = remaining_to_settle - adv;
                        d.set_value("direct_payment_amount", direct > 0 ? direct : 0);
                    }
                }
            },
            {
                fieldname: "direct_payment_amount",
                fieldtype: "Currency",
                label: __("Direct Payment Amount"),
                default: 0,
                hidden: 1,
                description: __("Amount paid directly to the supplier (generates Payment Entry).")
            },
            {
                fieldname: "settlement_notes",
                fieldtype: "Small Text",
                label: __("Settlement Notes")
            }
        ],
        primary_action_label: __("Confirm Settlement"),
        primary_action: function (values) {
            var method = values.settlement_method;
            if (!method) {
                frappe.msgprint(__("Please select a Settlement Method."));
                return;
            }

            var adv = flt(values.advance_amount_allocated || 0);
            var direct = flt(values.direct_payment_amount || 0);
            var total = adv + direct;

            if (Math.abs(total - remaining_to_settle) > 0.01) {
                frappe.msgprint(
                    __("Settlement total {0} must equal the remaining amount {1}.", [
                        format_currency(total),
                        format_currency(remaining_to_settle)
                    ])
                );
                return;
            }

            d.hide();
            frappe.call({
                method: "create_settlement",
                doc: frm.doc,
                args: {
                    advance_amount_allocated: adv,
                    direct_payment_amount: direct,
                    settlement_notes: values.settlement_notes || ""
                },
                freeze: true,
                freeze_message: __("Processing Settlement..."),
                callback: function (r) {
                    if (!r.exc) {
                        frm.reload_doc();
                        frappe.show_alert({
                            message: __("Settlement complete. Document {0} created.", [r.message]),
                            indicator: "green"
                        });
                    }
                }
            });
        }
    });

    // Hide amount fields initially until method is selected
    d.toggle_display("advance_amount_allocated", false);
    d.toggle_display("direct_payment_amount", false);
    d.show();
}

// ── Helper Functions ──────────────────────────────────────────────────────────
function calculate_item_amount(frm, cdt, cdn) {
    var row = locals[cdt][cdn];
    var amount = flt(row.qty) * flt(row.rate);
    frappe.model.set_value(cdt, cdn, "amount", amount);
    update_totals(frm);
}

function update_totals(frm) {
    var total = 0;
    (frm.doc.custody_items || []).forEach(function (item) {
        total += flt(item.amount);
    });
    frm.set_value("total_amount", total);
}
