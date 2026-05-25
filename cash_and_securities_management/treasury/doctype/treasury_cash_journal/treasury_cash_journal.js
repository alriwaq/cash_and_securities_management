// Treasury Cash Journal — Client Script
// Adds: Arabic field labels, accounting preview section, status-aware UI controls

frappe.ui.form.on("Treasury Cash Journal", {

	// ── Arabic Labels ────────────────────────────────────────────────────────────
	onload: function (frm) {
		const labels = {
			naming_series:       "رقم المسلسل",
			treasury_station:    "محطة الخزينة",
			posting_date:        "تاريخ القيد",
			posting_status:      "الحالة",
			company:             "الشركة",
			opening_balance:     "الرصيد الافتتاحي",
			total_inflows:       "إجمالي الوارد",
			total_outflows:      "إجمالي الصادر",
			expected_balance:    "الرصيد المتوقع",
			actual_balance:      "الرصيد الفعلي (العد)",
			variance:            "الفرق",
			variance_narration:  "بيان الفرق",
			journal_lines:       "سطور القيد",
		};
		Object.entries(labels).forEach(([fn, lbl]) => {
			if (frm.fields_dict[fn]) {
				frm.fields_dict[fn].set_label(lbl);
			}
		});
	},

	// ── Refresh: status-aware buttons + accounting preview ───────────────────────
	refresh: function (frm) {
		frm.trigger("_set_status_indicator");
		frm.trigger("_render_accounting_preview");

		// Only show Submit when Pending Review and not yet submitted
		if (frm.doc.posting_status === "Pending Review" && frm.doc.docstatus === 0) {
			frm.page.set_primary_action(__("تقديم للمحاسبة"), () => frm.savesubmit());
		}

		// Open cockpit link
		if (frm.doc.treasury_station) {
				frm.add_custom_button(__("فتح الكوكبيت"), () => {
					frappe.route_options = {
						station: frm.doc.treasury_station,
						date: frm.doc.posting_date
					};
					frappe.set_route("treasury-cash-journal-cockpit");
				}, __("الإجراءات"));
		}
	},

	// ── Status indicator colour ──────────────────────────────────────────────────
	_set_status_indicator: function (frm) {
		const map = {
			"Draft":          ["grey",   "مسودة"],
			"Pending Review": ["orange", "قيد المراجعة"],
			"Posted":         ["blue",   "مرحّل"],
			"Closed":         ["green",  "مغلق"],
		};
		const [colour, label] = map[frm.doc.posting_status] || ["grey", frm.doc.posting_status];
		frm.page.set_indicator(label, colour);
	},

	// ── Accounting Preview Section ────────────────────────────────────────────────
	_render_accounting_preview: function (frm) {
		// Only show for Pending Review or Posted/Closed
		if (!["Pending Review", "Posted", "Closed"].includes(frm.doc.posting_status)) {
			return;
		}
		if (!frm.doc.name || frm.doc.name === "new-treasury-cash-journal-1") return;

		frappe.call({
			method: "preview_accounting_lines",
			doc: frm.doc,
			callback: (r) => {
				if (!r.message || !r.message.length) return;
				const lines = r.message;

				let rows = lines.map((l) => `
					<tr>
						<td class="text-muted small">${l.idx}</td>
						<td>${l.direction === "Inbound"
							? '<span class="badge badge-success">وارد</span>'
							: '<span class="badge badge-danger">صادر</span>'}</td>
						<td>${l.category || ""}</td>
						<td>${l.party || ""}</td>
						<td>${l.reference || ""}</td>
						<td style="color:#155724;font-weight:600;">${l.debit_account || ""}</td>
						<td style="color:#721c24;font-weight:600;">${l.credit_account || ""}</td>
						<td style="text-align:right;font-weight:700;">${frappe.utils.format_number(l.amount, null, 2)}</td>
						<td class="text-muted small">${l.narration || ""}</td>
					</tr>
				`).join("");

				const html = `
				<div class="tcj-preview-wrapper" style="margin:15px 0;">
					<h6 style="font-weight:700;margin-bottom:8px;color:var(--primary);">
						<i class="fa fa-table mr-1"></i>
						مراجعة القيود المحاسبية — معاينة الحركات قبل الترحيل
					</h6>
					<div class="table-responsive">
					<table class="table table-bordered table-sm" style="font-size:0.82rem;">
						<thead class="thead-light">
							<tr>
								<th>#</th>
								<th>الاتجاه</th>
								<th>النوع</th>
								<th>الطرف</th>
								<th>المرجع</th>
								<th style="color:#155724;">مدين (Dr)</th>
								<th style="color:#721c24;">دائن (Cr)</th>
								<th>المبلغ</th>
								<th>البيان</th>
							</tr>
						</thead>
						<tbody>${rows}</tbody>
					</table>
					</div>
					<p class="text-muted small mt-1">
						<i class="fa fa-info-circle mr-1"></i>
						هذه معاينة فقط. سيتم إنشاء القيود الفعلية عند الضغط على "تقديم للمحاسبة".
					</p>
				</div>`;

				// Inject after the journal_lines field wrapper
				const $wrapper = frm.fields_dict.journal_lines
					? $(frm.fields_dict.journal_lines.wrapper)
					: $(frm.wrapper);
				$wrapper.find(".tcj-preview-wrapper").remove();
				$wrapper.after(html);
			},
		});
	},
});

// ── Child table: Arabic column labels ────────────────────────────────────────
frappe.ui.form.on("Treasury Journal Line", {
	form_render: function (frm, cdt, cdn) {
		// Labels are set via the child doctype JS; handled here for inline grid
	},
});
