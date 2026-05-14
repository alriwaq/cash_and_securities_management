/**
 * Purchase Receipt — Custody Mode Client Script
 *
 * For custody-linked PRs, this script:
 *   1. Toggles supplier/custodian field visibility
 *   2. Hides standard "Create > Purchase Invoice" button
 *      (invoice creation must be initiated from the Accountant Custody form)
 *   3. Shows an info banner directing the user to the AC form for actions
 *   4. Makes custody link fields read-only on submitted docs
 */
frappe.ui.form.on("Purchase Receipt", {
	refresh(frm) {
		apply_custody_pr_ui(frm);
	},
	custom_source_document_type(frm) {
		apply_custody_pr_ui(frm);
	},
	custom_accountant_custody(frm) {
		apply_custody_pr_ui(frm);
	},
});

function apply_custody_pr_ui(frm) {
	const isCustody =
		frm.doc.custom_source_document_type === "Custody" ||
		Boolean(frm.doc.custom_accountant_custody);

	if (!isCustody) {
		return;
	}

	// ── Toggle supplier / custodian visibility ───────────────────────────
	frm.toggle_display("supplier", false);
	frm.set_df_property("supplier", "read_only", 1);
	frm.set_df_property("supplier", "reqd", 0);
	frm.toggle_display("custom_custodian", true);

	// ── Make custody fields read-only on submitted docs ──────────────────
	if (frm.doc.docstatus >= 1) {
		frm.set_df_property("custom_accountant_custody", "read_only", 1);
		frm.set_df_property("custom_custodian", "read_only", 1);
		frm.set_df_property("custom_source_document_type", "read_only", 1);
	}

	// ── Remove standard "Create > Purchase Invoice" button ───────────────
	// ERPNext adds this on submitted PRs — for custody flow, PI must be
	// created from the AC form to ensure proper linking and validation.
	setTimeout(function () {
		frm.remove_custom_button(__("Purchase Invoice"), __("Create"));
		frm.remove_custom_button("Purchase Invoice", "Create");
		frm.remove_custom_button(__("Make Purchase Invoice"));
		frm.remove_custom_button("Make Purchase Invoice");
		// Also remove Return and other standard buttons that could bypass custody flow
		frm.remove_custom_button(__("Purchase Return"), __("Create"));
		frm.remove_custom_button("Purchase Return", "Create");
	}, 500);

	// ── Show info banner for submitted custody PRs ───────────────────────
	if (frm.doc.docstatus === 1 && frm.doc.custom_accountant_custody) {
		var ac_link =
			'<a href="/app/accountant-custody/' +
			frm.doc.custom_accountant_custody +
			'">' +
			frm.doc.custom_accountant_custody +
			"</a>";
		frm.set_intro(
			__(
				"This is a Custody Purchase Receipt. Invoice creation and further actions must be performed from the Accountant Custody form: {0}",
				[ac_link]
			),
			"blue"
		);
	}
}
