// Custody Request — Client Script
// Cash and Securities Management App

frappe.ui.form.on("Custody Request", {

	// ─── Form Setup ─────────────────────────────────────────────────────────

	setup(frm) {
		frm.set_query("employee", () => ({
			filters: { status: "Active" }
		}));

		frm.set_query("advance_account", () => ({
			filters: {
				account_type: "Receivable",
				company: frm.doc.company,
				is_group: 0
			}
		}));
	},

	// ─── Refresh ────────────────────────────────────────────────────────────

	refresh(frm) {
		frm.trigger("set_status_indicator");
		frm.trigger("add_action_buttons");
	},

	set_status_indicator(frm) {
		const color_map = {
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

	add_action_buttons(frm) {
		// Show linked Accountant Custody records
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("View Accountant Custodies"), () => {
				frappe.set_route("List", "Accountant Custody", {
					custody_request: frm.doc.name
				});
			}, __("Links"));
		}
	},

	// ─── Field Events ────────────────────────────────────────────────────────

	employee(frm) {
		if (frm.doc.employee) {
			frappe.db.get_value("Employee", frm.doc.employee, ["company", "department"], (r) => {
				frm.set_value("company", r.company);
				frm.set_value("department", r.department);
			});
			frm.trigger("load_default_advance_account");
		}
	},

	load_default_advance_account(frm) {
		frappe.db.get_single_value("Cash and Securities Settings", "custody_advance_account").then((account) => {
			if (account && !frm.doc.advance_account) {
				frm.set_value("advance_account", account);
			}
		});
	},

	advance_amount(frm) {
		frm.trigger("calculate_remaining_balance");
	},

	claimed_amount(frm) {
		frm.trigger("calculate_remaining_balance");
	},

	calculate_remaining_balance(frm) {
		const remaining = flt(frm.doc.advance_amount) - flt(frm.doc.claimed_amount);
		frm.set_value("remaining_balance", remaining);
	}
});
