// Custodian — Client-side controller
// Handles action buttons, real-time balance refresh, and conditional field visibility.

frappe.ui.form.on("Custodian", {

    // ── Form Load ──────────────────────────────────────────────────────────

    refresh(frm) {
        frm._setup_action_buttons();
        frm._refresh_supplier_visibility();
        frm._setup_dashboard_indicators();
    },

    // ── Field Events ───────────────────────────────────────────────────────

    employee(frm) {
        if (frm.doc.employee) {
            frm.set_value("employee_name", null);
            frm.set_value("department", null);
            frm.set_value("company", null);
        }
    },

    // ── Private Helpers ────────────────────────────────────────────────────

    _setup_action_buttons(frm) {
        // Only show action buttons on submitted documents
        if (frm.doc.docstatus !== 1) return;

        if (frm.doc.status === "Active") {
            frm.add_custom_button(__("Suspend"), () => {
                frappe.confirm(
                    __("Are you sure you want to suspend this custodian? New Custody Requests will be blocked."),
                    () => {
                        frm.call("suspend").then(() => {
                            frm.reload_doc();
                            frappe.show_alert({ message: __("Custodian suspended."), indicator: "orange" });
                        });
                    }
                );
            }, __("Actions"));
        }

        if (frm.doc.status === "Suspended") {
            frm.add_custom_button(__("Reactivate"), () => {
                frm.call("reactivate").then(() => {
                    frm.reload_doc();
                    frappe.show_alert({ message: __("Custodian reactivated."), indicator: "green" });
                });
            }, __("Actions"));
        }

        if (["Active", "Suspended"].includes(frm.doc.status)) {
            frm.add_custom_button(__("Close Custodian"), () => {
                frappe.confirm(
                    __("Closing this custodian is permanent and cannot be undone. "
                        "Ensure all outstanding balances are settled. Continue?"),
                    () => {
                        frm.call("close").then(() => {
                            frm.reload_doc();
                            frappe.show_alert({ message: __("Custodian closed."), indicator: "red" });
                        });
                    }
                );
            }, __("Actions"));
        }

        // Refresh balance button — always visible on submitted docs
        frm.add_custom_button(__("Refresh Balances"), () => {
            frm.call("refresh_outstanding").then(() => {
                frm.reload_doc();
                frappe.show_alert({ message: __("Balances updated."), indicator: "blue" });
            });
        }, __("Actions"));
    },

    _refresh_supplier_visibility(frm) {
        // The depends_on expression in the JSON handles visibility automatically.
        // This function is a placeholder for any additional JS-side logic.
    },

    _setup_dashboard_indicators(frm) {
        if (frm.doc.docstatus !== 1) return;

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
            const pct = Math.round((frm.doc.total_outstanding / frm.doc.custody_limit) * 100);
            const color = pct >= 90 ? "red" : pct >= 70 ? "orange" : "green";
            frm.dashboard.add_indicator(
                __("Limit Used: {0}%", [pct]),
                color
            );
        }
    },
});
