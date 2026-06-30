// Accountant Custody DocType — Client-side controller (v15)
// Architecture: JS (UI) → api.py (service boundary) → DocType method (engine)
// Single-Account Self-Settling Model: PI credit_to = custody_account clears the advance.
frappe.ui.form.on("Accountant Custody", {
    // ── Form lifecycle ────────────────────────────────────────────────────
    refresh: function (frm) {
        setup_form_intro(frm);
        setup_action_buttons(frm);
    },

    onload: function (frm) {
        // Filter employee field: only employees who have an active Custodian record
        frm.set_query("employee", function () {
            return {
                query: "cash_and_securities_management.treasury.doctype.accountant_custody.accountant_custody.get_employees_with_custodian"
            };
        });
    },

    employee: function (frm) {
        if (frm.doc.employee) {
            // Fetch basic employee info
            frappe.db.get_value(
                "Employee",
                frm.doc.employee,
                ["employee_name", "department", "company"],
                function (r) {
                    if (r) {
                        frm.set_value("employee_name", r.employee_name);
                        if (!frm.doc.department) frm.set_value("department", r.department);
                        if (!frm.doc.company) frm.set_value("company", r.company);
                    }
                }
            );

            // Auto-fill custodian from the active Custodian record for this employee
            frappe.call({
                method: "cash_and_securities_management.treasury.doctype.accountant_custody.accountant_custody.get_custodian_for_employee",
                args: { employee: frm.doc.employee },
                callback: function (r) {
                    if (r.message) {
                        frm.set_value("custodian", r.message);
                    } else {
                        frm.set_value("custodian", "");
                        frappe.msgprint({
                            title: __("No Active Custodian"),
                            message: __("No active Custodian record found for the selected employee."),
                            indicator: "orange"
                        });
                    }
                }
            });
        } else {
            frm.set_value("custodian", "");
        }
    },

    custodian: function (frm) {
        if (frm.doc.custodian) {
            frappe.db.get_value(
                "Custodian",
                frm.doc.custodian,
                ["employee", "employee_name", "company", "department"],
                function (r) {
                    if (r) {
                        if (!frm.doc.company) frm.set_value("company", r.company);
                        if (!frm.doc.employee) frm.set_value("employee", r.employee);
                        if (!frm.doc.employee_name) frm.set_value("employee_name", r.employee_name);
                        if (!frm.doc.department) frm.set_value("department", r.department);
                    }
                }
            );
        }
    },

    // ── Propagate parent dimensions to all existing child rows ────────────
    project: function (frm) {
        propagate_to_all_rows(frm, "project", frm.doc.project);
    },

    cost_center: function (frm) {
        propagate_to_all_rows(frm, "cost_center", frm.doc.cost_center);
    },

    warehouse: function (frm) {
        propagate_to_all_rows(frm, "warehouse", frm.doc.warehouse);
    },

});

// ── Child table events ────────────────────────────────────────────────────────
frappe.ui.form.on("Accountant Custody Item", {
    item_code: function (frm, cdt, cdn) {
        var row = locals[cdt][cdn];
        if (row.item_code) {
            // Always fill from parent when item is selected (overwrite empty fields)
            if (frm.doc.project && !row.project) {
                frappe.model.set_value(cdt, cdn, "project", frm.doc.project);
            }
            if (frm.doc.cost_center && !row.cost_center) {
                frappe.model.set_value(cdt, cdn, "cost_center", frm.doc.cost_center);
            }
            if (frm.doc.warehouse && !row.warehouse) {
                frappe.model.set_value(cdt, cdn, "warehouse", frm.doc.warehouse);
            }
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

// ── Form Intro ────────────────────────────────────────────────────────────────
function setup_form_intro(frm) {
    if (!frm.doc.docstatus) return;
    var status_messages = {
        "Pending":          ["blue",   "Awaiting Purchase Receipt creation."],
        "Partly Received":  ["orange", "Some items received. Create remaining receipts."],
        "Fully Received":   ["blue",   "All items received. Ready to generate Purchase Invoice."],
        "Partly Invoiced":  ["orange", "Partially invoiced. Complete remaining invoices."],
        "Fully Invoiced":   ["green",  "Fully invoiced. Custody advance is self-settled via PI credit."],
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

    // ── Create Purchase Receipt — only shown when stock/asset items exist ──
    var has_stock_items = (frm.doc.custody_items || []).some(function (item) {
        return item.is_stock_item || item.is_fixed_asset;
    });
    if (["Pending", "Partly Received"].indexOf(status) !== -1 && has_stock_items) {
        frm.add_custom_button(__("Create Purchase Receipt"), function () {
            frappe.call({
                method: "cash_and_securities_management.api.create_custody_purchase_receipt",
                args: {
                    accountant_custody: frm.doc.name,
                },
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
    if (["Pending", "Fully Received", "Partly Received", "Partly Invoiced"].indexOf(status) !== -1) {
        frm.add_custom_button(__("Generate Purchase Invoice"), function () {
            frappe.call({
                method: "cash_and_securities_management.api.generate_custody_purchase_invoice",
                args: {
                    accountant_custody: frm.doc.name,
                },
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
}

// ── Helper Functions ──────────────────────────────────────────────────────────

/**
 * Propagate a parent-level dimension (project / cost_center / warehouse)
 * to ALL existing child rows that currently have no value for that field.
 * Called when the parent field changes.
 */
function propagate_to_all_rows(frm, fieldname, value) {
    if (!value) return;
    (frm.doc.custody_items || []).forEach(function (row) {
        if (!row[fieldname]) {
            frappe.model.set_value(row.doctype, row.name, fieldname, value);
        }
    });
}

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
