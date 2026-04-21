// Accountant Custody — Client Script
// Cash and Securities Management App

frappe.ui.form.on("Accountant Custody", {

	// ─── Form Setup ─────────────────────────────────────────────────────────

	setup(frm) {
		frm.set_query("employee", () => ({
			filters: { status: "Active" }
		}));

		frm.set_query("custody_request", () => ({
			filters: {
				employee: frm.doc.employee,
				docstatus: 1,
				status: ["in", ["Paid", "Partly Claimed"]]
			}
		}));

		frm.set_query("warehouse", "custody_items", () => ({
			filters: { company: frm.doc.company }
		}));
	},

	// ─── Refresh ────────────────────────────────────────────────────────────

	refresh(frm) {
		frm.trigger("set_status_indicator");
		frm.trigger("add_action_buttons");
		frm.trigger("toggle_fields_by_status");
	},

	set_status_indicator(frm) {
		const color_map = {
			"Draft": "red",
			"Submitted": "orange",
			"Receiving": "yellow",
			"Fully Received": "blue",
			"Invoiced": "purple",
			"Settled": "green",
			"Cancelled": "red"
		};
		if (frm.doc.status) {
			frm.page.set_indicator(frm.doc.status, color_map[frm.doc.status] || "gray");
		}
	},

	add_action_buttons(frm) {
		// Generate Invoice button — visible when status is Receiving or Fully Received
		if (frm.doc.docstatus === 1 && ["Receiving", "Fully Received"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Generate Invoice"), () => {
				frm.trigger("generate_invoice");
			}, __("Actions"));
		}

		// Settle button — visible when status is Invoiced
		if (frm.doc.docstatus === 1 && frm.doc.status === "Invoiced") {
			frm.add_custom_button(__("Settle"), () => {
				frm.trigger("open_settlement_dialog");
			}, __("Actions"));
		}
	},

	toggle_fields_by_status(frm) {
		// Lock the form after settlement
		const is_settled = frm.doc.status === "Settled";
		frm.set_df_property("custody_items", "read_only", is_settled ? 1 : 0);
		frm.set_df_property("custody_request", "read_only", is_settled ? 1 : 0);
	},

	// ─── Field Events ────────────────────────────────────────────────────────

	employee(frm) {
		if (frm.doc.employee) {
			frm.trigger("auto_link_custody_request");
		}
	},

	custody_request(frm) {
		if (frm.doc.custody_request) {
			frappe.db.get_value("Custody Request", frm.doc.custody_request, "remaining_balance", (r) => {
				frm.set_value("custody_request_balance", r.remaining_balance || 0);
			});
		} else {
			frm.set_value("custody_request_balance", 0);
		}
	},

	auto_link_custody_request(frm) {
		if (frm.doc.custody_request || !frm.doc.employee) return;
		frappe.db.get_list("Custody Request", {
			filters: {
				employee: frm.doc.employee,
				docstatus: 1,
				status: ["in", ["Paid", "Partly Claimed"]]
			},
			fields: ["name", "remaining_balance"],
			order_by: "posting_date asc",
			limit: 1
		}).then((results) => {
			if (results.length > 0) {
				frm.set_value("custody_request", results[0].name);
				frm.set_value("custody_request_balance", results[0].remaining_balance || 0);
			}
		});
	},

	// ─── Generate Invoice ────────────────────────────────────────────────────

	generate_invoice(frm) {
		frappe.confirm(
			__("Are you sure you want to generate a Purchase Invoice for this Accountant Custody?"),
			() => {
				frappe.call({
					method: "generate_purchase_invoice",
					doc: frm.doc,
					freeze: true,
					freeze_message: __("Generating Purchase Invoice..."),
					callback(r) {
						if (!r.exc) {
							frm.reload_doc();
							frappe.show_alert({
								message: __("Purchase Invoice {0} created", [r.message]),
								indicator: "green"
							});
						}
					}
				});
			}
		);
	},

	// ─── Settlement Dialog ───────────────────────────────────────────────────

	open_settlement_dialog(frm) {
		const billed_amount = frm.doc.total_billed_amount || 0;
		const request_balance = frm.doc.custody_request_balance || 0;

		const d = new frappe.ui.Dialog({
			title: __("Settle Accountant Custody"),
			fields: [
				{
					fieldname: "settlement_type",
					fieldtype: "Select",
					label: __("Settlement Type"),
					options: [
						"Full Advance Settlement",
						"Full Direct Payment",
						"Mixed Settlement"
					].join("\n"),
					reqd: 1,
					default: frm.doc.custody_request ? "Full Advance Settlement" : "Full Direct Payment",
					onchange() {
						const type = d.get_value("settlement_type");
						d.set_df_property("advance_amount_allocated", "hidden", type === "Full Direct Payment");
						d.set_df_property("direct_payment_amount", "hidden", type === "Full Advance Settlement");
						if (type === "Full Advance Settlement") {
							d.set_value("advance_amount_allocated", billed_amount);
							d.set_value("direct_payment_amount", 0);
						} else if (type === "Full Direct Payment") {
							d.set_value("advance_amount_allocated", 0);
							d.set_value("direct_payment_amount", billed_amount);
						}
					}
				},
				{
					fieldname: "advance_amount_allocated",
					fieldtype: "Currency",
					label: __("Advance Amount Allocated"),
					default: frm.doc.custody_request ? Math.min(billed_amount, request_balance) : 0,
					description: __("Amount from Custody Request advance. Available balance: {0}", [format_currency(request_balance)]),
					onchange() {
						const adv = flt(d.get_value("advance_amount_allocated"));
						const remaining = billed_amount - adv;
						d.set_value("direct_payment_amount", remaining > 0 ? remaining : 0);
					}
				},
				{
					fieldname: "direct_payment_amount",
					fieldtype: "Currency",
					label: __("Direct Payment Amount"),
					default: 0,
					description: __("Amount paid directly (not from advance)")
				},
				{
					fieldname: "total_label",
					fieldtype: "HTML",
					options: `<div class="alert alert-info">
						<strong>${__("Total Billed Amount")}: ${format_currency(billed_amount)}</strong>
					</div>`
				},
				{
					fieldname: "settlement_notes",
					fieldtype: "Small Text",
					label: __("Settlement Notes")
				}
			],
			primary_action_label: __("Settle"),
			primary_action(values) {
				const total = flt(values.advance_amount_allocated || 0) + flt(values.direct_payment_amount || 0);
				if (Math.abs(total - billed_amount) > 0.01) {
					frappe.msgprint(__("Total settlement amount {0} must equal the billed amount {1}.", [
						format_currency(total), format_currency(billed_amount)
					]));
					return;
				}
				d.hide();
				frappe.call({
					method: "create_settlement",
					doc: frm.doc,
					args: {
						settlement_type: values.settlement_type,
						advance_amount_allocated: values.advance_amount_allocated || 0,
						direct_payment_amount: values.direct_payment_amount || 0,
						settlement_notes: values.settlement_notes || ""
					},
					freeze: true,
					freeze_message: __("Processing Settlement..."),
					callback(r) {
						if (!r.exc) {
							frm.reload_doc();
							frappe.show_alert({
								message: __("Settlement complete. Journal Entry {0} created.", [r.message]),
								indicator: "green"
							});
						}
					}
				});
			}
		});

		// Set initial visibility
		if (!frm.doc.custody_request) {
			d.set_df_property("advance_amount_allocated", "hidden", 1);
			d.set_value("settlement_type", "Full Direct Payment");
			d.set_value("direct_payment_amount", billed_amount);
		}

		d.show();
	}
});

// ─── Child Table: Accountant Custody Item ────────────────────────────────────

frappe.ui.form.on("Accountant Custody Item", {

	item_code(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.item_code) {
			frappe.db.get_value("Item", row.item_code, ["is_stock_item", "is_fixed_asset", "stock_uom", "asset_category"], (r) => {
				frappe.model.set_value(cdt, cdn, "is_stock_item", r.is_stock_item || 0);
				frappe.model.set_value(cdt, cdn, "is_fixed_asset", r.is_fixed_asset || 0);
				frappe.model.set_value(cdt, cdn, "uom", r.stock_uom || "");
				frappe.model.set_value(cdt, cdn, "asset_category", r.asset_category || "");
			});
		}
	},

	qty(frm, cdt, cdn) {
		calculate_amount(cdt, cdn);
	},

	rate(frm, cdt, cdn) {
		calculate_amount(cdt, cdn);
	},

	custody_items_remove(frm) {
		frm.trigger("update_totals");
	}
});

function calculate_amount(cdt, cdn) {
	const row = locals[cdt][cdn];
	const amount = flt(row.qty) * flt(row.rate);
	frappe.model.set_value(cdt, cdn, "amount", amount);
	// Trigger total recalculation on the parent form
	const frm = frappe.get_form("Accountant Custody");
	if (frm) frm.trigger("update_totals");
}

// Extend the form with a utility trigger
frappe.ui.form.on("Accountant Custody", {
	update_totals(frm) {
		let total = 0;
		(frm.doc.custody_items || []).forEach((item) => {
			total += flt(item.amount);
		});
		frm.set_value("total_amount", total);
	}
});
