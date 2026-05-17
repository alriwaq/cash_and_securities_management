frappe.pages["treasury-cash-journal"].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Treasury Cash Journal",
		single_column: true,
	});

	// Render the HTML template into the page body
	$(wrapper).find(".page-content").html(frappe.render_template("treasury_cash_journal"));

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
		this.rows = [];           // in-memory row array
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
			method: "cash_and_securities_management.treasury.page.treasury_cash_journal.treasury_cash_journal_api.get_station_list",
			callback: (r) => {
				if (!r.message) return;
				const sel = $("#tcj-station-select");
				r.message.forEach((s) => {
					sel.append(`<option value="${s.name}">${s.station_name}</option>`);
				});
				// Auto-select if only one station
				if (r.message.length === 1) {
					sel.val(r.message[0].name);
					this._loadJournal();
				}
			},
		});
	}

	_bindEvents() {
		// Station / date change → reload journal
		$("#tcj-station-select").on("change", () => this._loadJournal());
		$("#tcj-date-input").on("change", () => this._loadJournal());

		// Tab filter
		$("#tcj-tabs .nav-link").on("click", (e) => {
			e.preventDefault();
			$("#tcj-tabs .nav-link").removeClass("active");
			$(e.currentTarget).addClass("active");
			this.activeFilter = $(e.currentTarget).data("filter");
			this._renderGrid();
		});

		// Add row
		$("#tcj-add-row-btn").on("click", () => this._addRow());

		// Save draft
		$("#tcj-save-btn").on("click", () => this._saveDraft());

		// Post journal
		$("#tcj-post-btn").on("click", () => this._confirmPost());

		// Denomination drawer toggle
		$("#tcj-denomination-toggle").on("click", () => {
			const body = $("#tcj-denomination-body");
			const chevron = $("#tcj-denom-chevron");
			body.slideToggle(200);
			chevron.toggleClass("fa-chevron-down fa-chevron-up");
		});
	}

	_initDenomTable() {
		// Standard denominations (SAR — adjust per company currency as needed)
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

		// Live calculation
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
			method: "cash_and_securities_management.treasury.page.treasury_cash_journal.treasury_cash_journal_api.get_station_data",
			args: { station, posting_date: date },
			callback: (r) => {
				if (!r.message) return;
				const data = r.message;
				this.stationData = data.station;
				this.openingBalance = data.opening_balance || 0;
				this.journalName = data.journal_name || null;
				this.posted = data.existing && data.existing.posting_status === "Posted";

				// Populate rows from existing journal
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
		// Focus the direction cell of the new row
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

		this._updateBadgeCounts();
		this._updateRowCount();
	}

	_renderRow(row, idx) {
		const posted = row.is_posted;
		const readOnly = posted || this.posted;
		const rowClass = posted ? "table-success" : (row.direction === "Inbound" ? "tcj-row-inbound" : row.direction === "Outbound" ? "tcj-row-outbound" : "");

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

		// Direction change
		tbody.on("change", ".tcj-direction", (e) => {
			const id = parseInt($(e.target).data("id"));
			const row = this._getRow(id);
			if (row) {
				row.direction = $(e.target).val();
				this._updateKPIs();
				this._updateBadgeCounts();
			}
		});

		// Category change
		tbody.on("change", ".tcj-category", (e) => {
			const id = parseInt($(e.target).data("id"));
			const row = this._getRow(id);
			if (row) {
				row.transaction_category = $(e.target).val();
				// Swap reference_doctype based on category
				row.reference_doctype = this._inferRefDoctype(row);
			}
		});

		// Party type change
		tbody.on("change", ".tcj-party-type", (e) => {
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

		// Party input
		tbody.on("blur", ".tcj-party", (e) => {
			const id = parseInt($(e.target).data("id"));
			const row = this._getRow(id);
			if (row) row.party = $(e.target).val();
		});

		// Amount change
		tbody.on("input", ".tcj-amount", (e) => {
			const id = parseInt($(e.target).data("id"));
			const row = this._getRow(id);
			if (row) {
				row.amount = parseFloat($(e.target).val()) || 0;
				this._updateKPIs();
				this._calcDenomTotal();
			}
		});

		// Narration change
		tbody.on("blur", ".tcj-narration", (e) => {
			const id = parseInt($(e.target).data("id"));
			const row = this._getRow(id);
			if (row) row.narration = $(e.target).val();
		});

		// Reference name change
		tbody.on("blur", ".tcj-ref-name", (e) => {
			const id = parseInt($(e.target).data("id"));
			const row = this._getRow(id);
			if (row) row.reference_name = $(e.target).val();
		});

		// Fetch references button
		tbody.on("click", ".tcj-fetch-refs", (e) => {
			const id = parseInt($(e.target).closest("button").data("id"));
			this._fetchReferences(id);
		});

		// Delete row
		tbody.on("click", ".tcj-delete-row", (e) => {
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
			method: "cash_and_securities_management.treasury.page.treasury_cash_journal.treasury_cash_journal_api.get_open_references",
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
				// Show a dialog to pick a reference
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

		// Update denomination expected
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
			method: "cash_and_securities_management.treasury.page.treasury_cash_journal.treasury_cash_journal_api.save_journal_draft",
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
		const actual = actualBalance !== 0
			? expected + actualBalance
			: expected;

		frappe.call({
			method: "cash_and_securities_management.treasury.page.treasury_cash_journal.treasury_cash_journal_api.post_journal",
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

				// Update row posted status from result
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

// Bind grid events after each render (event delegation on tbody)
$(document).on("page-change", function () {
	// Clean up on page change
});

// Override render to also bind events
const _origRenderGrid = TreasuryCashJournal.prototype._renderGrid;
TreasuryCashJournal.prototype._renderGrid = function () {
	_origRenderGrid.call(this);
	this._bindGridEvents();
};
