// Custody Request — Client-side controller
// Cash and Securities Management App

frappe.ui.form.on("Custody Request", {

    // ─── Form Setup ─────────────────────────────────────────────────────────

    setup: function (frm) {
        // Filter: only Active employees
        frm.set_query("employee", function () {
            return { filters: { status: "Active" } };
        });

        // Filter: only Active custodians for the selected employee
        frm.set_query("custodian", function () {
            var filters = { docstatus: 1, status: "Active" };
            if (frm.doc.employee) {
                filters.employee = frm.doc.employee;
            }
            return { filters: filters };
        });
    },

    // ─── Refresh ────────────────────────────────────────────────────────────

    refresh: function (frm) {
        frm.set_intro("");
        frm.clear_custom_buttons();

        // Show Create Payment button for approved/partly-paid submitted requests
        if (
            frm.doc.docstatus === 1
            && ["Approved", "Partly Paid"].indexOf(frm.doc.status) !== -1
        ) {
            frm.add_custom_button(__("Create Payment Entry"), function () {
                frappe.confirm(
                    __("This will create a Payment Entry for {0}. Continue?", [
                        format_currency(frm.doc.advance_amount)
                    ]),
                    function () {
                        frm.call("create_payment_entry").then(function (r) {
                            if (r && r.message) {
                                frappe.set_route("Form", "Payment Entry", r.message);
                            } else {
                                frm.reload_doc();
                            }
                        });
                    }
                );
            }).addClass("btn-primary");
        }

        // Refresh Amounts button for submitted docs
        if (frm.doc.docstatus === 1) {
            frm.add_custom_button(__("Refresh Amounts"), function () {
                frm.call("refresh_amounts").then(function () {
                    frm.reload_doc();
                });
            }, __("Actions"));

            frm.add_custom_button(__("View Custodian"), function () {
                frappe.set_route("Form", "Custodian", frm.doc.custodian);
            }, __("Links"));

            frm.add_custom_button(__("View Accountant Custodies"), function () {
                frappe.set_route("List", "Accountant Custody", {
                    custody_request: frm.doc.name
                });
            }, __("Links"));
        }

        // Show warning if custodian is not Active
        if (frm.doc.custodian_status && frm.doc.custodian_status !== "Active") {
            frm.set_intro(
                __("Warning: Custodian is currently {0}. This request cannot be submitted.", [
                    frm.doc.custodian_status
                ]),
                "orange"
            );
        }
    },

    // ─── Field Events ────────────────────────────────────────────────────────

    employee: function (frm) {
        if (!frm.doc.employee) {
            frm.set_value("custodian", "");
            frm.set_value("advance_account", "");
            return;
        }

        // Auto-lookup the active Custodian for this employee
        frappe.db.get_value("Custodian", {
            employee: frm.doc.employee,
            docstatus: 1,
            status: "Active"
        }, ["name", "custody_account"], function (r) {
            if (r && r.name) {
                frm.set_value("custodian", r.name);
                frm.set_value("advance_account", r.custody_account || "");
            } else {
                frm.set_value("custodian", "");
                frm.set_value("advance_account", "");
                frappe.show_alert({
                    message: __("No active Custodian found for this employee. Please create one first."),
                    indicator: "orange"
                }, 7);
            }
        });
    },

    custodian: function (frm) {
        if (!frm.doc.custodian) {
            frm.set_value("advance_account", "");
            return;
        }
        // Lock the advance account to the custodian's account
        frappe.db.get_value("Custodian", frm.doc.custodian, "custody_account", function (r) {
            if (r && r.custody_account) {
                frm.set_value("advance_account", r.custody_account);
            }
        });
    },

    advance_amount: function (frm) {
        calculate_unallocated(frm);
    },

    paid_amount: function (frm) {
        calculate_unallocated(frm);
    },

    claimed_amount: function (frm) {
        calculate_unallocated(frm);
    }
});

function calculate_unallocated(frm) {
    var unallocated = flt(frm.doc.paid_amount) - flt(frm.doc.claimed_amount);
    frm.set_value("unallocated_amount", unallocated);
}
