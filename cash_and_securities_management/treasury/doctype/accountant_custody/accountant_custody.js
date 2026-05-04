// Accountant Custody — Client Script
// Cash and Securities Management App

frappe.ui.form.on("Accountant Custody", {

    // ─── Form Setup ─────────────────────────────────────────────────────────

    setup: function (frm) {
        frm.set_query("employee", function () {
            return { filters: { status: "Active" } };
        });

        frm.set_query("custody_request", function () {
            return {
                filters: {
                    employee: frm.doc.employee,
                    docstatus: 1,
                    status: ["in", ["Paid", "Partly Claimed"]]
                }
            };
        });

        frm.set_query("warehouse", "custody_items", function () {
            return { filters: { company: frm.doc.company } };
        });
    },

    // ─── Refresh ────────────────────────────────────────────────────────────

    refresh: function (frm) {
        frm.clear_custom_buttons();

        // Generate Invoice button — visible when status is Receiving or Fully Received
        if (frm.doc.docstatus === 1 && ["Receiving", "Fully Received"].includes(frm.doc.status)) {
            frm.add_custom_button(__("Generate Invoice"), function () {
                frappe.confirm(
                    __("Are you sure you want to generate a Purchase Invoice for this Accountant Custody?"),
                    function () {
                        frappe.call({
                            method: "generate_purchase_invoice",
                            doc: frm.doc,
                            freeze: true,
                            freeze_message: __("Generating Purchase Invoice..."),
                            callback: function (r) {
                                if (!r.exc) {
                                    frm.reload_doc();
                                    frappe.show_alert({
                                        message: __("Purchase Invoice {0} created", [r.message]),
                                        indicator: "green"
                                    });
                                }
                            }
                        });
                    }
                );
            }, __("Actions"));
        }

        // Settle button — visible when status is Invoiced
        if (frm.doc.docstatus === 1 && frm.doc.status === "Invoiced") {
            frm.add_custom_button(__("Settle"), function () {
                open_settlement_dialog(frm);
            }, __("Actions"));
        }

        // Lock the form after settlement
        if (frm.doc.status === "Settled") {
            frm.set_df_property("custody_items", "read_only", 1);
            frm.set_df_property("custody_request", "read_only", 1);
            frm.set_df_property("settlement_type", "read_only", 1);
        }
    },

    // ─── Field Events ────────────────────────────────────────────────────────

    employee: function (frm) {
        if (frm.doc.employee && !frm.doc.custody_request) {
            // Auto-link to first available Custody Request
            frappe.db.get_list("Custody Request", {
                filters: {
                    employee: frm.doc.employee,
                    docstatus: 1,
                    status: ["in", ["Paid", "Partly Claimed"]]
                },
                fields: ["name", "unallocated_amount"],
                order_by: "posting_date asc",
                limit: 1
            }).then(function (results) {
                if (results && results.length > 0) {
                    frm.set_value("custody_request", results[0].name);
                    frm.set_value("custody_request_balance", results[0].unallocated_amount || 0);
                }
            });
        }
    },

    custody_request: function (frm) {
        if (frm.doc.custody_request) {
            frappe.db.get_value("Custody Request", frm.doc.custody_request,
                ["unallocated_amount", "custodian"], function (r) {
                    if (r) {
                        frm.set_value("custody_request_balance", r.unallocated_amount || 0);
                        if (r.custodian) {
                            frm.set_value("custodian", r.custodian);
                        }
                    }
                });
        } else {
            frm.set_value("custody_request_balance", 0);
        }
    }
});

// ─── Child Table: Accountant Custody Item ────────────────────────────────────

frappe.ui.form.on("Accountant Custody Item", {

    item_code: function (frm, cdt, cdn) {
        var row = locals[cdt][cdn];
        if (row.item_code) {
            frappe.db.get_value("Item", row.item_code,
                ["is_stock_item", "is_fixed_asset", "stock_uom", "asset_category"],
                function (r) {
                    if (r) {
                        frappe.model.set_value(cdt, cdn, "is_stock_item", r.is_stock_item || 0);
                        frappe.model.set_value(cdt, cdn, "is_fixed_asset", r.is_fixed_asset || 0);
                        frappe.model.set_value(cdt, cdn, "uom", r.stock_uom || "");
                        frappe.model.set_value(cdt, cdn, "asset_category", r.asset_category || "");
                    }
                });
        }
    },

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

// ─── Helper Functions ────────────────────────────────────────────────────────

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

function open_settlement_dialog(frm) {
    var billed_amount = frm.doc.total_billed_amount || 0;
    var request_balance = frm.doc.custody_request_balance || 0;
    var settlement_type = frm.doc.settlement_type;

    if (!settlement_type) {
        frappe.msgprint(__("Please select a Settlement Type on the Settlement tab before settling."));
        return;
    }

    // Determine defaults based on settlement_type from header
    var default_advance = 0;
    var default_direct = 0;
    var hide_advance = false;
    var hide_direct = false;

    if (settlement_type === "Full Advance Settlement") {
        default_advance = billed_amount;
        default_direct = 0;
        hide_direct = true;
    } else if (settlement_type === "Full Direct Payment") {
        default_advance = 0;
        default_direct = billed_amount;
        hide_advance = true;
    } else {
        // Mixed Settlement
        default_advance = Math.min(billed_amount, request_balance);
        default_direct = billed_amount - default_advance;
    }

    var d = new frappe.ui.Dialog({
        title: __("Settle Accountant Custody — {0}", [settlement_type]),
        fields: [
            {
                fieldname: "info_html",
                fieldtype: "HTML",
                options: '<div class="alert alert-info">' +
                    '<strong>' + __("Total Billed Amount") + ': ' + format_currency(billed_amount) + '</strong>' +
                    (frm.doc.custody_request ? '<br>' + __("Available Advance Balance") + ': ' + format_currency(request_balance) : '') +
                    '</div>'
            },
            {
                fieldname: "advance_amount_allocated",
                fieldtype: "Currency",
                label: __("Advance Amount Allocated"),
                default: default_advance,
                hidden: hide_advance ? 1 : 0,
                description: __("Amount from Custody Request advance"),
                onchange: function () {
                    var adv = flt(d.get_value("advance_amount_allocated"));
                    var remaining = billed_amount - adv;
                    d.set_value("direct_payment_amount", remaining > 0 ? remaining : 0);
                }
            },
            {
                fieldname: "direct_payment_amount",
                fieldtype: "Currency",
                label: __("Direct Payment Amount"),
                default: default_direct,
                hidden: hide_direct ? 1 : 0,
                description: __("Amount paid directly (not from advance)")
            },
            {
                fieldname: "settlement_notes",
                fieldtype: "Small Text",
                label: __("Settlement Notes")
            }
        ],
        primary_action_label: __("Settle"),
        primary_action: function (values) {
            var total = flt(values.advance_amount_allocated || 0) + flt(values.direct_payment_amount || 0);
            if (Math.abs(total - billed_amount) > 0.01) {
                frappe.msgprint(__("Total settlement amount {0} must equal the billed amount {1}.", [
                    format_currency(total), format_currency(billed_amount)
                ]));
                return;
            }
            d.hide();
            frappe.call({
                method: "create_settlement",
                doc: frm.doc,
                args: {
                    advance_amount_allocated: values.advance_amount_allocated || 0,
                    direct_payment_amount: values.direct_payment_amount || 0,
                    settlement_notes: values.settlement_notes || ""
                },
                freeze: true,
                freeze_message: __("Processing Settlement..."),
                callback: function (r) {
                    if (!r.exc) {
                        frm.reload_doc();
                        frappe.show_alert({
                            message: __("Settlement complete. Journal Entry {0} created.", [r.message]),
                            indicator: "green"
                        });
                    }
                }
            });
        }
    });

    d.show();
}
