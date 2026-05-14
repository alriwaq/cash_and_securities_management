/**
 * Purchase Invoice — Custody Mode Client Script
 *
 * For custody-linked PIs, this script:
 *   1. Toggles supplier/custodian field visibility
 *   2. Hides ALL standard "Create > Payment" and "Make > Payment" buttons
 *      (custody settlement must be initiated from the Accountant Custody form)
 *   3. Shows an info banner directing the user to the AC form for actions
 *   4. Makes custody link fields read-only on submitted docs
 */
frappe.ui.form.on("Purchase Invoice", {
	refresh(frm) {
		apply_custody_pi_ui(frm);
	},
	custom_source_document_type(frm) {
		apply_custody_pi_ui(frm);
	},
	custom_accountant_custody(frm) {
		apply_custody_pi_ui(frm);
	},
});

function apply_custody_pi_ui(frm) {
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

	// ── Remove ALL standard payment/make buttons for custody PIs ─────────
	// ERPNext adds these in various forms depending on version
	setTimeout(function () {
		frm.remove_custom_button(__("Payment"), __("Create"));
		frm.remove_custom_button("Payment", "Create");
		frm.remove_custom_button(__("Payment"), __("Make"));
		frm.remove_custom_button("Payment", "Make");
		frm.remove_custom_button(__("Payment Entry"), __("Create"));
		frm.remove_custom_button("Payment Entry", "Create");
	}, 500);

	// ── Show info banner for submitted custody PIs ───────────────────────
	if (frm.doc.docstatus === 1 && frm.doc.custom_accountant_custody) {
		var ac_link =
			'<a href="/app/accountant-custody/' +
			frm.doc.custom_accountant_custody +
			'">' +
			frm.doc.custom_accountant_custody +
			"</a>";
		frm.set_intro(
			__(
				"This is a Custody Purchase Invoice. Settlement and payment actions must be performed from the Accountant Custody form: {0}",
				[ac_link]
			),
			"blue"
		);
	}
}
