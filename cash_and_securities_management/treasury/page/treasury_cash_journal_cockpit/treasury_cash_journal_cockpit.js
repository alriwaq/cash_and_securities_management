frappe.pages["treasury-cash-journal-cockpit"].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Cash Journal Cockpit",
		single_column: true,
	});

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
    <li class="nav-item">
      <a class="nav-link" id="tab-bank" data-filter="Bank Transfer" href="#" role="tab">
        <i class="fa fa-exchange"></i> Bank
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

  <!-- Add Row / Toolbar -->
  <div class="tcj-toolbar mt-2 mb-3 d-flex align-items-center">
    <button id="tcj-add-row-btn" class="btn btn-sm btn-outline-primary mr-2">
      <i class="fa fa-plus mr-1"></i> Add Row
    </button>
    <span class="text-muted small" id="tcj-row-count">0 rows</span>
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

		$("#tcj-add-row-btn").on("click", () => this._addRow());
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

	// ── Journal Load ─────────────────────────────────────────────────────────

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
					amount: l.amount || 0,
					narration: l.narration || "",
					is_posted: l.is_posted || 0,
					linked_document: l.linked_document || "",
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

	// ── Row Management ────────────────────────────────────────────────────────

	_addRow() {
		if (this.posted) {
			frappe.msgprint(__("This journal is already posted. No new rows can be added."));
			return;
		}
		const id = Date.now();
		this.rows.push({
			_id: id,
			direction: "",
			transaction_category: "",
			party_type: "",
			party: "",
			reference_doctype: "",
			reference_name: "",
			amount: 0,
			narration: "",
			is_posted: 0,
			linked_document: "",
		});
		this._renderGrid();
		setTimeout(() => {
			$(`#row-${id} .tcj-direction`).focus();
		}, 50);
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
						No rows yet. Click <strong>Add Row</strong> to begin.
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
		const readOnly = posted || this.posted;
		const rowClass = posted
			? "table-success"
			: (row.direction === "Inbound"
				? "tcj-row-inbound"
				: row.direction === "Outbound"
					? "tcj-row-outbound"
					: "");

		const dirOptions = ["", "Inbound", "Outbound", "Bank Transfer"]
			.map((d) => `<option value="${d}" ${row.direction === d ? "selected" : ""}>${d || "—"}</option>`)
			.join("");

		const catOptions = ["", "Invoice Payment", "Advance Allocation", "Direct Expense", "Bank Liquidity"]
			.map((c) => `<option value="${c}" ${row.transaction_category === c ? "selected" : ""}>${c || "—"}</option>`)
			.join("");

		const ptOptions = ["", "Customer", "Supplier", "Custodian", "Bank Account"]
			.map((p) => `<option value="${p}" ${row.party_type === p ? "selected" : ""}>${p || "—"}</option>`)
			.join("");

		const statusCell = posted
			? `<span class="badge badge-success"><i class="fa fa-check"></i> Posted</span>
			   <a href="/app/payment-entry/${row.linked_document}" target="_blank"
			      class="small ml-1" title="Open ${row.linked_document}">
			      <i class="fa fa-external-link"></i>
			   </a>`
			: `<span class="badge badge-secondary">Draft</span>`;

		const deleteBtn = (!readOnly)
			? `<button class="btn btn-xs btn-danger tcj-delete-row" data-id="${row._id}" title="Delete row">
			     <i class="fa fa-trash"></i>
			   </button>`
			: "";

		return `
			<tr id="row-${row._id}" class="${rowClass}" data-id="${row._id}">
				<td class="text-muted small">${idx}</td>
				<td>
					<select class="form-control form-control-sm tcj-direction" data-id="${row._id}"
					        ${readOnly ? "disabled" : ""}>
						${dirOptions}
					</select>
				</td>
				<td>
					<select class="form-control form-control-sm tcj-category" data-id="${row._id}"
					        ${readOnly ? "disabled" : ""}>
						${catOptions}
					</select>
				</td>
				<td>
					<select class="form-control form-control-sm tcj-party-type" data-id="${row._id}"
					        ${readOnly ? "disabled" : ""}>
						${ptOptions}
					</select>
				</td>
				<td>
					<input type="text" class="form-control form-control-sm tcj-party" data-id="${row._id}"
					       value="${frappe.utils.escape_html(row.party || "")}"
					       placeholder="Party..." ${readOnly ? "readonly" : ""} />
				</td>
				<td>
					<div class="d-flex">
						<input type="text" class="form-control form-control-sm tcj-ref-name" data-id="${row._id}"
						       value="${frappe.utils.escape_html(row.reference_name || "")}"
						       placeholder="Reference..." ${readOnly ? "readonly" : ""} style="flex:1;" />
						${!readOnly && row.party_type && row.party ? `
						<button class="btn btn-xs btn-outline-secondary tcj-fetch-refs ml-1" data-id="${row._id}"
						        title="Fetch open references">
							<i class="fa fa-search"></i>
						</button>` : ""}
					</div>
				</td>
				<td>
					<input type="number" class="form-control form-control-sm tcj-amount text-right" data-id="${row._id}"
					       value="${row.amount || 0}" min="0" step="0.01"
					       ${readOnly ? "readonly" : ""} style="text-align:right;" />
				</td>
				<td>
					<input type="text" class="form-control form-control-sm tcj-narration" data-id="${row._id}"
					       value="${frappe.utils.escape_html(row.narration || "")}"
					       placeholder="Narration..." ${readOnly ? "readonly" : ""} />
				</td>
				<td class="text-center">${statusCell}</td>
				<td>${deleteBtn}</td>
			</tr>
		`;
	}

	// ── Grid Event Delegation ─────────────────────────────────────────────────

	_bindGridEvents() {
		const tbody = $("#tcj-tbody");

		tbody.off("change.tcj input.tcj blur.tcj click.tcj");

		tbody.on("change.tcj", ".tcj-direction", (e) => {
			const id = parseInt($(e.target).data("id"));
			const row = this._getRow(id);
			if (row) {
				row.direction = $(e.target).val();
				this._updateKPIs();
				this._updateBadgeCounts();
			}
		});

		tbody.on("change.tcj", ".tcj-category", (e) => {
			const id = parseInt($(e.target).data("id"));
			const row = this._getRow(id);
			if (row) {
				row.transaction_category = $(e.target).val();
				row.reference_doctype = this._inferRefDoctype(row);
			}
		});

		tbody.on("change.tcj", ".tcj-party-type", (e) => {
			const id = parseInt($(e.target).data("id"));
			const row = this._getRow(id);
			if (row) {
				row.party_type = $(e.target).val();
				row.party = "";
				row.reference_name = "";
				row.reference_doctype = this._inferRefDoctype(row);
				this._renderGrid();
			}
		});

		tbody.on("blur.tcj", ".tcj-party", (e) => {
			const id = parseInt($(e.target).data("id"));
			const row = this._getRow(id);
			if (row) {
				row.party = $(e.target).val().trim();
				this._renderGrid();
			}
		});

		tbody.on("focus.tcj", ".tcj-party", (e) => {
			const id = parseInt($(e.target).data("id"));
			const row = this._getRow(id);
			if (!row || !row.party_type) return;

			const doctypeMap = {
				"Customer": "Customer",
				"Supplier": "Supplier",
				"Custodian": "Custodian",
				"Bank Account": "Bank Account",
			};
			const targetDoctype = doctypeMap[row.party_type];
			if (!targetDoctype) return;

			const $input = $(e.target);

			$input.off("input.tcj-autocomplete").on("input.tcj-autocomplete", function () {
				const txt = $(this).val();
				if (txt.length < 1) return;
				frappe.call({
					method: "frappe.desk.search.search_link",
					args: {
						doctype: targetDoctype,
						txt: txt,
						query: "",
						page_length: 10,
					},
					callback: (r) => {
						if (!r.results || r.results.length === 0) return;
						$input.next(".tcj-autocomplete-dropdown").remove();
						const $dd = $(`<ul class="tcj-autocomplete-dropdown list-group" style="
							position:absolute; z-index:9999; min-width:200px;
							max-height:200px; overflow-y:auto;
							background:#fff; border:1px solid #ccc; border-radius:4px;
							box-shadow:0 2px 8px rgba(0,0,0,.15);"></ul>`);
						r.results.forEach((res) => {
							$dd.append(
								$(`<li class="list-group-item list-group-item-action py-1 px-2" style="cursor:pointer;">${res.value}</li>`)
								.on("mousedown", () => {
									$input.val(res.value);
									row.party = res.value;
									$dd.remove();
									setTimeout(() => this._renderGrid(), 50);
								}.bind(this))
							);
						});
						$input.after($dd);
					},
				});
			}.bind(this));

			$input.off("blur.tcj-autocomplete").on("blur.tcj-autocomplete", function () {
				setTimeout(() => $input.next(".tcj-autocomplete-dropdown").remove(), 200);
			});
		});

		tbody.on("input.tcj", ".tcj-amount", (e) => {
			const id = parseInt($(e.target).data("id"));
			const row = this._getRow(id);
			if (row) {
				row.amount = parseFloat($(e.target).val()) || 0;
				this._updateKPIs();
				this._calcDenomTotal();
			}
		});

		tbody.on("blur.tcj", ".tcj-narration", (e) => {
			const id = parseInt($(e.target).data("id"));
			const row = this._getRow(id);
			if (row) row.narration = $(e.target).val();
		});

		tbody.on("blur.tcj", ".tcj-ref-name", (e) => {
			const id = parseInt($(e.target).data("id"));
			const row = this._getRow(id);
			if (row) row.reference_name = $(e.target).val();
		});

		tbody.on("click.tcj", ".tcj-fetch-refs", (e) => {
			const id = parseInt($(e.target).closest("button").data("id"));
			this._fetchReferences(id);
		});

		tbody.on("click.tcj", ".tcj-delete-row", (e) => {
			const id = parseInt($(e.target).closest("button").data("id"));
			this._deleteRow(id);
		});
	}

	_inferRefDoctype(row) {
		if (row.direction === "Inbound" && row.transaction_category === "Invoice Payment") {
			return "Sales Invoice";
		}
		if (row.direction === "Outbound" && row.transaction_category === "Invoice Payment") {
			return "Purchase Invoice";
		}
		if (row.transaction_category === "Advance Allocation") {
			return "Custody Request";
		}
		if (row.transaction_category === "Direct Expense" && row.party_type === "Custodian") {
			return "Accountant Custody";
		}
		return "";
	}

	_fetchReferences(rowId) {
		const row = this._getRow(rowId);
		if (!row || !row.party_type || !row.party) return;

		const refDoctype = this._inferRefDoctype(row);
		if (!refDoctype) {
			frappe.msgprint(__("Cannot determine reference document type for this row."));
			return;
		}
		row.reference_doctype = refDoctype;

		frappe.call({
			method: "cash_and_securities_management.treasury.page.treasury_cash_journal_cockpit.treasury_cash_journal_cockpit_api.get_open_references",
			args: {
				party_type: row.party_type,
				party: row.party,
				reference_doctype: refDoctype,
			},
			callback: (r) => {
				if (!r.message || r.message.length === 0) {
					frappe.msgprint(__("No open {0} found for {1}.").replace("{0}", refDoctype).replace("{1}", row.party));
					return;
				}
				const fields = r.message.map((ref) => ({
					label: `${ref.name} — Outstanding: ${frappe.utils.format_number(ref.outstanding_amount, null, 2)}`,
					value: ref.name,
					amount: ref.outstanding_amount,
				}));

				const d = new frappe.ui.Dialog({
					title: __("Select {0}").replace("{0}", refDoctype),
					fields: [
						{
							fieldtype: "HTML",
							fieldname: "ref_list",
							options: `<div class="tcj-ref-list">
								${fields.map((f) => `
									<div class="tcj-ref-item d-flex justify-content-between align-items-center p-2 mb-1"
									     style="border:1px solid #dee2e6; border-radius:4px; cursor:pointer;"
									     data-name="${f.value}" data-amount="${f.amount}">
										<span>${f.label}</span>
										<button class="btn btn-xs btn-primary tcj-pick-ref">Select</button>
									</div>
								`).join("")}
							</div>`,
						},
					],
				});

				d.show();

				d.$wrapper.on("click", ".tcj-pick-ref", (e) => {
					const item = $(e.target).closest(".tcj-ref-item");
					row.reference_name = item.data("name");
					row.amount = parseFloat(item.data("amount")) || row.amount;
					d.hide();
					this._renderGrid();
					this._updateKPIs();
				});
			},
		});
	}

	// ── KPI Update ────────────────────────────────────────────────────────────

	_sumInflows() {
		return this.rows
			.filter((r) => r.direction === "Inbound")
			.reduce((s, r) => s + (parseFloat(r.amount) || 0), 0);
	}

	_sumOutflows() {
		return this.rows
			.filter((r) => r.direction === "Outbound" || r.direction === "Bank Transfer")
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

	_updateStatusBadge() {
		const badge = $("#tcj-status-badge");
		badge.removeClass("badge-secondary badge-success badge-warning");
		if (this.posted) {
			badge.addClass("badge-success").text("Posted");
			$("#tcj-save-btn, #tcj-add-row-btn").prop("disabled", true);
		} else {
			badge.addClass("badge-secondary").text("Draft");
			$("#tcj-save-btn, #tcj-add-row-btn").prop("disabled", false);
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
			__("Post journal <strong>{0}</strong>? This will create Payment Entries for all unposted rows and cannot be undone.").replace("{0}", this.journalName),
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
			freeze_message: __("Posting journal — creating Payment Entries..."),
			callback: (r) => {
				if (!r.message) return;
				const result = r.message;

				result.lines.forEach((l) => {
					const row = this.rows.find((r) => r._id == l.idx - 1 || r.idx == l.idx);
					if (row) {
						row.is_posted = l.is_posted;
						row.linked_document = l.linked_document;
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

	_getRow(id) {
		return this.rows.find((r) => r._id === id);
	}
}
