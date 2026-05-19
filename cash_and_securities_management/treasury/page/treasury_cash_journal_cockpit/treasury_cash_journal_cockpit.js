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
        Treasury Cash Journal
      </h4>
    </div>
    <div class="col-auto ml-3">
      <select id="tcj-station-select" class="form-control form-control-sm" style="min-width:200px;">
        <option value="">— Select Station —</option>
      </select>
    </div>
    <div class="col-auto">
      <input type="date" id="tcj-date-input" class="form-control form-control-sm" style="min-width:140px;" />
    </div>
    <div class="col-auto">
      <span id="tcj-status-badge" class="badge badge-secondary" style="font-size:0.85rem; padding:6px 12px;">Draft</span>
    </div>
    <div class="col-auto ml-auto">
      <button id="tcj-add-txn-btn" class="btn btn-sm btn-success mr-2">
				<i class="fa fa-plus mr-1"></i> Record Vault Movement
      </button>
      <button id="tcj-save-btn" class="btn btn-sm btn-default mr-2">
        <i class="fa fa-save mr-1"></i> Save Draft
      </button>
      <button id="tcj-post-btn" class="btn btn-sm btn-primary">
        <i class="fa fa-check-circle mr-1"></i> Post Journal
      </button>
    </div>
  </div>

  <!-- KPI Cards -->
  <div class="tcj-kpi-row row mb-3" id="tcj-kpi-row">
    <div class="col-md-3 col-sm-6 mb-2">
      <div class="tcj-kpi-card card shadow-sm" style="border-left:4px solid #6c757d;">
        <div class="card-body py-2 px-3">
          <div class="tcj-kpi-label text-muted" style="font-size:0.75rem; text-transform:uppercase; letter-spacing:0.05em;">Opening Balance</div>
          <div class="tcj-kpi-value" id="kpi-opening" style="font-size:1.4rem; font-weight:700; color:#495057;">0.00</div>
        </div>
      </div>
    </div>
    <div class="col-md-3 col-sm-6 mb-2">
      <div class="tcj-kpi-card card shadow-sm" style="border-left:4px solid #28a745;">
        <div class="card-body py-2 px-3">
          <div class="tcj-kpi-label text-muted" style="font-size:0.75rem; text-transform:uppercase; letter-spacing:0.05em;">Total Inflows</div>
          <div class="tcj-kpi-value" id="kpi-inflows" style="font-size:1.4rem; font-weight:700; color:#28a745;">0.00</div>
        </div>
      </div>
    </div>
    <div class="col-md-3 col-sm-6 mb-2">
      <div class="tcj-kpi-card card shadow-sm" style="border-left:4px solid #dc3545;">
        <div class="card-body py-2 px-3">
          <div class="tcj-kpi-label text-muted" style="font-size:0.75rem; text-transform:uppercase; letter-spacing:0.05em;">Total Outflows</div>
          <div class="tcj-kpi-value" id="kpi-outflows" style="font-size:1.4rem; font-weight:700; color:#dc3545;">0.00</div>
        </div>
      </div>
    </div>
    <div class="col-md-3 col-sm-6 mb-2">
      <div class="tcj-kpi-card card shadow-sm" style="border-left:4px solid var(--primary);">
        <div class="card-body py-2 px-3">
          <div class="tcj-kpi-label text-muted" style="font-size:0.75rem; text-transform:uppercase; letter-spacing:0.05em;">Expected Balance</div>
          <div class="tcj-kpi-value" id="kpi-expected" style="font-size:1.4rem; font-weight:700; color:var(--primary);">0.00</div>
        </div>
      </div>
    </div>
  </div>

  <!-- Tab Filter Bar -->
  <ul class="nav nav-tabs mb-0" id="tcj-tabs" role="tablist" style="border-bottom:2px solid var(--primary);">
    <li class="nav-item">
      <a class="nav-link active" id="tab-all" data-filter="all" href="#" role="tab">
        All <span class="badge badge-secondary ml-1" id="badge-all">0</span>
      </a>
    </li>
    <li class="nav-item">
      <a class="nav-link" id="tab-outbound" data-filter="Outbound" href="#" role="tab">
        <span style="color:#dc3545;">&#8595;</span> Outbound
        <span class="badge badge-danger ml-1" id="badge-outbound">0</span>
      </a>
    </li>
    <li class="nav-item">
      <a class="nav-link" id="tab-inbound" data-filter="Inbound" href="#" role="tab">
        <span style="color:#28a745;">&#8593;</span> Inbound
        <span class="badge badge-success ml-1" id="badge-inbound">0</span>
      </a>
    </li>
  </ul>

  <!-- Transaction Grid -->
  <div class="tcj-grid-wrapper" style="overflow-x:auto; background:#fff; border:1px solid #dee2e6; border-top:none;">
    <table class="table table-sm table-hover mb-0" id="tcj-grid">
      <thead style="background:var(--subtle-fg); position:sticky; top:0; z-index:10;">
        <tr>
          <th style="width:30px;">#</th>
          <th style="width:110px;">Direction</th>
          <th style="width:150px;">Category</th>
          <th style="width:120px;">Party Type</th>
          <th style="width:180px;">Party</th>
          <th style="width:160px;">Reference</th>
          <th style="width:120px; text-align:right;">Amount</th>
          <th>Narration</th>
          <th style="width:80px; text-align:center;">Status</th>
          <th style="width:40px;"></th>
        </tr>
      </thead>
      <tbody id="tcj-tbody">
      </tbody>
    </table>
  </div>

  <!-- Read-only Row Count Indicator -->
  <div class="tcj-toolbar mt-2 mb-3 d-flex align-items-center">
		<span class="text-muted small"><i class="fa fa-info-circle mr-1"></i> <strong>Read-Only Table:</strong> Use "Record Vault Movement" to add entries through the wizard.</span>
    <span class="text-muted small ml-auto" id="tcj-row-count">0 rows</span>
  </div>

  <!-- End-of-Day Denomination Drawer -->
  <div class="card mt-3" id="tcj-denomination-card" style="display:none;">
    <div class="card-header d-flex justify-content-between align-items-center"
         style="cursor:pointer; background:var(--subtle-fg);"
         id="tcj-denomination-toggle">
      <span><i class="fa fa-calculator mr-2"></i> End-of-Day Denomination Count</span>
      <i class="fa fa-chevron-down" id="tcj-denom-chevron"></i>
    </div>
    <div class="card-body" id="tcj-denomination-body">
      <div class="row">
        <div class="col-md-6">
          <table class="table table-sm" id="tcj-denom-table">
            <thead>
              <tr>
                <th>Denomination</th>
                <th style="width:100px;">Count</th>
                <th style="width:120px; text-align:right;">Total</th>
              </tr>
            </thead>
            <tbody id="tcj-denom-tbody"></tbody>
            <tfoot>
              <tr style="font-weight:700; border-top:2px solid #dee2e6;">
                <td colspan="2">Physical Count Total</td>
                <td style="text-align:right;" id="tcj-denom-total">0.00</td>
              </tr>
            </tfoot>
          </table>
        </div>
        <div class="col-md-6">
          <div class="card bg-light p-3">
            <div class="row mb-2">
              <div class="col-6 text-muted">Expected Balance:</div>
              <div class="col-6 text-right font-weight-bold" id="tcj-denom-expected">0.00</div>
            </div>
            <div class="row mb-2">
              <div class="col-6 text-muted">Actual (Counted):</div>
              <div class="col-6 text-right font-weight-bold" id="tcj-denom-actual">0.00</div>
            </div>
            <div class="row mb-3">
              <div class="col-6 text-muted">Variance:</div>
              <div class="col-6 text-right font-weight-bold" id="tcj-denom-variance" style="color:#dc3545;">0.00</div>
            </div>
            <div class="form-group mb-2">
              <label class="small text-muted">Variance Narration (required if variance &ne; 0)</label>
              <textarea id="tcj-variance-narration" class="form-control form-control-sm" rows="2"
                        placeholder="Explain the reason for shortage or overage..."></textarea>
            </div>
          </div>
        </div>
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
		this.openingBalance = 0;
		this.stationData = null;
		this.posted = false;

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
				if (!r.message) return;
				const sel = $("#tcj-station-select");
				r.message.forEach((s) => {
					sel.append(`<option value="${s.name}">${s.station_name}</option>`);
				});
				if (r.message.length === 1) {
					sel.val(r.message[0].name);
					this._loadJournal();
				}
			},
		});
	}

	_bindEvents() {
		$("#tcj-station-select").on("change", () => this._loadJournal());
		$("#tcj-date-input").on("change", () => this._loadJournal());

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
				this.posted = data.existing && data.existing.posting_status === "Posted";

				this.rows = (data.lines || []).map((l, i) => ({
					_id: i,
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
		if (row.direction === "Inbound" && row.transaction_category === "Custody Return") {
			return "Custody Request";
		}
		if (row.transaction_category === "Advance Allocation") {
			return "Accountant Custody";
		}
		if (row.transaction_category === "Direct Expense") {
			return "Account";
		}
		return "";
	}

	// ── Multi-Step Wizard Dialog ────────────────────────────────────────────

	_showAddTransactionWizard() {
		if (this.posted) {
			frappe.msgprint(__("This journal is already posted. No new rows can be added."));
			return;
		}

		const categoryConfig = {
			"Invoice Collection": { party_type: "Customer", reference_doctype: "Sales Invoice", is_direct_expense: false, is_bank_transfer: false },
			"Custody Return": { party_type: "Custodian", reference_doctype: "Custody Request", is_direct_expense: false, is_bank_transfer: false },
			"Supplier Payment": { party_type: "Supplier", reference_doctype: "Purchase Invoice", is_direct_expense: false, is_bank_transfer: false },
			"Advance Allocation": { party_type: "Custodian", reference_doctype: "Accountant Custody", is_direct_expense: false, is_bank_transfer: false },
			"Direct Expense": { party_type: "", reference_doctype: "", is_direct_expense: true, is_bank_transfer: false },
			"Bank Withdrawal": { party_type: "Bank Account", reference_doctype: "", is_direct_expense: false, is_bank_transfer: true },
			"Bank Deposit": { party_type: "Bank Account", reference_doctype: "", is_direct_expense: false, is_bank_transfer: true },
		};

		const wizardFields = [
			// ─ Step 1: Classification ─
			{
				fieldtype: "Section Break",
				fieldname: "step1_section",
				label: "Step 1: Transaction Classification",
				hidden: 0,
			},
			{
				fieldtype: "Select",
				fieldname: "direction",
				label: "Direction",
				options: ["", "Inbound", "Outbound", "Bank Transfer"],
				hidden: 0,
			},
			{
				fieldtype: "Select",
				fieldname: "transaction_category",
				label: "Category",
				options: [],
				hidden: 1,
			},

			// ─ Step 2: Linking & Cascading Filters ─
			{
				fieldtype: "Section Break",
				fieldname: "step2_section",
				label: "Step 2: Link & Party Information",
				hidden: 1,
			},
			{
				fieldtype: "Link",
				fieldname: "party_type",
				label: "Party Type",
				options: "Party Type",
				hidden: 1,
				read_only: 1,
			},
			{
				fieldtype: "Link",
				fieldname: "party",
				label: "Party",
				options: "Customer",
				hidden: 1,
			},
			{
				fieldtype: "Data",
				fieldname: "reference_doctype",
				label: "Reference Type",
				hidden: 1,
				read_only: 1,
			},
			{
				fieldtype: "Link",
				fieldname: "reference_name",
				label: "Reference Name",
				options: "Sales Invoice",
				hidden: 1,
			},
			{
				fieldtype: "Link",
				fieldname: "expense_account",
				label: "Expense Account",
				options: "Account",
				hidden: 1,
			},

			// ─ Step 3: Financial Automation & Validation ─
			{
				fieldtype: "Section Break",
				fieldname: "step3_section",
				label: "Step 3: Amount & Narration",
				hidden: 1,
			},
			{
				fieldtype: "Currency",
				fieldname: "amount",
				label: "Amount",
				read_only: 0,
				hidden: 1,
			},
			{
				fieldtype: "Small Text",
				fieldname: "narration",
				label: "Narration",
				hidden: 1,
			},
		];

		const dialog = new frappe.ui.Dialog({
			title: "Record Vault Movement",
			fields: wizardFields,
			primary_action_label: __("Confirm"),
			primary_action: () => this._onWizardSubmit(dialog),
		});

		dialog.get_field("expense_account").df.get_query = () => ({
			filters: {
				root_type: "Expense",
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
			dialog.set_df_property("party", "reqd", 0);
			dialog.set_df_property("reference_name", "reqd", 0);
			dialog.set_df_property("expense_account", "reqd", 0);
			dialog.get_field("party_type").refresh();
			dialog.get_field("party").refresh();
			dialog.get_field("reference_name").refresh();
			dialog.get_field("expense_account").refresh();
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
				hasLinks = !!dialog.get_value("party");
			} else {
				hasLinks = !!dialog.get_value("party_type") && !!dialog.get_value("party") && !!dialog.get_value("reference_name");
			}
			const canConfirm = hasBase && hasLinks && amount > 0 && narration.length > 0;

			dialog.get_primary_btn().prop("disabled", !canConfirm);
		};

		// ─ Event Handlers for Dynamic Field Updates ─

		// When Direction changes, update Category options and visibility
		dialog.fields_dict.direction.df.onchange = () => {
			const direction = dialog.get_value("direction");
			let catOptions = [];

			if (direction === "Inbound") {
				catOptions = ["", "Invoice Collection", "Custody Return"];
			} else if (direction === "Outbound") {
				catOptions = ["", "Supplier Payment", "Advance Allocation", "Direct Expense"];
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
					// Bank Transfer: show party (Bank Account) only, Step 3 will show after party selected
					dialog.set_df_property("party", "hidden", 0);
					dialog.set_df_property("party", "options", "Bank Account");
					dialog.get_field("party").refresh();
					hideStep3(); // Hide until party is selected
				} else {
					// Standard categories: show party field and reference_name, Step 3 will show after reference_name selected
					dialog.set_df_property("party", "hidden", 0);
					dialog.set_df_property("reference_name", "hidden", 0);
					dialog.set_df_property("party", "options", cfg.party_type || "Customer");
					dialog.set_df_property("reference_name", "options", cfg.reference_doctype || "Sales Invoice");
					dialog.get_field("party").refresh();
					dialog.get_field("reference_name").refresh();
					hideStep3(); // Hide until reference_name is selected
				}
			}

			// Reset subsequent fields
			dialog.set_value("party", "");
			dialog.set_value("reference_name", "");
			dialog.set_value("expense_account", "");
			dialog.set_value("amount", 0);
			dialog.set_value("narration", "");
			updateConfirmState();
		};

		dialog.fields_dict.party.df.onchange = () => {
			const refDoctype = dialog.get_value("reference_doctype");
			const party = dialog.get_value("party");
			const cfg = categoryConfig[dialog.get_value("transaction_category")] || null;
			dialog.set_value("reference_name", "");
			dialog.set_value("amount", 0);
			dialog.set_value("narration", "");
			hideStep3();
			
			// For Bank Transfer, no reference doc needed — show Step 3 for manual amount entry after party selected
			if (cfg && cfg.is_bank_transfer) {
				if (party) showStep3(false);
				updateConfirmState();
				return;
			}
			
			if (!party || !refDoctype) {
				updateConfirmState();
				return;
			}

			const partyField = this._getPartyFieldName(refDoctype);
			dialog.get_field("reference_name").df.get_query = () => {
				const filters = { docstatus: 1 };
				if (partyField) {
					filters[partyField] = party;
				}

				if (refDoctype === "Sales Invoice" || refDoctype === "Purchase Invoice") {
					filters.outstanding_amount = [">", 0];
				} else if (refDoctype === "Custody Request") {
					filters.unallocated_amount = [">", 0];
					filters.status = ["in", ["Paid", "Partly Claimed", "Approved", "Partly Paid"]];
				} else if (refDoctype === "Accountant Custody") {
					filters.status = ["in", ["Fully Invoiced", "Partly Settled"]];
				}

				return { filters };
			};
			dialog.get_field("reference_name").refresh();
			updateConfirmState();
		};

		// When Reference Name is selected, auto-fill Amount
		dialog.fields_dict.reference_name.df.onchange = () => {
			const refName = dialog.get_value("reference_name");
			const refDoctype = dialog.get_value("reference_doctype");
			if (refName && refDoctype) {
				let amountField = "outstanding_amount";
				if (refDoctype === "Custody Request") {
					amountField = "unallocated_amount";
				} else if (refDoctype === "Accountant Custody") {
					amountField = "total_billed_amount";
				}

				frappe.db.get_value(refDoctype, refName, amountField, (r) => {
					if (r.message) {
						dialog.set_value("amount", parseFloat(r.message[amountField]) || 0);
						showStep3(true);
						dialog.get_field("narration").focus();
						updateConfirmState();
					}
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
		dialog.get_primary_btn().prop("disabled", true);
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
		const values = dialog.get_values(true); // true = skip mandatory highlight, we validate manually
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
			if (!values.party) {
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
			refDoctype = "Bank Account";
			refName = values.party;
		} else {
			refDoctype = this._inferRefDoctype(values);
			refName = values.reference_name;
		}

		this.rows.push({
			_id: id,
			direction: values.direction,
			transaction_category: values.transaction_category,
			party_type: (isDirectExpense || isBankTransfer) ? "" : values.party_type,
			party: (isDirectExpense) ? "" : values.party,
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
		$("#badge-all").text(all);
		$("#badge-outbound").text(outbound);
		$("#badge-inbound").text(inbound);
	}

	_updateRowCount() {
		const filtered = this.activeFilter === "all"
			? this.rows
			: this.rows.filter((r) => r.direction === this.activeFilter);
		$("#tcj-row-count").text(`${filtered.length} row${filtered.length !== 1 ? "s" : ""}`);
	}

	_updateStatusBadge() {
		const badge = $("#tcj-status-badge");
		badge.removeClass("badge-secondary badge-success badge-warning");
		if (this.posted) {
			badge.addClass("badge-success").text("Posted");
			$("#tcj-save-btn, #tcj-add-txn-btn").prop("disabled", true).hide();
		} else {
			badge.addClass("badge-secondary").text("Draft");
			$("#tcj-save-btn, #tcj-add-txn-btn").prop("disabled", false).show();
		}
	}

	_updateDenomCard() {
		if (this.rows.length > 0) {
			$("#tcj-denomination-card").show();
		}
	}

	// ── Save Draft ────────────────────────────────────────────────────────────

	_saveDraft() {
		const station = $("#tcj-station-select").val();
		const date = $("#tcj-date-input").val();
		if (!station || !date) {
			frappe.msgprint(__("Please select a station and date first."));
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
					frappe.show_alert({ message: __("Draft saved: {0}").replace("{0}", r.message), indicator: "green" });
				}
			},
		});
	}

	// ── Post Journal ──────────────────────────────────────────────────────────

	_confirmPost() {
		if (!this.journalName) {
			frappe.msgprint(__("Please save the draft first before posting."));
			return;
		}
		if (this.rows.filter((r) => !r.is_posted).length === 0) {
			frappe.msgprint(__("All rows are already posted."));
			return;
		}

		const variance = parseFloat($("#tcj-denom-variance").text().replace(/,/g, "")) || 0;
		const narration = $("#tcj-variance-narration").val();

		if (Math.abs(variance) > 0.01 && !narration) {
			frappe.msgprint(__("A variance of {0} was detected. Please enter a Variance Narration before posting.").replace("{0}", variance));
			return;
		}

		frappe.confirm(
			__("Post journal <strong>{0}</strong>? This will execute vault movement posting for all unposted rows and cannot be undone.").replace("{0}", this.journalName),
			() => this._doPost(variance, narration)
		);
	}

	_doPost(actualBalance, varianceNarration) {
		const expected = this.openingBalance + this._sumInflows() - this._sumOutflows();
		const actual = actualBalance !== 0 ? expected + actualBalance : expected;

		frappe.call({
			method: "cash_and_securities_management.treasury.page.treasury_cash_journal_cockpit.treasury_cash_journal_cockpit_api.post_journal",
			args: {
				journal_name: this.journalName,
				actual_balance: actual,
				variance_narration: varianceNarration,
			},
			freeze: true,
			freeze_message: __("Posting journal - executing vault movement logic..."),
			callback: (r) => {
				if (!r.message) return;
				const result = r.message;

				result.lines.forEach((l) => {
					const row = this.rows.find((r) => r._id == l.idx - 1 || r.idx == l.idx);
					if (row) {
						row.is_posted = l.is_posted;
						row.linked_document = l.linked_document;
						row.linked_doctype = l.linked_doctype || row.linked_doctype;
					}
				});

				this.posted = result.status === "Posted";
				this._updateKPIs();
				this._renderGrid();
				this._updateStatusBadge();

				if (result.status === "Posted") {
					frappe.show_alert({
						message: __("Journal {0} posted successfully!").replace("{0}", this.journalName),
						indicator: "green",
					});
				}
			},
		});
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
