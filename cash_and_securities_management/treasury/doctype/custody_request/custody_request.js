// Custody Request — Client Script
// Cash and Securities Management App

frappe.ui.form.on("Custody Request", {

    // ─── Form Setup ─────────────────────────────────────────────────────────

    setup: function (frm) {
        // Filter: only Active employees
        frm.set_query("employee", function () {
            return {
                filters: { status: "Active" }
            };
        });

        // Filter: only submitted, non-closed Custodians for the selected employee
        frm.set_query("custodian", function () {
            return {
                filters: {
                    employee: frm.doc.employee || undefined,
                    docstatus: 1,
                    status: ["in", ["Active", "Suspended"]]
                }
            };
        });

        // Filter: Receivable accounts for the company
        frm.set_query("advance_account", function () {
            return {
                filters: {
                    account_type: "Receivable",
                    company: frm.doc.company,
                    is_group: 0
                }
            };
        });
    },

    // ─── Refresh ────────────────────────────────────────────────────────────

    refresh: function (frm) {
        frm.trigger("set_status_indicator");
        frm.trigger("add_action_buttons");
        frm.trigger("show_custodian_alert");
    },

    set_status_indicator: function (frm) {
        var color_map = {
            "Draft": "red",
            "Unpaid": "orange",
            "Paid": "green",
            "Claimed": "blue",
            "Partly Claimed": "yellow",
            "Cancelled": "red"
        };
        if (frm.doc.status) {
            frm.page.set_indicator(frm.doc.status, color_map[frm.doc.status] || "gray");
        }
    },

    add_action_buttons: function (frm) {
        if (frm.doc.docstatus === 1) {
            frm.add_custom_button(__("View Accountant Custodies"), function () {
                frappe.set_route("List", "Accountant Custody", {
                    custody_request: frm.doc.name
                });
            }, __("Links"));

            frm.add_custom_button(__("View Custodian"), function () {
                frappe.set_route("Form", "Custodian", frm.doc.custodian);
            }, __("Links"));
        }
    },

    show_custodian_alert: function (frm) {
        if (frm.doc.custodian_status === "Suspended") {
            frm.dashboard.add_comment(
                __("Warning: The custodian for this employee is currently Suspended. This request cannot be submitted until the custodian is reactivated."),
                "orange",
                true
            );
        }
    },

    // ─── Field Events ────────────────────────────────────────────────────────

    employee: function (frm) {
        if (!frm.doc.employee) return;

        // Auto-find and set the active Custodian for this employee
        frappe.db.get_value(
            "Custodian",
            {
                employee: frm.doc.employee,
                docstatus: 1,
                status: ["in", ["Active", "Suspended"]]
            },
            "name",
            function (r) {
                if (r && r.name) {
                    frm.set_value("custodian", r.name);
                } else {
                    frm.set_value("custodian", null);
                    frappe.msgprint({
                        title: __("No Active Custodian"),
                        message: __("No active Custodian record found for employee {0}. Please create a Custodian record first.", [frm.doc.employee_name || frm.doc.employee]),
                        indicator: "orange"
                    });
                }
            }
        );
    },

    custodian: function (frm) {
        if (!frm.doc.custodian) return;
        frm.trigger("load_account_from_custodian");
    },

    load_account_from_custodian: function (frm) {
        if (!frm.doc.custodian) return;
        frappe.db.get_value("Custodian", frm.doc.custodian, "custody_account", function (r) {
            if (r && r.custody_account && !frm.doc.advance_account) {
                frm.set_value("advance_account", r.custody_account);
            }
        });
    },

    advance_amount: function (frm) {
        frm.trigger("calculate_remaining_balance");
    },

    claimed_amount: function (frm) {
        frm.trigger("calculate_remaining_balance");
    },

    calculate_remaining_balance: function (frm) {
        var remaining = flt(frm.doc.advance_amount) - flt(frm.doc.claimed_amount);
        frm.set_value("remaining_balance", remaining);
    }

});
