// Copyright (c) 2024, Cash and Securities Management
// Custodian Balance Summary Report — filters

frappe.query_reports["Custodian Balance Summary"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			reqd: 1,
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "custodian",
			label: __("Custodian"),
			fieldtype: "Link",
			options: "Custodian",
			get_query: function () {
				return {
					filters: {
						company: frappe.query_report.get_filter_value("company"),
					},
				};
			},
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: "\nActive\nSuspended\nClosed",
		},
	],

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (!data) return value;

		// Closing balance — red if positive (outstanding), green if zero
		if (column.fieldname === "closing_balance") {
			const num = flt(data.closing_balance);
			if (num > 0.01) {
				value = `<span style="color:var(--red-600);font-weight:600">${value}</span>`;
			} else if (Math.abs(num) < 0.01) {
				value = `<span style="color:var(--green-600);font-weight:600">${value}</span>`;
			}
		}

		// Available limit — red if negative (over limit)
		if (column.fieldname === "available_limit") {
			const num = flt(data.available_limit);
			if (num < 0) {
				value = `<span style="color:var(--red-600)">${value}</span>`;
			}
		}

		// Status badge
		if (column.fieldname === "status" && data.status) {
			const colour = {
				"Active":    "green",
				"Suspended": "orange",
				"Closed":    "gray",
			}[data.status] || "gray";
			value = `<span class="indicator-pill ${colour}">${data.status}</span>`;
		}

		// Open ACs — highlight if > 0
		if (column.fieldname === "open_acs" && flt(data.open_acs) > 0) {
			value = `<span style="color:var(--orange-600);font-weight:600">${value}</span>`;
		}

		return value;
	},
};
