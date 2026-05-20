frappe.pages["treasury-cash-journal-cockpit"] = frappe.pages["treasury-cash-journal-cockpit"] || {};

frappe.pages["treasury-cash-journal-cockpit"].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Cash Journal Cockpit",
		single_column: true,
	});

	try {
		// Inject the cockpit HTML directly into the page main section
		$(page.main).html(`
<div class="tcj-page" style="padding: 0 15px;">

  <!-- Header Bar -->
  <div class="tcj-header row align-items-center mb-3 mt-2">
    <div class="col-auto">
      <h4 class="mb-0" style="font-weight:600;">
        <i class="fa fa-university mr-2" style="color:var(--primary);"></i>
        يومية نقدية الخزينة
      </h4>
    </div>
    <div class="col-auto ml-3">
      <select id="tcj-station-select" class="form-control form-control-sm" style="min-width:200px;">
        <option value="">— اختر المحطة —</option>
      </select>
    </div>
    <div class="col-auto">
      <input type="date" id="tcj-date-input" class="form-control form-control-sm" style="min-width:140px;" />
    </div>
    <div class="col-auto">
      <span id="tcj-status-badge" class="badge badge-secondary" style="font-size:0.85rem; padding:6px 12px;">مسودة</span>
    </div>
    <div class="col-auto ml-auto">
      <button id="tcj-add-txn-btn" class="btn btn-sm btn-success mr-2">
				<i class="fa fa-plus mr-1"></i> تسجيل حركة خزينة
      </button>
      <button id="tcj-save-btn" class="btn btn-sm btn-default mr-2">
        <i class="fa fa-save mr-1"></i> حفظ مسودة
      </button>
      <button id="tcj-post-btn" class="btn btn-sm btn-primary">
        <i class="fa fa-paper-plane mr-1"></i> إرسال للمراجعة
      </button>
    </div>
  </div>

  <!-- KPI Cards -->
  <div class="tcj-kpi-row row mb-3" id="tcj-kpi-row">
    <div class="col-md-3 col-sm-6 mb-2">
      <div class="tcj-kpi-card card shadow-sm" style="border-left:4px solid #6c757d;">
        <div class="card-body py-2 px-3">
          <div class="tcj-kpi-label text-muted" style="font-size:0.75rem; text-transform:uppercase; letter-spacing:0.05em;">الرصيد الافتتاحي</div>
          <div class="tcj-kpi-value" id="kpi-opening" style="font-size:1.4rem; font-weight:700; color:#495057;">0.00</div>
        </div>
      </div>
    </div>
    <div class="col-md-3 col-sm-6 mb-2">
      <div class="tcj-kpi-card card shadow-sm" style="border-left:4px solid #28a745;">
        <div class="card-body py-2 px-3">
          <div class="tcj-kpi-label text-muted" style="font-size:0.75rem; text-transform:uppercase; letter-spacing:0.05em;">إجمالي الوارد</div>
          <div class="tcj-kpi-value" id="kpi-inflows" style="font-size:1.4rem; font-weight:700; color:#28a745;">0.00</div>
        </div>
      </div>
    </div>
    <div class="col-md-3 col-sm-6 mb-2">
      <div class="tcj-kpi-card card shadow-sm" style="border-left:4px solid #dc3545;">
        <div class="card-body py-2 px-3">
          <div class="tcj-kpi-label text-muted" style="font-size:0.75rem; text-transform:uppercase; letter-spacing:0.05em;">إجمالي الصادر</div>
          <div class="tcj-kpi-value" id="kpi-outflows" style="font-size:1.4rem; font-weight:700; color:#dc3545;">0.00</div>
        </div>
      </div>
    </div>
    <div class="col-md-3 col-sm-6 mb-2">
      <div class="tcj-kpi-card card shadow-sm" style="border-left:4px solid var(--primary);">
        <div class="card-body py-2 px-3">
          <div class="tcj-kpi-label text-muted" style="font-size:0.75rem; text-transform:uppercase; letter-spacing:0.05em;">الرصيد المتوقع</div>
          <div class="tcj-kpi-value" id="kpi-expected" style="font-size:1.4rem; font-weight:700; color:var(--primary);">0.00</div>
        </div>
      </div>
    </div>
  </div>

  <!-- V4: Pending Items Alert Banner -->
  <div id="tcj-pending-banner" class="alert alert-warning d-flex align-items-center mb-2" style="display:none !important;">
    <i class="fa fa-clock-o mr-2"></i>
    <span>يوجد <strong id="tcj-pending-count">0</strong> حركة نقدية معلقة تنتظر التنفيذ من مصادر خارجية.</span>
    <button type="button" class="btn btn-xs btn-warning ml-auto" id="tcj-scroll-to-pending">عرض الحركات المعلقة &darr;</button>
  </div>

  <!-- Tab Filter Bar -->
  <ul class="nav nav-tabs mb-0" id="tcj-tabs" role="tablist" style="border-bottom:2px solid var(--primary);">
    <li class="nav-item">
      <a class="nav-link active" id="tab-all" data-filter="all" href="#" role="tab">
        الكل <span class="badge badge-secondary ml-1" id="badge-all">0</span>
      </a>
    </li>
    <li class="nav-item">
      <a class="nav-link" id="tab-outbound" data-filter="Outbound" href="#" role="tab">
        <span style="color:#dc3545;">&#8595;</span> صادر
        <span class="badge badge-danger ml-1" id="badge-outbound">0</span>
      </a>
    </li>
    <li class="nav-item">
      <a class="nav-link" id="tab-inbound" data-filter="Inbound" href="#" role="tab">
        <span style="color:#28a745;">&#8593;</span> وارد
        <span class="badge badge-success ml-1" id="badge-inbound">0</span>
      </a>
    </li>
		<li class="nav-item">
      <a class="nav-link" id="tab-bank" data-filter="Bank Transfer" href="#" role="tab">
				<i class="fa fa-exchange"></i> تحويل بنكي
				<span class="badge badge-info ml-1" id="badge-bank">0</span>
			</a>
		</li>
  </ul>

  <!-- Transaction Grid -->
  <div class="tcj-grid-wrapper" style="overflow-x:auto; background:#fff; border:1px solid #dee2e6; border-top:none;">
    <table class="table table-sm table-hover mb-0" id="tcj-grid">
      <thead style="background:var(--subtle-fg); position:sticky; top:0; z-index:10;">
        <tr>
          <th style="width:30px;">#</th>
          <th style="width:110px;">الاتجاه</th>
          <th style="width:150px;">النوع</th>
          <th style="width:120px;">نوع الطرف</th>
          <th style="width:180px;">الطرف</th>
          <th style="width:160px;">المرجع</th>
          <th style="width:120px; text-align:right;">المبلغ</th>
          <th>البيان</th>
          <th style="width:80px; text-align:center;">الحالة</th>
          <th style="width:40px;"></th>
        </tr>
      </thead>
      <tbody id="tcj-tbody">
      </tbody>
    </table>
  </div>

  <!-- Read-only Row Count Indicator -->
  <div class="tcj-toolbar mt-2 mb-3 d-flex align-items-center">
		<span class="text-muted small"><i class="fa fa-info-circle mr-1"></i> <strong>جدول للقراءة فقط:</strong> استخدم "تسجيل حركة خزينة" لإضافة القيود عبر المعالج.</span>
    <span class="text-muted small ml-auto" id="tcj-row-count">0 سطر</span>
  </div>

  <!-- End-of-Day Denomination Drawer -->
  <div class="card mt-3" id="tcj-denomination-card" style="display:none;">
    <div class="card-header d-flex justify-content-between align-items-center"
         style="cursor:pointer; background:var(--subtle-fg);"
         id="tcj-denomination-toggle">
      <span><i class="fa fa-calculator mr-2"></i> جرد الأوراق النقدية - نهاية اليوم</span>
      <i class="fa fa-chevron-down" id="tcj-denom-chevron"></i>
    </div>
    <div class="card-body" id="tcj-denomination-body">
      <div class="row">
        <div class="col-md-6">
          <table class="table table-sm" id="tcj-denom-table">
            <thead>
              <tr>
                <th>الفئة</th>
                <th style="width:100px;">العدد</th>
                <th style="width:120px; text-align:right;">الإجمالي</th>
              </tr>
            </thead>
            <tbody id="tcj-denom-tbody"></tbody>
            <tfoot>
              <tr style="font-weight:700; border-top:2px solid #dee2e6;">
                <td colspan="2">إجمالي العد الفعلي</td>
                <td style="text-align:right;" id="tcj-denom-total">0.00</td>
              </tr>
            </tfoot>
          </table>
        </div>
        <div class="col-md-6">
          <div class="card bg-light p-3">
            <div class="row mb-2">
              <div class="col-6 text-muted">الرصيد المتوقع:</div>
              <div class="col-6 text-right font-weight-bold" id="tcj-denom-expected">0.00</div>
            </div>
            <div class="row mb-2">
              <div class="col-6 text-muted">الرصيد الفعلي (العد):</div>
              <div class="col-6 text-right font-weight-bold" id="tcj-denom-actual">0.00</div>
            </div>
            <div class="row mb-3">
              <div class="col-6 text-muted">الفرق:</div>
              <div class="col-6 text-right font-weight-bold" id="tcj-denom-variance" style="color:#dc3545;">0.00</div>
            </div>
            <div class="form-group mb-2">
              <label class="small text-muted">بيان الفرق (مطلوب إذا كان الفرق ≠ 0)</label>
              <textarea id="tcj-variance-narration" class="form-control form-control-sm" rows="2"
                        placeholder="اذكر سبب العجز أو الزيادة..."></textarea>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- V4: Pending Items Section -->
  <div id="tcj-pending-section" class="card mt-4" style="display:none;">
    <div class="card-header d-flex justify-content-between align-items-center"
         style="background:#fff3cd; border-bottom:1px solid #ffc107; cursor:pointer;"
         id="tcj-pending-toggle">
      <span style="font-weight:600;">
        <i class="fa fa-clock-o mr-2" style="color:#856404;"></i>
        الحركات المعلقة &mdash; بانتظار التنفيذ من الخزينة
        <span class="badge badge-warning ml-2" id="tcj-pending-badge">0</span>
      </span>
      <i class="fa fa-chevron-down" id="tcj-pending-chevron"></i>
    </div>
    <div class="card-body p-0" id="tcj-pending-body">
      <div class="alert alert-info m-3" style="font-size:0.85rem;">
        <i class="fa fa-info-circle mr-1"></i>
        هذه الحركات تم إنشاؤها تلقائياً من مستندات خارجية (سندات دفع، فواتير). قم بتنفيذ كل حركة بعد تسليم النقد فعلياً.
      </div>
      <div class="table-responsive">
        <table class="table table-sm table-hover mb-0" id="tcj-pending-grid">
          <thead style="background:#fff3cd;">
            <tr>
              <th>المستند المصدر</th>
              <th>الاتجاه</th>
              <th>النوع</th>
              <th>الطرف</th>
              <th>المرجع</th>
              <th style="text-align:right;">المبلغ المتوقع</th>
              <th>البيان</th>
              <th style="text-align:center; width:180px;">الإجراء</th>
            </tr>
          </thead>
          <tbody id="tcj-pending-tbody">
            <tr><td colspan="8" class="text-center text-muted py-3">لا توجد حركات معلقة</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- Hidden journal name store -->
  <input type="hidden" id="tcj-journal-name" value="" />
  <input type="hidden" id="tcj-opening-balance" value="0" />

</div>
`);

		// Boot the controller
		new TreasuryCashJournal(page, wrapper);
	} catch (e) {
		console.error("Failed to load Treasury Cash Journal Cockpit", e);
		$(page.main).html(`
			<div class="alert alert-danger" role="alert" style="margin: 15px;">
				<strong>Cash Journal Cockpit failed to load.</strong><br/>
				Please contact your administrator and check browser console logs.
			</div>
		`);
	}
};

// ─────────────────────────────────────────────────────────────────────────────
// TreasuryCashJournal Controller
// ─────────────────────────────────────────────────────────────────────────────
class TreasuryCashJournal {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;
		this.rows = [];
		this.activeFilter = "all";
		this.journalName = null;
		this.journalStatus = "Draft";
		this.openingBalance = 0;
		this.stationData = null;
		this.posted = false;
		// Separate serial counters for inbound and outbound vouchers
		this._inboundSerial = 0;
		this._outboundSerial = 0;

		this._initDatePicker();
		this._loadStations();
		this._bindEvents();
		this._initDenomTable();
	}

	// ── Initialisation ────────────────────────────────────────────────────────

	_initDatePicker() {
		const today = frappe.datetime.get_today();
		$("#tcj-date-input").val(today);
	}

	_loadStations() {
		frappe.call({
			method: "cash_and_securities_management.treasury.page.treasury_cash_journal_cockpit.treasury_cash_journal_cockpit_api.get_station_list",
			callback: (r) => {
				const stations = (r && r.message) ? r.message : [];

				if (stations.length === 0) {
					// No station assigned to this user — show locked state
					$("#tcj-station-select").prop("disabled", true);
					$("#tcj-date-input").prop("disabled", true);
					$("#tcj-add-txn-btn, #tcj-save-btn, #tcj-post-btn").prop("disabled", true);
					// Show Arabic access-denied message
					const $main = $("#tcj-main-area");
					$main.prepend(`
						<div class="alert alert-warning text-center" style="font-size:1.1rem;margin-bottom:16px;">
							<i class="fa fa-lock" style="margin-left:6px;"></i>
							<strong>لا يوجد لديك صلاحية لأي محطة خزينة مفتوحة.</strong><br>
							<small>يرجى التواصل مع مدير الحسابات لتعيين مسؤولية خزينة لحسابك.</small>
						</div>
					`);
					return;
				}

				const sel = $("#tcj-station-select");
				stations.forEach((s) => {
					const label = s.responsible_employee
						? `${s.station_name} — ${s.responsible_employee}`
						: s.station_name;
					sel.append(`<option value="${s.name}">${label}</option>`);
				});
				if (stations.length === 1) {
					sel.val(stations[0].name);
					this._loadJournal();
					this._loadPendingItems();
				}
			},
		});
	}

	_bindEvents() {
		$("#tcj-station-select").on("change", () => { this._loadJournal(); this._loadPendingItems(); });
		$("#tcj-date-input").on("change", () => { this._loadJournal(); this._loadPendingItems(); });

		$("#tcj-tabs .nav-link").on("click", (e) => {
			e.preventDefault();
			$("#tcj-tabs .nav-link").removeClass("active");
			$(e.currentTarget).addClass("active");
			this.activeFilter = $(e.currentTarget).data("filter");
			this._renderGrid();
		});

		// New: "Add Transaction" button triggers wizard
		$("#tcj-add-txn-btn").on("click", () => this._showAddTransactionWizard());

		$("#tcj-save-btn").on("click", () => this._saveDraft());
		$("#tcj-post-btn").on("click", () => this._confirmPost());

		$("#tcj-denomination-toggle").on("click", () => {
			const body = $("#tcj-denomination-body");
			const chevron = $("#tcj-denom-chevron");
			body.slideToggle(200);
			chevron.toggleClass("fa-chevron-down fa-chevron-up");
		});

		// V4: Pending items panel toggle
		$("#tcj-pending-toggle").on("click", () => {
			$("#tcj-pending-body").slideToggle(200);
			$("#tcj-pending-chevron").toggleClass("fa-chevron-down fa-chevron-up");
		});

		// V4: Scroll-to-pending button in alert banner (no href routing)
		$(document).on("click", "#tcj-scroll-to-pending", (e) => {
			e.preventDefault();
			const $section = $("#tcj-pending-section");
			$section.show();
			$("#tcj-pending-body").slideDown(200);
			$("#tcj-pending-chevron").removeClass("fa-chevron-up").addClass("fa-chevron-down");
			const el = $section[0];
			if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
		});
	}

	_initDenomTable() {
		const denoms = [500, 200, 100, 50, 20, 10, 5, 2, 1, 0.5, 0.25];
		const tbody = $("#tcj-denom-tbody");
		tbody.empty();
		denoms.forEach((d) => {
			tbody.append(`
				<tr data-denom="${d}">
					<td>${d}</td>
					<td><input type="number" class="form-control form-control-sm denom-count"
					           min="0" value="0" data-denom="${d}" style="width:80px;" /></td>
					<td class="text-right denom-line-total">0.00</td>
				</tr>
			`);
		});
		$(document).on("input", ".denom-count", () => this._calcDenomTotal());
	}

	_calcDenomTotal() {
		let total = 0;
		$(".denom-count").each(function () {
			const count = parseFloat($(this).val()) || 0;
			const denom = parseFloat($(this).data("denom"));
			const lineTotal = count * denom;
			$(this).closest("tr").find(".denom-line-total").text(
				frappe.utils.format_number(lineTotal, null, 2)
			);
			total += lineTotal;
		});
		const expected = this.openingBalance + this._sumInflows() - this._sumOutflows();
		const variance = total - expected;

		$("#tcj-denom-total").text(frappe.utils.format_number(total, null, 2));
		$("#tcj-denom-expected").text(frappe.utils.format_number(expected, null, 2));
		$("#tcj-denom-actual").text(frappe.utils.format_number(total, null, 2));
		$("#tcj-denom-variance")
			.text(frappe.utils.format_number(variance, null, 2))
			.css("color", variance < 0 ? "#dc3545" : variance > 0 ? "#fd7e14" : "#28a745");
	}

	_loadJournal() {
		const station = $("#tcj-station-select").val();
		const date = $("#tcj-date-input").val();
		if (!station || !date) return;

		frappe.call({
			method: "cash_and_securities_management.treasury.page.treasury_cash_journal_cockpit.treasury_cash_journal_cockpit_api.get_station_data",
			args: { station, posting_date: date },
			callback: (r) => {
				if (!r.message) return;
				const data = r.message;
				this.stationData = data.station;
				this.openingBalance = data.opening_balance || 0;
				this.journalName = data.journal_name || null;
				this.journalStatus = (data.existing && data.existing.posting_status) || "Draft";
				this.posted = this.journalStatus === "Posted" || this.journalStatus === "Closed";

				this.rows = (data.lines || []).map((l, i) => ({
					_id: i,
					voucher_serial: l.voucher_serial || "",
					direction: l.direction || "",
					transaction_category: l.transaction_category || "",
					party_type: l.party_type || "",
					party: l.party || "",
					reference_doctype: l.reference_doctype || "",
					reference_name: l.reference_name || "",
					expense_account: l.expense_account || "",
					amount: l.amount || 0,
					narration: l.narration || "",
					is_posted: l.is_posted || 0,
					linked_document: l.linked_document || "",
					linked_doctype: l.linked_doctype || "",
				}));
				// Restore serial counters from loaded rows
				this._inboundSerial = this.rows.filter(r => r.direction === "Inbound").length;
				this._outboundSerial = this.rows.filter(r => r.direction === "Outbound").length;

				this._updateKPIs();
				this._renderGrid();
				this._updateStatusBadge();
				this._updateDenomCard();
				$("#tcj-opening-balance").val(this.openingBalance);
				$("#tcj-journal-name").val(this.journalName || "");
			},
		});
	}

	_addRow() {
		if (this.posted) {
			frappe.msgprint(__("This journal is already posted. No new rows can be added."));
			return;
		}
		this._showAddTransactionWizard();
	}

	_deleteRow(id) {
		this.rows = this.rows.filter((r) => r._id !== id);
		this._updateKPIs();
		this._renderGrid();
	}

	// ── Grid Render ───────────────────────────────────────────────────────────

	_renderGrid() {
		const tbody = $("#tcj-tbody");
		tbody.empty();

		const filtered = this.activeFilter === "all"
			? this.rows
			: this.rows.filter((r) => r.direction === this.activeFilter);

		if (filtered.length === 0) {
			tbody.append(`
				<tr>
					<td colspan="10" class="text-center text-muted py-4">
						<i class="fa fa-inbox fa-2x mb-2 d-block"></i>
						No rows yet. Click <strong>Record Vault Movement</strong> to begin.
					</td>
				</tr>
			`);
		} else {
			filtered.forEach((row, idx) => {
				tbody.append(this._renderRow(row, idx + 1));
			});
		}

		this._bindGridEvents();
		this._updateBadgeCounts();
		this._updateRowCount();
	}

	_renderRow(row, idx) {
		const posted = row.is_posted;
		const rowClass = posted
			? "table-success"
			: (row.direction === "Inbound"
				? "tcj-row-inbound"
				: row.direction === "Outbound"
					? "tcj-row-outbound"
					: "");

		const linkedRoute = row.linked_doctype
			? row.linked_doctype.toLowerCase().replace(/\s+/g, "-")
			: "payment-entry";

		const statusCell = posted
			? `<span class="badge badge-success"><i class="fa fa-check"></i> Posted</span>
			   ${row.linked_document ? `<a href="/app/${linkedRoute}/${row.linked_document}" target="_blank"
			      class="small ml-1" title="Open ${row.linked_document}">
			      <i class="fa fa-external-link"></i>
			   </a>` : ""}`
			: `<span class="badge badge-secondary">Draft</span>`;

		const deleteBtn = !posted
			? `<button class="btn btn-xs btn-danger tcj-delete-row" data-id="${row._id}" title="Delete row">
			     <i class="fa fa-trash"></i>
			   </button>`
			: "";

		return `
			<tr id="row-${row._id}" class="${rowClass}" data-id="${row._id}">
				<td class="text-muted small">${idx}</td>
				<td><span class="badge badge-light">${row.direction || "—"}</span></td>
				<td><span>${row.transaction_category || "—"}</span></td>
				<td><span>${row.party_type || "—"}</span></td>
				<td><span>${this._escapeHtml(row.party || "—")}</span></td>
				<td><span>${this._escapeHtml(row.reference_name || "—")}</span></td>
				<td style="text-align:right;"><strong>${frappe.utils.format_number(row.amount || 0, null, 2)}</strong></td>
				<td><span>${this._escapeHtml(row.narration || "—")}</span></td>
				<td class="text-center">${statusCell}</td>
				<td>${deleteBtn}</td>
			</tr>
		`;
	}

	_bindGridEvents() {
		const tbody = $("#tcj-tbody");
		tbody.off("click.tcj");
		
		// Only delete button event needed for read-only table
		tbody.on("click.tcj", ".tcj-delete-row", (e) => {
			const id = parseInt($(e.target).closest("button").data("id"));
			this._deleteRow(id);
		});
	}

	_inferRefDoctype(row) {
		if (row.direction === "Inbound" && row.transaction_category === "Invoice Collection") {
			return "Sales Invoice";
		}
		if (row.direction === "Outbound" && row.transaction_category === "Supplier Payment") {
			return "Purchase Invoice";
		}
		if (row.direction === "Outbound" && row.transaction_category === "Custody Advance") {
			return "Custody Request";
		}
		if (row.direction === "Inbound" && row.transaction_category === "Custody Return") {
			return "Custody Request";
		}
		if (row.direction === "Bank Transfer" && ["Bank Withdrawal", "Bank Deposit"].includes(row.transaction_category)) {
			return "Account";
		}
		if (["Custody Settlement", "Advance Allocation"].includes(row.transaction_category)) {
			return "Accountant Custody";
		}
		if (row.transaction_category === "Direct Expense") {
			return "Account";
		}
		return "";
	}

	// ── Multi-Step Wizard Dialog (V4: Two-Path) ──────────────────────────────

	_showAddTransactionWizard() {
		if (this.posted) {
			frappe.msgprint(__("This journal is already posted. No new rows can be added."));
			return;
		}
		// Show path-selector first, then open the appropriate wizard
		this._showPathSelector();
	}

	_showPathSelector() {
		const d = new frappe.ui.Dialog({
			title: "تسجيل حركة خزينة — اختر النوع",
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "path_selector_html",
					options: `
						<div style="display:flex; gap:16px; justify-content:center; padding:16px 0;">
							<button id="path-inbound" class="btn btn-lg" style="flex:1; padding:24px 16px; border:2px solid #28a745; border-radius:10px; background:#f6fff8; cursor:pointer;">
								<div style="font-size:2rem;">📥</div>
								<div style="font-weight:700; font-size:1rem; color:#155724; margin-top:8px;">استلام نقدي</div>
								<div style="font-size:0.78rem; color:#6c757d; margin-top:4px;">تسجيل مبلغ وارد للخزينة</div>
							</button>
							<button id="path-expense" class="btn btn-lg" style="flex:1; padding:24px 16px; border:2px solid #dc3545; border-radius:10px; background:#fff8f8; cursor:pointer;">
								<div style="font-size:2rem;">💸</div>
								<div style="font-weight:700; font-size:1rem; color:#721c24; margin-top:8px;">مصروف مباشر</div>
								<div style="font-size:0.78rem; color:#6c757d; margin-top:4px;">صرف مبلغ من الخزينة مباشرةً</div>
							</button>
						</div>
					`,
				},
			],
		});
		d.show();
		// Bind path buttons after dialog renders
		setTimeout(() => {
			d.$wrapper.find("#path-inbound").on("click", () => {
				d.hide();
				this._showInboundWizard();
			});
			d.$wrapper.find("#path-expense").on("click", () => {
				d.hide();
				this._showDirectExpenseWizard();
			});
		}, 200);
	}

	// ── Path A: Inbound Cash Receipt ──────────────────────────────────────────

	_showInboundWizard() {
		// Static fallback map for common party types
		const inboundRefMap = {
			"Customer":  { doctype: "Sales Invoice",    party_field: "customer" },
			"Supplier":  { doctype: "Purchase Invoice",  party_field: "supplier" },
			"Employee":  { doctype: "Expense Claim",     party_field: "employee" },
			"Student":   { doctype: "Fees",              party_field: "student" },
		};
		// Resolve ref meta from Party Type doc (account_type field) or static map
		const getRefMeta = (ptype, cb) => {
			if (!ptype) { cb({ doctype: "", party_field: "" }); return; }
			if (inboundRefMap[ptype]) { cb(inboundRefMap[ptype]); return; }
			// Fetch from Party Type doctype (has field: account_type)
			frappe.db.get_value("Party Type", ptype, ["account_type"], (r) => {
				cb({ doctype: "", party_field: "" }); // generic — no reference doc
			});
		};

		const dialog = new frappe.ui.Dialog({
			title: "📥 استلام نقدي",
			fields: [
				{
					fieldtype: "Section Break",
					label: "بيانات الاستلام",
				},
				{
					fieldtype: "Link",
					fieldname: "party_type",
					label: "نوع الطرف",
					options: "Party Type",
					default: "Customer",
					reqd: 0,
				},
				{
					fieldtype: "Dynamic Link",
					fieldname: "party",
					label: "الطرف (اختياري)",
					options: "party_type",
				},
				{
					fieldtype: "Link",
					fieldname: "reference_name",
					label: "مستند مرجعي (اختياري)",
					options: "Sales Invoice",   // updated dynamically
				},
				{
					fieldtype: "Column Break",
				},
				{
					fieldtype: "Currency",
					fieldname: "amount",
					label: "المبلغ المستلم",
					reqd: 1,
				},
				{
					fieldtype: "Small Text",
					fieldname: "narration",
					label: "البيان",
					reqd: 1,
				},
			],
			primary_action_label: "تأكيد الاستلام",
			primary_action: (vals) => {
				if ((parseFloat(vals.amount) || 0) <= 0) {
					frappe.msgprint("المبلغ يجب أن يكون أكبر من صفر."); return;
				}
				if (!(vals.narration || "").trim()) {
					frappe.msgprint("البيان إلزامي."); return;
				}
				const ptype = vals.party_type || "";
				const refMeta = inboundRefMap[ptype] || { doctype: "", party_field: "" };
				dialog.hide();
				this._commitImmediateVPI({
					direction: "Inbound",
					transaction_category: "Invoice Collection",
					party_type: ptype !== "Other" ? ptype : "",
					party: vals.party || "",
					reference_doctype: vals.reference_name ? (refMeta.doctype || "") : "",
					reference_name: vals.reference_name || "",
					expense_account: "",
					amount: parseFloat(vals.amount),
					narration: vals.narration,
				});
			},
			secondary_action_label: "معاينة وطباعة",
			secondary_action: () => {
				const vals = dialog.get_values(true);
				const year = new Date().getFullYear();
				const previewSerial = `IN-${year}-${String(this._inboundSerial + 1).padStart(4, "0")}`;
				const station = this.stationData ? (this.stationData.station_name || this.stationData.name) : "";
				this._printVoucher({
					serial: previewSerial,
					station,
					date: $("#tcj-date-input").val(),
					direction: "Inbound",
					transaction_category: "Invoice Collection",
					party: (vals.party_type !== "Other" ? vals.party_type + ": " : "") + (vals.party || ""),
					reference_name: vals.reference_name || "",
					amount: parseFloat(vals.amount) || 0,
					narration: vals.narration || "",
				});
			},
		});

		// When party_type changes: update reference_name doctype and clear party/reference
		dialog.fields_dict.party_type.df.onchange = () => {
			const ptype = dialog.get_value("party_type");
			getRefMeta(ptype, (refMeta) => {
				const refField = dialog.get_field("reference_name");
				refField.df.options = refMeta.doctype || "";
				refField.df.hidden = !refMeta.doctype;
				refField.refresh();
				dialog.set_value("party", "");
				dialog.set_value("reference_name", "");
				dialog.set_value("amount", 0);
			});
		};

		// When party changes: filter reference_name to that party's open documents
		dialog.fields_dict.party.df.onchange = () => {
			const ptype = dialog.get_value("party_type");
			const party = dialog.get_value("party");
			getRefMeta(ptype, (refMeta) => {
				if (!refMeta.doctype || !party) return;
				const refField = dialog.get_field("reference_name");
				refField.df.get_query = () => ({
					filters: {
						docstatus: 1,
						outstanding_amount: [">", 0],
						...(refMeta.party_field ? { [refMeta.party_field]: party } : {}),
					},
				});
				refField.refresh();
				dialog.set_value("reference_name", "");
				dialog.set_value("amount", 0);
			});
		};

		// When reference_name is selected: auto-fill amount from outstanding_amount
		dialog.fields_dict.reference_name.df.onchange = () => {
			const ref = dialog.get_value("reference_name");
			if (!ref) return;
			const ptype = dialog.get_value("party_type");
			getRefMeta(ptype, (refMeta) => {
				const doctype = refMeta.doctype || "Sales Invoice";
				frappe.db.get_value(doctype, ref, ["outstanding_amount", "grand_total"], (r) => {
					if (r) {
						const amt = parseFloat(r.outstanding_amount) || parseFloat(r.grand_total) || 0;
						if (amt > 0) dialog.set_value("amount", amt);
					}
				});
			});
		};

		dialog.show();
	}

	// ── Path C: Direct Expense ─────────────────────────────────────────────────

	_showDirectExpenseWizard() {
		const dialog = new frappe.ui.Dialog({
			title: "💸 مصروف مباشر",
			fields: [
				{
					fieldtype: "Section Break",
					label: "بيانات الصرف",
				},
				{
					fieldtype: "Link",
					fieldname: "expense_account",
					label: "حساب المصروف",
					options: "Account",
					reqd: 1,
					get_query: () => ({ filters: { root_type: "Expense", is_group: 0 } }),
				},
				{
					fieldtype: "Data",
					fieldname: "beneficiary",
					label: "المستفيد",
				},
				{
					fieldtype: "Column Break",
				},
				{
					fieldtype: "Currency",
					fieldname: "amount",
					label: "المبلغ المصروف",
					reqd: 1,
				},
				{
					fieldtype: "Small Text",
					fieldname: "narration",
					label: "البيان",
					reqd: 1,
				},
			],
			primary_action_label: "تأكيد الصرف",
			primary_action: (vals) => {
				if (!vals.expense_account) {
					frappe.msgprint("يرجى تحديد حساب المصروف."); return;
				}
				if ((parseFloat(vals.amount) || 0) <= 0) {
					frappe.msgprint("المبلغ يجب أن يكون أكبر من صفر."); return;
				}
				if (!(vals.narration || "").trim()) {
					frappe.msgprint("البيان إلزامي."); return;
				}
				dialog.hide();
				const narration = vals.beneficiary
					? `${vals.narration} — ${vals.beneficiary}`
					: vals.narration;
				this._commitImmediateVPI({
					direction: "Outbound",
					transaction_category: "Direct Expense",
					party_type: "",
					party: vals.beneficiary || "",
					reference_doctype: "Account",
					reference_name: vals.expense_account,
					expense_account: vals.expense_account,
					amount: parseFloat(vals.amount),
					narration,
				});
			},
			secondary_action_label: "معاينة وطباعة",
			secondary_action: () => {
				const vals = dialog.get_values(true);
				const year = new Date().getFullYear();
				const previewSerial = `OUT-${year}-${String(this._outboundSerial + 1).padStart(4, "0")}`;
				const station = this.stationData ? (this.stationData.station_name || this.stationData.name) : "";
				this._printVoucher({
					serial: previewSerial,
					station,
					date: $("#tcj-date-input").val(),
					direction: "Outbound",
					transaction_category: "مصروف مباشر / Direct Expense",
					party: vals.beneficiary || "",
					reference_name: vals.expense_account || "",
					amount: parseFloat(vals.amount) || 0,
					narration: vals.narration || "",
				});
			},
		});
		dialog.show();
	}

	// ── Immediate VPI Commit (Paths A & C) ────────────────────────────────────
	// Creates a VPI, immediately marks it Executed, assigns serial, adds to TCJ.

	_commitImmediateVPI(data) {
		const station = $("#tcj-station-select").val();
		const date = $("#tcj-date-input").val();
		if (!station || !date) {
			frappe.msgprint("يرجى تحديد المحطة والتاريخ أولاً.");
			return;
		}

		frappe.call({
			method: "cash_and_securities_management.treasury.page.treasury_cash_journal_cockpit.treasury_cash_journal_cockpit_api.create_and_execute_immediate",
			args: {
				station,
				posting_date: date,
				direction: data.direction,
				transaction_category: data.transaction_category,
				party_type: data.party_type || "",
				party: data.party || "",
				reference_doctype: data.reference_doctype || "",
				reference_name: data.reference_name || "",
				expense_account: data.expense_account || "",
				amount: data.amount,
				narration: data.narration,
			},
			freeze: true,
			freeze_message: "جاري تسجيل الحركة...",
			callback: (r) => {
				if (!r.message) return;
				const res = r.message;
				// Print the final voucher with the confirmed serial
				const station_name = this.stationData
					? (this.stationData.station_name || this.stationData.name)
					: "";
				this._printVoucher({
					serial: res.serial,
					station: station_name,
					date,
					direction: data.direction,
					transaction_category: data.transaction_category,
					party: data.party || "",
					reference_name: data.reference_name || data.expense_account || "",
					amount: res.actual_amount || data.amount,
					narration: data.narration,
				});
				frappe.show_alert({ message: `تم تسجيل الحركة ${res.serial} وإضافتها لليومية`, indicator: "green" });
				// Update serial counters
				if (data.direction === "Inbound") this._inboundSerial++;
				else this._outboundSerial++;
				// Reload journal grid
				this._loadJournal();
			},
		});
	}

	_showAddTransactionWizardLegacy() {
		if (this.posted) {
			frappe.msgprint(__("This journal is already posted. No new rows can be added."));
			return;
		}

		const categoryConfig = {
			"Invoice Collection": { party_type: "Customer", reference_doctype: "Sales Invoice", is_direct_expense: false, is_bank_transfer: false },
			"Custody Return": { party_type: "Custodian", reference_doctype: "Custody Request", is_direct_expense: false, is_bank_transfer: false },
			"Supplier Payment": { party_type: "Supplier", reference_doctype: "Purchase Invoice", is_direct_expense: false, is_bank_transfer: false },
			"Custody Advance": { party_type: "Custodian", reference_doctype: "Custody Request", is_direct_expense: false, is_bank_transfer: false },
			"Custody Settlement": { party_type: "Custodian", reference_doctype: "Accountant Custody", is_direct_expense: false, is_bank_transfer: false },
			"Direct Expense": { party_type: "", reference_doctype: "", is_direct_expense: true, is_bank_transfer: false },
			"Bank Withdrawal": { party_type: "Bank Account", reference_doctype: "", is_direct_expense: false, is_bank_transfer: true },
			"Bank Deposit": { party_type: "Bank Account", reference_doctype: "", is_direct_expense: false, is_bank_transfer: true },
		};

		const wizardFields = [
			// ─ Step 1: Classification ─
			{
				fieldtype: "Section Break",
				fieldname: "step1_section",
				label: "الخطوة 1: تصنيف المعاملة",
				hidden: 0,
			},
			{
				fieldtype: "Select",
				fieldname: "direction",
				label: "اتجاه الحركة",
				options: ["", "Inbound", "Outbound", "Bank Transfer"],
				hidden: 0,
			},
			{
				fieldtype: "Select",
				fieldname: "transaction_category",
				label: "نوع المعاملة",
				options: [],
				hidden: 1,
			},

			// ─ Step 2: Linking & Cascading Filters ─
			{
				fieldtype: "Section Break",
				fieldname: "step2_section",
				label: "الخطوة 2: الطرف والمرجع",
				hidden: 1,
			},
			{
				fieldtype: "Link",
				fieldname: "party_type",
				label: "نوع الطرف",
				options: "Party Type",
				hidden: 1,
				read_only: 1,
			},
			{
				fieldtype: "Link",
				fieldname: "party",
				label: "الطرف",
				options: "Customer",
				hidden: 1,
			},
			{
				fieldtype: "Data",
				fieldname: "reference_doctype",
				label: "نوع المرجع",
				hidden: 1,
				read_only: 1,
			},
			{
				fieldtype: "Link",
				fieldname: "reference_name",
				label: "رقم المرجع",
				options: "Sales Invoice",
				hidden: 1,
			},
			{
				fieldtype: "Link",
				fieldname: "expense_account",
				label: "حساب المصروف",
				options: "Account",
				hidden: 1,
			},
			{
				fieldtype: "Link",
				fieldname: "bank_account",
				label: "حساب بنكي",
				options: "Account",
				hidden: 1,
			},

			// ─ Step 3: Financial Automation & Validation ─
			{
				fieldtype: "Section Break",
				fieldname: "step3_section",
				label: "الخطوة 3: المبلغ والبيان",
				hidden: 1,
			},
			{
				fieldtype: "Currency",
				fieldname: "amount",
				label: "المبلغ",
				read_only: 0,
				hidden: 1,
			},
			{
				fieldtype: "Small Text",
				fieldname: "narration",
				label: "البيان / الوصف",
				hidden: 1,
			},
		];

		const dialog = new frappe.ui.Dialog({
			title: "تسجيل حركة خزينة",
			fields: wizardFields,
			primary_action_label: "تأكيد وإضافة",
			primary_action: () => this._onWizardSubmit(dialog),
			secondary_action_label: "طباعة سند الحركة",
			secondary_action: () => this._printVoucherFromDialog(dialog),
		});

		dialog.get_field("expense_account").df.get_query = () => ({
			filters: {
				root_type: "Expense",
				is_group: 0,
			},
		});

		dialog.get_field("bank_account").df.get_query = () => ({
			filters: {
				account_type: "Bank",
				is_group: 0,
			},
		});

		const hideStep3 = () => {
			dialog.set_df_property("step3_section", "hidden", 1);
			dialog.set_df_property("amount", "hidden", 1);
			dialog.set_df_property("narration", "hidden", 1);
			dialog.get_field("step3_section").refresh();
			dialog.get_field("amount").refresh();
			dialog.get_field("narration").refresh();
		};

		const hideStep2Details = () => {
			dialog.set_df_property("party_type", "hidden", 1);
			dialog.set_df_property("party", "hidden", 1);
			dialog.set_df_property("reference_name", "hidden", 1);
			dialog.set_df_property("expense_account", "hidden", 1);
			dialog.set_df_property("bank_account", "hidden", 1);
			dialog.set_df_property("party", "reqd", 0);
			dialog.set_df_property("reference_name", "reqd", 0);
			dialog.set_df_property("expense_account", "reqd", 0);
			dialog.set_df_property("bank_account", "reqd", 0);
			dialog.get_field("party_type").refresh();
			dialog.get_field("party").refresh();
			dialog.get_field("reference_name").refresh();
			dialog.get_field("expense_account").refresh();
			dialog.get_field("bank_account").refresh();
		};

		const showStep3 = (amountReadOnly) => {
			dialog.set_df_property("step3_section", "hidden", 0);
			dialog.set_df_property("amount", "hidden", 0);
			dialog.set_df_property("narration", "hidden", 0);
			dialog.set_df_property("amount", "read_only", amountReadOnly ? 1 : 0);
			dialog.get_field("step3_section").refresh();
			dialog.get_field("amount").refresh();
			dialog.get_field("narration").refresh();
		};

		const updateConfirmState = () => {
			// Use get_value() per-field to avoid triggering Frappe mandatory UI errors on every change
			const direction = dialog.get_value("direction");
			const category = dialog.get_value("transaction_category");
			const cfg = categoryConfig[category] || null;
			const isDirectExpense = !!(cfg && cfg.is_direct_expense);
			const isBankTransfer = !!(cfg && cfg.is_bank_transfer);

			const amount = parseFloat(dialog.get_value("amount")) || 0;
			const narration = (dialog.get_value("narration") || "").trim();
			const hasBase = !!direction && !!category;
			let hasLinks = false;
			if (isDirectExpense) {
				hasLinks = !!dialog.get_value("expense_account");
			} else if (isBankTransfer) {
				hasLinks = !!dialog.get_value("bank_account");
			} else {
				hasLinks = !!dialog.get_value("party_type") && !!dialog.get_value("party") && !!dialog.get_value("reference_name");
			}
			const canConfirm = hasBase && hasLinks && amount > 0 && narration.length > 0;

			dialog.get_primary_btn().prop("disabled", !canConfirm);
			// Also enable/disable the print button based on whether we have enough info
			if (dialog.get_secondary_btn) {
				dialog.get_secondary_btn().prop("disabled", !(hasBase && amount > 0));
			}
		};
		// Delayed confirm state re-check after Frappe Link field internal async resolution
		const deferredConfirmState = () => setTimeout(updateConfirmState, 350);

		const setReferenceQuery = (refDoctype, party, category) => {
			dialog.get_field("reference_name").df.get_query = () => {
				const filters = { docstatus: 1 };
				const partyField = this._getPartyFieldName(refDoctype);
				if (party && partyField) {
					filters[partyField] = party;
				}

				if (refDoctype === "Sales Invoice" || refDoctype === "Purchase Invoice") {
					// Only show invoices that still have an outstanding balance.
					// outstanding_amount is a stored numeric field in ERPNext;
					// a value > 0 means the invoice is not fully settled.
					filters.outstanding_amount = [">", 0];
				} else if (refDoctype === "Custody Request") {
					if (category === "Custody Advance") {
						filters.remaining_to_pay = [">", 0];
						filters.status = ["in", ["Approved", "Pending Payment", "Partly Paid"]];
					} else {
						filters.unallocated_amount = [">", 0];
						filters.status = ["in", ["Paid", "Partly Claimed", "Partly Paid"]];
					}
				} else if (refDoctype === "Accountant Custody") {
					filters.status = ["in", ["Fully Received", "Partly Invoiced"]];
				}

				return { filters };
			};
			dialog.get_field("reference_name").refresh();
		};

		// ─ Event Handlers for Dynamic Field Updates ─

		// When Direction changes, update Category options and visibility
		dialog.fields_dict.direction.df.onchange = () => {
			const direction = dialog.get_value("direction");
			let catOptions = [];

			if (direction === "Inbound") {
				catOptions = ["", "Invoice Collection", "Custody Return"];
			} else if (direction === "Outbound") {
				catOptions = ["", "Supplier Payment", "Custody Advance", "Custody Settlement", "Direct Expense"];
			} else if (direction === "Bank Transfer") {
				catOptions = ["", "Bank Withdrawal", "Bank Deposit"];
			}

			dialog.set_df_property("transaction_category", "options", catOptions);
			dialog.set_df_property("transaction_category", "hidden", direction ? 0 : 1);
			dialog.get_field("transaction_category").refresh();

			// Reset category and subsequent fields
			dialog.set_value("transaction_category", "");
			dialog.set_value("party_type", "");
			dialog.set_value("party", "");
			dialog.set_value("reference_doctype", "");
			dialog.set_value("reference_name", "");
			dialog.set_value("expense_account", "");
			dialog.set_value("bank_account", "");
			dialog.set_value("amount", 0);
			dialog.set_value("narration", "");
			hideStep2Details();
			hideStep3();
			updateConfirmState();
		};

		// When Category changes, show Step 2 section
		dialog.fields_dict.transaction_category.df.onchange = () => {
			const category = dialog.get_value("transaction_category");
			const hasCategory = !!category;
			const cfg = categoryConfig[category] || null;
			const isDirectExpense = !!(cfg && cfg.is_direct_expense);
			const isBankTransfer = !!(cfg && cfg.is_bank_transfer);

			dialog.set_df_property("step2_section", "hidden", hasCategory ? 0 : 1);
			hideStep2Details();
			dialog.get_field("step2_section").refresh();

			dialog.set_value("party_type", cfg ? cfg.party_type : "");
			dialog.set_value("reference_doctype", cfg ? cfg.reference_doctype : "");

			if (hasCategory && cfg) {
				if (isDirectExpense) {
					// Direct Expense: show expense account, Step 3 will show after account selected
					dialog.set_df_property("expense_account", "hidden", 0);
					dialog.get_field("expense_account").refresh();
					hideStep3(); // Hide until account is selected
				} else if (isBankTransfer) {
					// Bank Transfer: select bank from Account list only, then show Step 3
					dialog.set_df_property("bank_account", "hidden", 0);
					dialog.get_field("bank_account").refresh();
					hideStep3(); // Hide until bank account is selected
				} else {
					// Standard categories: show party field and reference_name, Step 3 will show after reference_name selected
					dialog.set_df_property("party", "hidden", 0);
					dialog.set_df_property("reference_name", "hidden", 0);
					dialog.set_df_property("party", "options", cfg.party_type || "Customer");
					dialog.set_df_property("reference_name", "options", cfg.reference_doctype || "Sales Invoice");
					dialog.get_field("party").refresh();
					setReferenceQuery(cfg.reference_doctype || "Sales Invoice", dialog.get_value("party"), category);
					hideStep3(); // Hide until reference_name is selected
				}
			}

			// Reset subsequent fields
			dialog.set_value("party", "");
			dialog.set_value("reference_name", "");
			dialog.set_value("expense_account", "");
			dialog.set_value("bank_account", "");
			dialog.set_value("amount", 0);
			dialog.set_value("narration", "");
			updateConfirmState();
		};

		dialog.fields_dict.party.df.onchange = () => {
			const refDoctype = dialog.get_value("reference_doctype");
			const party = dialog.get_value("party");
			const category = dialog.get_value("transaction_category");
			dialog.set_value("reference_name", "");
			dialog.set_value("amount", 0);
			dialog.set_value("narration", "");
			hideStep3();

			if (!party || !refDoctype) {
				setReferenceQuery(refDoctype, party, category);
				updateConfirmState();
				return;
			}

			setReferenceQuery(refDoctype, party, category);
			updateConfirmState();
			deferredConfirmState();
		};

		dialog.fields_dict.bank_account.df.onchange = () => {
			if (dialog.get_value("bank_account")) {
				showStep3(false);
				dialog.get_field("narration").focus();
			} else {
				dialog.set_value("amount", 0);
				hideStep3();
			}
			updateConfirmState();
		};

			// When Reference Name is selected, auto-fill Amount
			dialog.fields_dict.reference_name.df.onchange = () => {
				const refName = dialog.get_value("reference_name");
				const refDoctype = dialog.get_value("reference_doctype");
				const category = dialog.get_value("transaction_category");
				if (refName && refDoctype) {
					// Always open Step 3 on valid reference selection.
					showStep3(false);

					// Map category/doctype → ordered list of fields to try for the amount.
					// frappe.db.get_value callback receives the dict directly (not r.message).
					const amountFieldsByKey = {
						"Sales Invoice":       ["outstanding_amount", "grand_total"],
						"Purchase Invoice":    ["outstanding_amount", "grand_total"],
						"Invoice Collection":  ["outstanding_amount", "grand_total"],
						"Supplier Payment":    ["outstanding_amount", "grand_total"],
						"Custody Advance":     ["remaining_to_pay", "advance_amount"],
						"Custody Return":      ["unallocated_amount", "remaining_to_pay", "advance_amount"],
						"Accountant Custody":  ["total_billed_amount", "total_amount", "advance_amount"],
					};

					// Prefer category key first, then fall back to refDoctype, then grand_total.
					const amountFields = amountFieldsByKey[category]
						|| amountFieldsByKey[refDoctype]
						|| ["outstanding_amount", "grand_total"];

					// frappe.db.get_value(doctype, name, fields, callback)
					// callback(r) — r is the plain dict {field: value}, NOT r.message
					frappe.db.get_value(refDoctype, refName, amountFields, (r) => {
						let resolvedAmount = 0;
						if (r) {
							for (const field of amountFields) {
								const v = parseFloat(r[field]);
								if (!isNaN(v) && v > 0) {
									resolvedAmount = v;
									break;
								}
							}
						}
						// Set amount and keep it editable so the user can adjust
						// (e.g. partial payment against an invoice)
						dialog.set_value("amount", resolvedAmount || 0);
						dialog.set_df_property("amount", "read_only", 0);
						dialog.get_field("amount").refresh();
						dialog.get_field("narration").focus();
					updateConfirmState();
					deferredConfirmState();
				});
			} else {
				dialog.set_value("amount", 0);
				hideStep3();
				updateConfirmState();
			}
		};

		dialog.fields_dict.expense_account.df.onchange = () => {
			if (dialog.get_value("expense_account")) {
				showStep3(false);
				dialog.get_field("narration").focus();
			} else {
				dialog.set_value("amount", 0);
				hideStep3();
			}
			updateConfirmState();
		};

		dialog.fields_dict.amount.df.onchange = () => updateConfirmState();
		dialog.fields_dict.narration.df.onchange = () => updateConfirmState();

		dialog.show();
		// Keep Confirm state synced while typing (not only on blur/change)
		const amountInput = dialog.get_field("amount") && dialog.get_field("amount").$input;
		const narrationInput = dialog.get_field("narration") && dialog.get_field("narration").$input;
		if (amountInput && amountInput.on) {
			amountInput.on("input", () => { updateConfirmState(); deferredConfirmState(); });
		}
		if (narrationInput && narrationInput.on) {
			narrationInput.on("input", () => { updateConfirmState(); deferredConfirmState(); });
		}
		// Attach input listeners to all Link field inputs for real-time Confirm enable
		setTimeout(() => {
			["party", "reference_name", "expense_account", "bank_account"].forEach((fn) => {
				const f = dialog.get_field(fn);
				if (f && f.$input) {
					f.$input.on("input blur", () => { updateConfirmState(); deferredConfirmState(); });
				}
			});
		}, 400);
		updateConfirmState();
	}

	_getPartyFieldName(doctype) {
		const partyFieldMap = {
			"Sales Invoice": "customer",
			"Purchase Invoice": "supplier",
			"Custody Request": "custodian",
			"Accountant Custody": "custodian",
		};
		return partyFieldMap[doctype] || null;
	}

	_onWizardSubmit(dialog) {
		const values = {
			direction: dialog.get_value("direction"),
			transaction_category: dialog.get_value("transaction_category"),
			party_type: dialog.get_value("party_type"),
			party: dialog.get_value("party"),
			reference_doctype: dialog.get_value("reference_doctype"),
			reference_name: dialog.get_value("reference_name"),
			expense_account: dialog.get_value("expense_account"),
			bank_account: dialog.get_value("bank_account"),
			amount: dialog.get_value("amount"),
			narration: dialog.get_value("narration"),
		};
		const isDirectExpense = values.transaction_category === "Direct Expense";
		const isBankTransfer = ["Bank Withdrawal", "Bank Deposit"].includes(values.transaction_category);

		// Validate mandatory fields
		if (!values.direction) {
			frappe.msgprint(__("Please select Direction."));
			return;
		}
		if (!values.transaction_category) {
			frappe.msgprint(__("Please select Category."));
			return;
		}
		if (isDirectExpense) {
			if (!values.expense_account) {
				frappe.msgprint(__("Please select Expense Account."));
				return;
			}
		} else if (isBankTransfer) {
			if (!values.bank_account) {
				frappe.msgprint(__("Please select a Bank Account."));
				return;
			}
		} else {
			if (!values.party_type) {
				frappe.msgprint(__("Please select Party Type."));
				return;
			}
			if (!values.party) {
				frappe.msgprint(__("Please select Party."));
				return;
			}
			if (!values.reference_name) {
				frappe.msgprint(__("Please select Reference Name."));
				return;
			}
		}
		if ((parseFloat(values.amount) || 0) <= 0) {
			frappe.msgprint(__("Amount must be greater than zero."));
			return;
		}
		if (!(values.narration || "").trim()) {
			frappe.msgprint(__("Narration is mandatory."));
			return;
		}

		// Build row
		const id = Date.now();
		let refDoctype = "";
		let refName = "";

		if (isDirectExpense) {
			refDoctype = "Account";
			refName = values.expense_account;
		} else if (isBankTransfer) {
			refDoctype = "Account";
			refName = values.bank_account;
		} else {
			refDoctype = this._inferRefDoctype(values);
			refName = values.reference_name;
		}

		// Assign serial number per direction
		const year = new Date().getFullYear();
		let voucherSerial = "";
		if (values.direction === "Inbound") {
			this._inboundSerial++;
			voucherSerial = `IN-${year}-${String(this._inboundSerial).padStart(4, "0")}`;
		} else if (values.direction === "Outbound") {
			this._outboundSerial++;
			voucherSerial = `OUT-${year}-${String(this._outboundSerial).padStart(4, "0")}`;
		} else {
			voucherSerial = `BNK-${year}-${String(this._inboundSerial + this._outboundSerial + 1).padStart(4, "0")}`;
		}

		this.rows.push({
			_id: id,
			voucher_serial: voucherSerial,
			direction: values.direction,
			transaction_category: values.transaction_category,
			party_type: (isDirectExpense || isBankTransfer) ? "" : values.party_type,
			party: (isDirectExpense || isBankTransfer) ? "" : values.party,
			reference_doctype: refDoctype,
			reference_name: refName,
			expense_account: isDirectExpense ? values.expense_account : "",
			amount: parseFloat(values.amount) || 0,
			narration: values.narration,
			is_posted: 0,
			linked_document: "",
			linked_doctype: "",
		});

		this._updateKPIs();
		this._renderGrid();
		dialog.hide();
		frappe.show_alert({ message: __("Transaction added successfully."), indicator: "green" });
	}

	// ── KPI Update ────────────────────────────────────────────────────────────

	_sumInflows() {
		return this.rows
			.filter((r) => r.direction === "Inbound")
			.reduce((s, r) => s + (parseFloat(r.amount) || 0), 0);
	}

	_sumOutflows() {
		return this.rows
			.filter((r) => r.direction === "Outbound")
			.reduce((s, r) => s + (parseFloat(r.amount) || 0), 0);
	}

	_updateKPIs() {
		const inflows = this._sumInflows();
		const outflows = this._sumOutflows();
		const expected = this.openingBalance + inflows - outflows;

		const fmt = (v) => frappe.utils.format_number(v, null, 2);
		$("#kpi-opening").text(fmt(this.openingBalance));
		$("#kpi-inflows").text(fmt(inflows));
		$("#kpi-outflows").text(fmt(outflows));
		$("#kpi-expected").text(fmt(expected));
		$("#tcj-denom-expected").text(fmt(expected));
	}

	_updateBadgeCounts() {
		const all = this.rows.length;
		const outbound = this.rows.filter((r) => r.direction === "Outbound").length;
		const inbound = this.rows.filter((r) => r.direction === "Inbound").length;
		const bank = this.rows.filter((r) => r.direction === "Bank Transfer").length;
		$("#badge-all").text(all);
		$("#badge-outbound").text(outbound);
		$("#badge-inbound").text(inbound);
		$("#badge-bank").text(bank);
	}

	_updateRowCount() {
		const filtered = this.activeFilter === "all"
			? this.rows
			: this.rows.filter((r) => r.direction === this.activeFilter);
		$("#tcj-row-count").text(`${filtered.length} row${filtered.length !== 1 ? "s" : ""}`);
	}

	// ── V4: Pending Items ───────────────────────────────────────────────────────────────────

	_loadPendingItems() {
		const station = $("#tcj-station-select").val();
		const date = $("#tcj-date-input").val();
		if (!station || !date) return;

		frappe.call({
			method: "cash_and_securities_management.treasury.page.treasury_cash_journal_cockpit.treasury_cash_journal_cockpit_api.get_pending_items",
			args: { station, posting_date: date },
			callback: (r) => {
				const items = r.message || [];
				this._renderPendingGrid(items);
			},
		});
	}

	_renderPendingGrid(items) {
		const tbody = $("#tcj-pending-tbody");
		const count = items.length;

		// Update badges and banner
		$("#tcj-pending-badge, #tcj-pending-count").text(count);
		if (count > 0) {
			$("#tcj-pending-section").show();
			$("#tcj-pending-banner").css("display", "flex");
		} else {
			$("#tcj-pending-section").hide();
			$("#tcj-pending-banner").css("display", "none");
		}

		if (count === 0) {
			tbody.html('<tr><td colspan="8" class="text-center text-muted py-3">لا توجد حركات معلقة</td></tr>');
			return;
		}

		const dirBadge = (d) => {
			if (d === "Inbound") return '<span class="badge badge-success">وارد</span>';
			if (d === "Outbound") return '<span class="badge badge-danger">صادر</span>';
			return '<span class="badge badge-info">تحويل</span>';
		};

		let html = "";
		items.forEach((item) => {
			const amount = frappe.utils.format_number(item.expected_amount, null, 2);
			const src = item.source_document
				? `<a href="/app/${(item.source_document_type || "").toLowerCase().replace(/ /g, "-")}/${item.source_document}" target="_blank">${item.source_document}</a>`
				: "—";
			html += `
				<tr data-item="${this._escapeHtml(item.name)}">
					<td>${src}</td>
					<td>${dirBadge(item.direction)}</td>
					<td>${this._escapeHtml(item.transaction_category || "")}</td>
					<td>${this._escapeHtml(item.party || "—")}</td>
					<td>${this._escapeHtml(item.reference_name || "—")}</td>
					<td style="text-align:right; font-weight:600;">${amount}</td>
					<td>${this._escapeHtml(item.narration || "")}</td>
					<td style="text-align:center;">
						<button class="btn btn-xs btn-success mr-1 tcj-execute-btn" data-item="${this._escapeHtml(item.name)}" data-amount="${item.expected_amount}">
							<i class="fa fa-check mr-1"></i>تنفيذ
						</button>
						<button class="btn btn-xs btn-danger tcj-cancel-pending-btn" data-item="${this._escapeHtml(item.name)}">
							<i class="fa fa-times"></i>
						</button>
					</td>
				</tr>`;
		});
		tbody.html(html);

		// Bind execute button
		tbody.off("click.pending").on("click.pending", ".tcj-execute-btn", (e) => {
			const itemName = $(e.currentTarget).data("item");
			const expectedAmt = parseFloat($(e.currentTarget).data("amount")) || 0;
			this._executeVaultPendingItem(itemName, expectedAmt);
		});

		// Bind cancel button
		tbody.on("click.pending", ".tcj-cancel-pending-btn", (e) => {
			const itemName = $(e.currentTarget).data("item");
			frappe.prompt(
				[{ fieldtype: "Small Text", fieldname: "reason", label: "سبب الإلغاء", reqd: 1 }],
				(vals) => {
					frappe.call({
						method: "cash_and_securities_management.treasury.page.treasury_cash_journal_cockpit.treasury_cash_journal_cockpit_api.cancel_pending_item",
						args: { item_name: itemName, reason: vals.reason },
						callback: () => {
							frappe.show_alert({ message: "تم إلغاء الحركة", indicator: "orange" });
							this._loadPendingItems();
						},
					});
				},
				"إلغاء الحركة المعلقة",
				"تأكيد الإلغاء"
			);
		});
	}

	_executeVaultPendingItem(itemName, expectedAmount) {
		const d = new frappe.ui.Dialog({
			title: "تنفيذ حركة الخزينة",
			fields: [
				{
					fieldtype: "Currency",
					fieldname: "actual_amount",
					label: "المبلغ الفعلي المسلّم",
					default: expectedAmount,
					reqd: 1,
				},
				{
					fieldtype: "Small Text",
					fieldname: "narration",
					label: "ملاحظة التنفيذ",
				},
			],
			primary_action_label: "تأكيد التنفيذ",
			primary_action: (vals) => {
				d.hide();
				frappe.call({
					method: "cash_and_securities_management.treasury.page.treasury_cash_journal_cockpit.treasury_cash_journal_cockpit_api.execute_pending_item",
					args: {
						item_name: itemName,
						actual_amount: vals.actual_amount,
						narration: vals.narration,
					},
					freeze: true,
					freeze_message: "جاري تسجيل التنفيذ...",
					callback: (r) => {
						if (!r.message) return;
						const res = r.message;
						// Print the voucher for this executed item
						const station = this.stationData
							? (this.stationData.station_name || this.stationData.name)
							: "";
						this._printVoucher({
							serial: res.serial || res.item_name,
							station,
							date: $("#tcj-date-input").val(),
							direction: "",
							transaction_category: "",
							party: "",
							reference_name: "",
							amount: res.actual_amount || expectedAmount,
							narration: vals.narration || "",
						});
						frappe.show_alert({ message: `تم تنفيذ الحركة وإضافتها لليومية ${res.journal_name}`, indicator: "green" });
						// Reload both grids
						this._loadPendingItems();
						this._loadJournal();
					},
				});
			},
		});
		d.show();
	}

	_updateStatusBadge() {
		const badge = $("#tcj-status-badge");
		badge.removeClass("badge-secondary badge-success badge-warning badge-info");
		const statusMap = {
			"Draft":          ["badge-secondary", "مسودة"],
			"Pending Review": ["badge-warning",   "قيد المراجعة"],
			"Posted":         ["badge-success",   "مرحّل"],
			"Closed":         ["badge-info",      "مغلق"],
		};
		const [cls, label] = statusMap[this.journalStatus || (this.posted ? "Posted" : "Draft")] || ["badge-secondary", "مسودة"];
		badge.addClass(cls).text(label);
		const locked = ["Pending Review", "Posted", "Closed"].includes(this.journalStatus);
		if (locked) {
			$("#tcj-save-btn, #tcj-add-txn-btn").prop("disabled", true).hide();
			$("#tcj-post-btn").prop("disabled", true).hide();
		} else {
			$("#tcj-save-btn, #tcj-add-txn-btn").prop("disabled", false).show();
			$("#tcj-post-btn").prop("disabled", false).show();
		}
	}

	_updateDenomCard() {
		if (this.rows.length > 0) {
			$("#tcj-denomination-card").show();
		}
	}

	// ── Save Draft ────────────────────────────────────────────────────────────

	_saveDraft(cb) {
		const station = $("#tcj-station-select").val();
		const date = $("#tcj-date-input").val();
		if (!station || !date) {
			frappe.msgprint({ title: "تحذير", message: "يرجى اختيار المحطة والتاريخ أولاً.", indicator: "orange" });
			return;
		}

		frappe.call({
			method: "cash_and_securities_management.treasury.page.treasury_cash_journal_cockpit.treasury_cash_journal_cockpit_api.save_journal_draft",
			args: {
				station,
				posting_date: date,
				lines: this.rows,
				journal_name: this.journalName,
			},
			callback: (r) => {
				if (r.message) {
					this.journalName = r.message;
					$("#tcj-journal-name").val(r.message);
					frappe.show_alert({ message: `تم حفظ المسودة: ${r.message}`, indicator: "green" });
					if (typeof cb === "function") cb(r.message);
				}
			},
		});
	}

	// ── Post Journal ──────────────────────────────────────────────────────────

	_confirmPost() {
		if (!this.journalName) {
			// Auto-save first, then send for review
			this._saveDraft(() => this._doSendForReview());
			return;
		}
		if (this.rows.length === 0) {
			frappe.msgprint({
				title: "تحذير",
				message: "لا يمكن إرسال يومية فارغة للمراجعة.",
				indicator: "orange",
			});
			return;
		}

		const variance = parseFloat($("#tcj-denom-variance").text().replace(/,/g, "")) || 0;
		const narration = $("#tcj-variance-narration").val();

		if (Math.abs(variance) > 0.01 && !narration) {
			frappe.msgprint({
				title: "فرق في الرصيد",
				message: `تم اكتشاف فرق بقيمة <strong>${variance}</strong>. يرجى إدخال بيان الفرق قبل الإرسال.`,
				indicator: "red",
			});
			return;
		}

		frappe.confirm(
			`إرسال اليومية <strong>${this.journalName}</strong> لمراجعة المحاسب؟<br/>
			<span class="text-muted small">سيتم إغلاق الكوكبيت وستظهر اليومية في نموذج Treasury Cash Journal للمراجعة والتقديم.</span>`,
			() => this._doSendForReview()
		);
	}

	_doSendForReview() {
		const saveThenSend = (jname) => {
			frappe.call({
				method: "cash_and_securities_management.treasury.page.treasury_cash_journal_cockpit.treasury_cash_journal_cockpit_api.send_for_review",
				args: { journal_name: jname },
				freeze: true,
				freeze_message: "جاري إرسال اليومية للمراجعة...",
				callback: (r) => {
					if (!r.message) return;
					const result = r.message;
					this.journalStatus = "Pending Review";
					this.posted = false;
					this._updateStatusBadge();

					// Show success with link to TCJ form
					const link = result.url
						? `<a href="${result.url}" target="_blank" class="btn btn-xs btn-primary ml-2">
							<i class="fa fa-external-link mr-1"></i>فتح اليومية</a>`
						: "";
					frappe.msgprint({
						title: "تم الإرسال بنجاح ✔️",
						message: `تم إرسال اليومية <strong>${result.journal_name}</strong> لمراجعة المحاسب.
							<br/>يمكن للمحاسب مراجعة القيود وتقديمها من نموذج Treasury Cash Journal.${link}`,
						indicator: "green",
					});
				},
			});
		};

		if (!this.journalName) {
			this._saveDraft((jname) => saveThenSend(jname));
		} else {
			saveThenSend(this.journalName);
		}
	}

	// ── Print Voucher ────────────────────────────────────────────────────────

	_printVoucherFromDialog(dialog) {
		const values = {
			direction:            dialog.get_value("direction"),
			transaction_category: dialog.get_value("transaction_category"),
			party:                dialog.get_value("party") || "",
			reference_name:       dialog.get_value("reference_name") || dialog.get_value("expense_account") || dialog.get_value("bank_account") || "",
			amount:               parseFloat(dialog.get_value("amount")) || 0,
			narration:            dialog.get_value("narration") || "",
		};

		const station = this.stationData
			? (this.stationData.station_name || this.stationData.name)
			: ($("#tcj-station-select option:selected").text() || "");

		// Compute a preview serial (not yet committed)
		const year = new Date().getFullYear();
		let previewSerial = "";
		if (values.direction === "Inbound") {
			previewSerial = `IN-${year}-${String(this._inboundSerial + 1).padStart(4, "0")}`;
		} else if (values.direction === "Outbound") {
			previewSerial = `OUT-${year}-${String(this._outboundSerial + 1).padStart(4, "0")}`;
		} else {
			previewSerial = `BNK-${year}-PREVIEW`;
		}

		this._printVoucher({
			serial:   previewSerial,
			station:  station,
			date:     $("#tcj-date-input").val(),
			...values,
		});
	}

	_printVoucher(data) {
		const now = new Date();
		const timeStr = now.toLocaleTimeString("ar-SA", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
		const dateStr = data.date || frappe.datetime.get_today();
		const user = frappe.session.user_fullname || frappe.session.user || "";

		const directionAr = { "Inbound": "وارد / Inbound", "Outbound": "صادر / Outbound", "Bank Transfer": "تحويل بنكي / Bank Transfer" };
		const dirLabel = directionAr[data.direction] || data.direction || "";
		const dirColor = data.direction === "Inbound" ? "#155724" : data.direction === "Outbound" ? "#721c24" : "#004085";

		const html = `
<!DOCTYPE html>
<html lang="ar" dir="ltr">
<head>
<meta charset="UTF-8"/>
<title>سند حركة خزينة - ${data.serial}</title>
<style>
  @media print { body { margin: 0; } .no-print { display: none; } }
  body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; color: #212529; background: #fff; }
  .voucher { width: 480px; margin: 20px auto; border: 2px solid #343a40; border-radius: 6px; overflow: hidden; }
  .voucher-header { background: #343a40; color: #fff; padding: 12px 16px; text-align: center; }
  .voucher-header h2 { margin: 0; font-size: 1.1rem; letter-spacing: 1px; }
  .voucher-header p  { margin: 4px 0 0; font-size: 0.8rem; opacity: 0.8; }
  .voucher-body { padding: 14px 18px; }
  .row-item { display: flex; justify-content: space-between; padding: 5px 0; border-bottom: 1px solid #f0f0f0; }
  .row-item:last-child { border-bottom: none; }
  .lbl { color: #6c757d; font-size: 0.82rem; min-width: 160px; }
  .val { font-weight: 600; text-align: right; }
  .direction-badge { display: inline-block; padding: 3px 12px; border-radius: 20px; font-weight: 700; font-size: 0.9rem; color: #fff; background: ${dirColor}; }
  .amount-row .val { font-size: 1.2rem; color: ${dirColor}; }
  .voucher-footer { background: #f8f9fa; border-top: 1px solid #dee2e6; padding: 10px 18px; font-size: 0.78rem; color: #6c757d; }
  .sig-line { border-top: 1px solid #adb5bd; width: 160px; margin-top: 20px; padding-top: 4px; text-align: center; }
  .print-btn { display: block; margin: 12px auto; padding: 8px 24px; background: #343a40; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 0.9rem; }
</style>
</head>
<body>
<div class="voucher">
  <div class="voucher-header">
    <h2>سند حركة خزينة &nbsp;|&nbsp; VAULT MOVEMENT VOUCHER</h2>
    <p>${data.station || ""}</p>
  </div>
  <div class="voucher-body">
    <div class="row-item">
      <span class="lbl">الرقم التسلسلي / Serial</span>
      <span class="val">${data.serial}</span>
    </div>
    <div class="row-item">
      <span class="lbl">التاريخ / Date</span>
      <span class="val">${dateStr}</span>
    </div>
    <div class="row-item">
      <span class="lbl">الوقت / Time</span>
      <span class="val">${timeStr}</span>
    </div>
    <div class="row-item">
      <span class="lbl">اتجاه الحركة / Direction</span>
      <span class="val"><span class="direction-badge">${dirLabel}</span></span>
    </div>
    <div class="row-item">
      <span class="lbl">نوع المعاملة / Category</span>
      <span class="val">${data.transaction_category || ""}</span>
    </div>
    <div class="row-item">
      <span class="lbl">الطرف / Party</span>
      <span class="val">${data.party || "—"}</span>
    </div>
    <div class="row-item">
      <span class="lbl">المرجع / Reference</span>
      <span class="val">${data.reference_name || "—"}</span>
    </div>
    <div class="row-item amount-row">
      <span class="lbl">المبلغ / Amount</span>
      <span class="val">${frappe.utils.format_number(data.amount, null, 2)}</span>
    </div>
    <div class="row-item">
      <span class="lbl">البيان / Narration</span>
      <span class="val" style="max-width:240px;text-align:right;word-break:break-word;">${data.narration || "—"}</span>
    </div>
  </div>
  <div class="voucher-footer" style="display:flex; justify-content:space-between; align-items:flex-end;">
    <div>
      <div>أعده / Prepared by: <strong>${user}</strong></div>
      <div style="margin-top:2px;">${timeStr}</div>
    </div>
    <div class="sig-line">توقيع المستلم / Recipient Signature</div>
  </div>
</div>
<button class="print-btn no-print" onclick="window.print(); window.close();">&#128438; طباعة / Print</button>
</body>
</html>`;

		const win = window.open("", "_blank", "width=560,height=700,scrollbars=yes");
		if (win) {
			win.document.write(html);
			win.document.close();
			win.focus();
		} else {
			frappe.msgprint({ title: "تحذير", message: "تعذّر فتح نافذة الطباعة. يرجى السماح بالنوافذ المنبثقة.", indicator: "orange" });
		}
	}

	// ── Helpers ───────────────────────────────────────────────────────────────

	_escapeHtml(value) {
		if (frappe.utils && typeof frappe.utils.escape_html === "function") {
			return frappe.utils.escape_html(value || "");
		}
		return $("<div>").text(value || "").html();
	}

	_getRow(id) {
		return this.rows.find((r) => r._id === id);
	}
}
