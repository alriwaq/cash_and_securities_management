/**
 * Payment Entry — Vault Approval Client Script
 *
 * Applies ONLY to Cash Payment Entries.
 * Replaces the Frappe Workflow document (which was hijacking ALL Payment Entries)
 * with a programmatic approach:
 *  - Non-cash PEs: untouched — native Save/Submit buttons work normally.
 *  - Cash PEs (Draft): Submit button hidden; custom "إرسال للموافقة" button shown.
 *  - Cash PEs (Pending Vault Approval): form is read-only; status banner shown.
 *  - Cash PEs (Vault Approved): banner shown; native Submit available.
 */

frappe.ui.form.on("Payment Entry", {
	refresh(frm) {
		apply_vault_ui(frm);
	},
	mode_of_payment(frm) {
		apply_vault_ui(frm);
	},
});

function apply_vault_ui(frm) {
	// Only act on Draft documents
	if (frm.doc.docstatus !== 0) return;

	// Only act on Cash payment mode
	if ((frm.doc.mode_of_payment || "").toLowerCase() !== "cash") return;

	const state = (frm.doc.workflow_state || "Draft").trim();

	// ── Hide the native Submit button for cash PEs not yet vault-approved ──
	// We use a short timeout because Frappe renders toolbar buttons after refresh.
	if (state !== "Vault Approved") {
		setTimeout(() => {
			frm.page.inner_toolbar.find('[data-label="Submit"]').hide();
			// Also hide from the actions dropdown if present
			frm.page.menu.find('[data-label="Submit"]').hide();
		}, 100);
	}

	// ── Draft: show "Send for Vault Approval" button ────────────────────────
	if (state === "Draft" || !state) {
		frm.add_custom_button(
			__("إرسال للموافقة / Send for Vault Approval"),
			function () {
				frappe.confirm(
					__("إرسال سند الدفع النقدي للموافقة من مسؤول الخزينة؟\n\nSend this Cash Payment Entry for Vault Approval?"),
					function () {
						frappe.call({
							method: "cash_and_securities_management.treasury.doctype.vault_pending_item.vault_pending_hooks.send_cash_pe_for_vault_approval",
							args: { pe_name: frm.doc.name },
							freeze: true,
							freeze_message: __("جاري الإرسال..."),
							callback(r) {
								if (!r.exc) {
									frm.reload_doc();
								}
							},
						});
					}
				);
			},
			__("الخزينة / Vault")
		);
	}

	// ── Status banners ──────────────────────────────────────────────────────
	if (state === "Pending Vault Approval") {
		frm.set_intro(
			__("⏳ في انتظار موافقة مسؤول الخزينة — لا يمكن تعديل السند حتى تتم الموافقة أو الرفض.<br>Pending Vault Approval — awaiting teller confirmation in the cockpit."),
			"yellow"
		);
	} else if (state === "Vault Approved") {
		frm.set_intro(
			__("✅ تمت الموافقة على السند من مسؤول الخزينة. سيتم ترحيله عبر سجل يومية الخزينة.<br>Vault Approved — will be posted via Treasury Cash Journal."),
			"green"
		);
	} else if (state === "Rejected") {
		frm.set_intro(
			__("❌ تم رفض السند من مسؤول الخزينة. يمكن تعديله وإعادة إرساله.<br>Rejected by vault — you may edit and resubmit for approval."),
			"red"
		);
		// Allow re-sending after rejection
		frm.add_custom_button(
			__("إعادة الإرسال / Resubmit for Approval"),
			function () {
				frappe.confirm(
					__("إعادة إرسال السند للموافقة؟\n\nResubmit for Vault Approval?"),
					function () {
						frappe.call({
							method: "cash_and_securities_management.treasury.doctype.vault_pending_item.vault_pending_hooks.send_cash_pe_for_vault_approval",
							args: { pe_name: frm.doc.name, allow_resubmit: true },
							freeze: true,
							freeze_message: __("جاري الإرسال..."),
							callback(r) {
								if (!r.exc) {
									frm.reload_doc();
								}
							},
						});
					}
				);
			},
			__("الخزينة / Vault")
		);
	}
}
