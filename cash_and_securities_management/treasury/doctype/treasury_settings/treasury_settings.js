// Treasury Settings — v2.1
// Client-side controller for the Treasury Settings singleton.
//
// Account groups are auto-created by the install/migrate hook in setup.py.
// This controller only handles the accounting_mode UI toggle.

frappe.ui.form.on("Treasury Settings", {
	refresh(frm) {
		// Reflect current mode on load
		frm.trigger("accounting_mode");
	},

	accounting_mode(frm) {
		const mode = frm.doc.accounting_mode;
		const isIndividual = mode === "Individual (Account-Based)";

		// In Individual mode both group fields are required
		frm.set_df_property("custody_advance_group", "reqd", isIndividual ? 1 : 0);
		frm.set_df_property("custodian_payable_group", "reqd", isIndividual ? 1 : 0);

		// Show a contextual description below the mode selector
		const desc = isIndividual
			? __(
				"<b>Individual mode:</b> Each custodian will get their own dedicated GL accounts " +
				"(E-{ID}-{Name} - Advance and E-{ID}-{Name} - Payable) created automatically " +
				"under the groups below."
			)
			: __(
				"<b>Consolidated mode:</b> All custodians share the group accounts below. " +
				"The Custodian is set as the Party on every GL entry to isolate individual balances."
			);
		frm.set_df_property("accounting_mode", "description", desc);
	},
});
