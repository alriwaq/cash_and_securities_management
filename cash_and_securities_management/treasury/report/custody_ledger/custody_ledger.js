// Copyright (c) 2024, Cash and Securities Management
// Custody Ledger Report — filters

frappe.query_reports["Custody Ledger"] = {
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
			fieldname: "show_zero_balance",
			label: __("Show Zero Balance"),
			fieldtype: "Check",
			default: 0,
		},
	],

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && data.bold) {
			value = `<strong>${value}</strong>`;
		}
		// Colour the balance column: red if positive (outstanding advance), green if zero/negative
		if (column.fieldname === "balance" && data) {
			const num = flt(data.balance);
			if (num > 0.01) {
				value = `<span style="color:var(--red-600)">${value}</span>`;
			} else if (Math.abs(num) < 0.01) {
				value = `<span style="color:var(--green-600)">${value}</span>`;
			}
		}
		return value;
	},
};
