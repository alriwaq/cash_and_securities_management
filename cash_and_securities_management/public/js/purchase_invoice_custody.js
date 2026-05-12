frappe.ui.form.on("Purchase Invoice", {
	refresh(frm) {
		apply_custody_ui(frm);
		setup_custody_payment_button(frm);
	},
	custom_source_document_type(frm) {
		apply_custody_ui(frm);
		setup_custody_payment_button(frm);
	},
	custom_accountant_custody(frm) {
		apply_custody_ui(frm);
		setup_custody_payment_button(frm);
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

function setup_custody_payment_button(frm) {
	const isCustody =
		frm.doc.custom_source_document_type === "Custody" ||
		Boolean(frm.doc.custom_accountant_custody);

	if (!isCustody) {
		return;
	}

	frm.remove_custom_button(__("Payment"), __("Create"));
	frm.remove_custom_button("Payment", "Create");

	if (frm.doc.docstatus !== 1 || flt(frm.doc.outstanding_amount || 0) <= 0) {
		return;
	}

	frm.add_custom_button(__("Custody Payment"), function () {
		frappe.call({
			method: "cash_and_securities_management.api.create_custody_payment_entry_from_pi",
			args: {
				purchase_invoice: frm.doc.name,
			},
			freeze: true,
			freeze_message: __("Creating Custody Payment Entry..."),
			callback: function (r) {
				if (!r.exc && r.message) {
					frappe.set_route("Form", "Payment Entry", r.message);
				}
			},
		});
	}, __("Create")).addClass("btn-primary");
}
