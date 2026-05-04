// Custodian — Client-side controller
// Handles action buttons, real-time balance refresh, and conditional field visibility.

frappe.ui.form.on("Custodian", {

    // ── Form Setup ────────────────────────────────────────────────────────

    setup: function (frm) {
        // Filter: only Active employees can be assigned as custodians
        frm.set_query("employee", function () {
            return {
                filters: { status: "Active" }
            };
        });
    },

    // ── Form Load ──────────────────────────────────────────────────────────

    refresh: function (frm) {
        // Clear any previous intro messages and custom buttons
        frm.set_intro("");
        frm.clear_custom_buttons();

        // Each helper is wrapped so a failure in one does not block the others
        try {
            refresh_supplier_visibility(frm);
        } catch (e) {
            console.error("Custodian: refresh_supplier_visibility error", e);
        }

        // Only show action buttons on submitted documents
        if (frm.doc.docstatus === 1) {
            try {
                setup_action_buttons(frm);
            } catch (e) {
                console.error("Custodian: setup_action_buttons error", e);
            }

            try {
                setup_dashboard_indicators(frm);
            } catch (e) {
                console.error("Custodian: setup_dashboard_indicators error", e);
            }
        }
    },

    // ── Field Events ───────────────────────────────────────────────────────

    employee: function (frm) {
        if (!frm.doc.employee) {
            frm.set_value("employee_name", null);
            frm.set_value("department", null);
            frm.set_value("company", null);
        }
        // When employee IS set, fetch_from in the JSON handles auto-population
    }
});

// ── Helper Functions ───────────────────────────────────────────────────────

function setup_action_buttons(frm) {
    // Status-based action buttons inside the "Actions" dropdown
    if (frm.doc.status === "Active") {
        frm.add_custom_button(__("Suspend"), function () {
            frappe.confirm(
                __("Are you sure you want to suspend this custodian? New Custody Requests will be blocked."),
                function () {
                    frm.call("suspend").then(function () {
                        frm.reload_doc();
                    });
                }
            );
        }, __("Actions"));
    }

    if (frm.doc.status === "Suspended") {
        frm.add_custom_button(__("Reactivate"), function () {
            frm.call("reactivate").then(function () {
                frm.reload_doc();
            });
        }, __("Actions"));
    }

    if (frm.doc.status === "Active" || frm.doc.status === "Suspended") {
        frm.add_custom_button(__("Close Custodian"), function () {
            frappe.confirm(
                __("Closing this custodian is permanent. Ensure all outstanding balances are settled. Continue?"),
                function () {
                    frm.call("close").then(function () {
                        frm.reload_doc();
                    });
                }
            );
        }, __("Actions"));
    }

    // Refresh balance button — always visible on submitted docs
    frm.add_custom_button(__("Refresh Balances"), function () {
        frm.call("refresh_outstanding").then(function () {
            frm.reload_doc();
        });
    }, __("Actions"));

    // Change Limit button — available unless custodian is Closed
    if (frm.doc.status !== "Closed") {
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
        });
    }
}

function refresh_supplier_visibility(frm) {
    // Show/hide the Dedicated Supplier section based on Treasury Settings.
    frappe.db.get_single_value("Treasury Settings", "use_single_dummy_supplier")
        .then(function (val) {
            var show = !val;
            frm.toggle_display("supplier_section", show);
            frm.toggle_display("dedicated_supplier", show);
        })
        .catch(function () {
            // Treasury Settings may not exist yet — default to showing the section
            frm.toggle_display("supplier_section", true);
            frm.toggle_display("dedicated_supplier", true);
        });
}

function setup_dashboard_indicators(frm) {
    // Guard: ensure the dashboard object is available
    if (!frm.dashboard) return;

    // Show outstanding balance as a colored indicator
    if (frm.doc.total_outstanding > 0) {
        frm.dashboard.add_indicator(
            __("Outstanding: {0}", [format_currency(frm.doc.total_outstanding)]),
            "orange"
        );
    } else {
        frm.dashboard.add_indicator(__("No Outstanding Balance"), "green");
    }

    // Show custody limit utilisation if a limit is set
    if (frm.doc.custody_limit > 0) {
        var pct = Math.round((frm.doc.total_outstanding / frm.doc.custody_limit) * 100);
        var color = pct >= 90 ? "red" : pct >= 70 ? "orange" : "green";
        frm.dashboard.add_indicator(
            __("Limit Used: {0}%", [pct]),
            color
        );
    }
}
