// Custodian DocType — Client-side controller (v2)
// Handles action buttons, dashboard indicators, and field visibility.
frappe.ui.form.on("Custodian", {
    // ── Form lifecycle ────────────────────────────────────────────────────
    refresh: function (frm) {
        refresh_supplier_visibility(frm);
        setup_dashboard_indicators(frm);

        if (frm.doc.docstatus === 1) {
            setup_action_buttons(frm);
        }
    },

    employee: function (frm) {
        if (frm.doc.employee) {
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
        }
    },
});

// ── Action Buttons ────────────────────────────────────────────────────────────
function setup_action_buttons(frm) {
    // Refresh Balances — always visible as a top-level button for submitted docs
    frm.add_custom_button(__("Refresh Balances"), function () {
        frm.call("refresh_outstanding").then(function () {
            frm.reload_doc();
            frappe.show_alert({ message: __("Balances refreshed."), indicator: "green" });
        });
    }).addClass("btn-primary");

    // ── Actions menu ──────────────────────────────────────────────────────
    if (frm.doc.status === "Active") {
        frm.add_custom_button(__("Change Limit"), function () {
            var d = new frappe.ui.Dialog({
                title: __("Change Custody Limit"),
                fields: [
                    {
                        fieldname: "new_limit",
                        fieldtype: "Currency",
                        label: __("New Limit"),
                        reqd: 1,
                        default: frm.doc.custody_limit,
                        description: __("Set to 0 for unlimited. Current limit: {0}", [
                            format_currency(frm.doc.custody_limit)
                        ])
                    }
                ],
                primary_action_label: __("Update Limit"),
                primary_action: function (values) {
                    frm.call("change_limit", { new_limit: values.new_limit }).then(function () {
                        d.hide();
                        frm.reload_doc();
                    });
                }
            });
            d.show();
        }, __("Actions"));

        frm.add_custom_button(__("Suspend"), function () {
            frappe.confirm(
                __("Are you sure you want to suspend custodian {0}?", [frm.doc.name]),
                function () {
                    frm.call("suspend").then(function () { frm.reload_doc(); });
                }
            );
        }, __("Actions"));

        frm.add_custom_button(__("Close Custodian"), function () {
            frappe.confirm(
                __("Closing custodian {0} is permanent. Continue?", [frm.doc.name]),
                function () {
                    frm.call("close").then(function () { frm.reload_doc(); });
                }
            );
        }, __("Actions"));
    }

    if (frm.doc.status === "Suspended") {
        frm.add_custom_button(__("Reactivate"), function () {
            frm.call("reactivate").then(function () { frm.reload_doc(); });
        }, __("Actions"));
    }

    // Recreate Accounts — useful if Treasury Settings were configured after submit
    if (!frm.doc.custody_account || !frm.doc.liability_account) {
        frm.add_custom_button(__("Create Sub-Ledger Accounts"), function () {
            frm.call("recreate_accounts").then(function () { frm.reload_doc(); });
        }, __("Actions"));
    }
}

// ── Supplier Section Visibility ───────────────────────────────────────────────
function refresh_supplier_visibility(frm) {
    frappe.db.get_single_value("Treasury Settings", "use_single_dummy_supplier")
        .then(function (val) {
            var show = !val;
            frm.toggle_display("supplier_section", show);
            frm.toggle_display("dedicated_supplier", show);
        })
        .catch(function () {
            frm.toggle_display("supplier_section", true);
            frm.toggle_display("dedicated_supplier", true);
        });
}

// ── Dashboard Indicators ──────────────────────────────────────────────────────
function setup_dashboard_indicators(frm) {
    if (!frm.dashboard) return;

    // Outstanding balance indicator
    if (frm.doc.total_outstanding > 0) {
        frm.dashboard.add_indicator(
            __("Outstanding: {0}", [format_currency(frm.doc.total_outstanding)]),
            "orange"
        );
    } else {
        frm.dashboard.add_indicator(__("No Outstanding Balance"), "green");
    }

    // Custody limit utilisation
    if (frm.doc.custody_limit > 0) {
        var pct = Math.round((frm.doc.total_outstanding / frm.doc.custody_limit) * 100);
        var color = pct >= 90 ? "red" : pct >= 70 ? "orange" : "green";
        frm.dashboard.add_indicator(
            __("Limit Used: {0}%", [pct]),
            color
        );
    }

    // Pending requests indicator
    if (frm.doc.pending_requests > 0) {
        frm.dashboard.add_indicator(
            __("Pending Requests: {0}", [format_currency(frm.doc.pending_requests)]),
            "blue"
        );
    }

    // Pending settlements indicator
    if (frm.doc.pending_settlements > 0) {
        frm.dashboard.add_indicator(
            __("Pending Settlements: {0}", [format_currency(frm.doc.pending_settlements)]),
            "yellow"
        );
    }

    // Sub-ledger account status
    if (frm.doc.docstatus === 1) {
        if (frm.doc.custody_account && frm.doc.liability_account) {
            frm.dashboard.add_indicator(__("Sub-Ledgers: Active"), "green");
        } else {
            frm.dashboard.add_indicator(__("Sub-Ledgers: Incomplete"), "red");
        }
    }
}
