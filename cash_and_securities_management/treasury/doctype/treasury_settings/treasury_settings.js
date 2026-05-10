// Treasury Settings — v2.1
// Client-side controller for the Treasury Settings singleton.
//
// Provides:
//   1. "Create Account Groups" button — calls server action to auto-create
//      the Advances and Payables group accounts.
//   2. accounting_mode toggle — shows/hides helper text and adjusts field
//      requirements based on Consolidated vs Individual mode.

frappe.ui.form.on("Treasury Settings", {
	refresh(frm) {
		frm.add_custom_button(
			__("Create Account Groups"),
			() => {
				frappe.confirm(
					__(
						"This will auto-create 'Advances to Custodians' and 'Custodian Payables' " +
						"group accounts under your chart of accounts. Continue?"
					),
					() => {
						frm.call({
							method: "create_account_groups",
							freeze: true,
							freeze_message: __("Creating account groups…"),
							callback(r) {
								if (!r.exc) {
									frm.reload_doc();
								}
							},
						});
					}
				);
			},
			__("Actions")
		);

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
