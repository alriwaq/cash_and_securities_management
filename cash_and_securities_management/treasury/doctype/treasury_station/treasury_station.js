// Treasury Station — Client Script
// Adds: Transfer Responsibility button, responsible_user auto-fill,
//       vault_account lock after submit, Arabic field labels

frappe.ui.form.on("Treasury Station", {

	// ─── Form Setup ────────────────────────────────────────────────────────────

	setup(frm) {
		// Filter vault_account to Cash/Bank accounts only
		frm.set_query("vault_account", () => ({
			filters: {
				account_type: ["in", ["Cash", "Bank"]],
				is_group: 0,
				company: frm.doc.company,
			},
		}));

		// Filter parent_account to Cash group accounts
		frm.set_query("parent_account", () => ({
			filters: {
				account_type: ["in", ["Cash", "Bank"]],
				is_group: 1,
				company: frm.doc.company,
			},
		}));

		// Filter shortage_account to Expense accounts
		frm.set_query("shortage_account", () => ({
			filters: {
				root_type: "Expense",
				is_group: 0,
				company: frm.doc.company,
			},
		}));
	},

	refresh(frm) {
		// Lock vault_account and company after submit
		if (frm.doc.docstatus === 1) {
			frm.set_df_property("vault_account", "read_only", 1);
			frm.set_df_property("company", "read_only", 1);
			frm.set_df_property("station_name", "read_only", 1);
		}

		// Show Transfer Responsibility button for managers on submitted doc
		if (frm.doc.docstatus === 1 && _isManager()) {
			frm.add_custom_button(__("نقل المسؤولية"), () => {
				_showTransferDialog(frm);
			}, __("الإجراءات"));
		}

		// Show/hide parent_account based on create_vault_account
		frm.toggle_display("parent_account", frm.doc.create_vault_account);
		frm.toggle_display("vault_account", !frm.doc.create_vault_account);

		// Translate field labels to Arabic
		_setArabicLabels(frm);
	},

	// ─── Field Events ──────────────────────────────────────────────────────────

	responsible_employee(frm) {
		if (!frm.doc.responsible_employee) {
			frm.set_value("responsible_user", "");
			return;
		}
		frappe.db.get_value("Employee", frm.doc.responsible_employee, "user_id", (r) => {
			if (r && r.user_id) {
				frm.set_value("responsible_user", r.user_id);
			} else {
				frappe.msgprint({
					title: __("تحذير"),
					message: __("الموظف {0} لا يملك حساب مستخدم مرتبط. يرجى تعيين معرف المستخدم في سجل الموظف أولاً.", [frm.doc.responsible_employee]),
					indicator: "orange",
				});
				frm.set_value("responsible_user", "");
			}
		});
	},

	create_vault_account(frm) {
		frm.toggle_display("parent_account", frm.doc.create_vault_account);
		frm.toggle_display("vault_account", !frm.doc.create_vault_account);
		if (frm.doc.create_vault_account) {
			frm.set_value("vault_account", "");
		}
	},

	is_default(frm) {
		if (frm.doc.is_default) {
			frappe.msgprint({
				title: __("المحطة الافتراضية"),
				message: __("عند الحفظ، سيتم تعيين هذه المحطة كحساب افتراضي لطريقة الدفع النقدي للشركة {0}.", [frm.doc.company]),
				indicator: "blue",
			});
		}
	},
});

// ─── Transfer Responsibility Dialog ──────────────────────────────────────────

function _showTransferDialog(frm) {
	const d = new frappe.ui.Dialog({
		title: __("نقل مسؤولية الخزينة"),
		fields: [
			{
				fieldname: "new_employee",
				fieldtype: "Link",
				options: "Employee",
				label: __("الموظف الجديد المسؤول"),
				reqd: 1,
				get_query: () => ({
					filters: { status: "Active" },
				}),
			},
			{
				fieldname: "handover_notes",
				fieldtype: "Small Text",
				label: __("ملاحظات التسليم"),
			},
		],
		primary_action_label: __("تأكيد النقل"),
		primary_action(values) {
			frappe.call({
				method: "transfer_responsibility",
				doc: frm.doc,
				args: {
					new_employee: values.new_employee,
					handover_notes: values.handover_notes || "",
				},
				callback(r) {
					if (!r.exc) {
						d.hide();
						frm.reload_doc();
					}
				},
			});
		},
	});
	d.show();
}

// ─── Arabic Labels ────────────────────────────────────────────────────────────

function _setArabicLabels(frm) {
	const labels = {
		station_name:        "اسم المحطة",
		company:             "الشركة",
		is_default:          "المحطة الافتراضية للشركة",
		status:              "الحالة",
		handover_date:       "تاريخ الاستلام",
		responsible_employee:"الموظف المسؤول",
		responsible_user:    "المستخدم المسؤول",
		create_vault_account:"إنشاء حساب خزينة جديد",
		parent_account:      "الحساب الأب",
		vault_account:       "حساب الخزينة النقدي",
		shortage_account:    "حساب الفروقات",
		opening_balance:     "الرصيد الافتتاحي",
		current_balance:     "الرصيد الحالي",
		last_closing_date:   "تاريخ آخر إقفال",
		responsibility_log:  "سجل نقل المسؤولية",
	};
	Object.entries(labels).forEach(([field, label]) => {
		frm.set_df_property(field, "label", label);
	});
}

// ─── Role Check ───────────────────────────────────────────────────────────────

function _isManager() {
	const roles = frappe.user_roles || [];
	return (
		roles.includes("System Manager") ||
		roles.includes("Accounts Manager") ||
		frappe.session.user === "Administrator"
	);
}
