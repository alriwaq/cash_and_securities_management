frappe.ui.form.on("Purchase Invoice", {
	refresh(frm) {
		apply_custody_ui(frm);
	},
	custom_source_document_type(frm) {
		apply_custody_ui(frm);
	},
	custom_accountant_custody(frm) {
		apply_custody_ui(frm);
	},
});

function apply_custody_ui(frm) {
	const isCustody =
		frm.doc.custom_source_document_type === "Custody" ||
		Boolean(frm.doc.custom_accountant_custody);

	frm.toggle_display("supplier", !isCustody);
	frm.set_df_property("supplier", "read_only", isCustody ? 1 : 0);
	frm.set_df_property("supplier", "reqd", isCustody ? 0 : 1);
	frm.toggle_display("custom_custodian", isCustody);
}
