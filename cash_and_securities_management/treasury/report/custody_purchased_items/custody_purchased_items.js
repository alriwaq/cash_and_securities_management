// Copyright (c) 2024, Cash and Securities Management
// Custody Purchased Items Report — filters

frappe.query_reports["Custody Purchased Items"] = {
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
			fieldname: "department",
			label: __("Department"),
			fieldtype: "Link",
			options: "Department",
		},
		{
			fieldname: "supplier",
			label: __("Supplier"),
			fieldtype: "Link",
			options: "Supplier",
		},
		{
			fieldname: "accountant_custody",
			label: __("Accountant Custody"),
			fieldtype: "Link",
			options: "Accountant Custody",
			get_query: function () {
				const custodian = frappe.query_report.get_filter_value("custodian");
				const f = { company: frappe.query_report.get_filter_value("company") };
				if (custodian) f.custodian = custodian;
				return { filters: f };
			},
		},
		{
			fieldname: "item_code",
			label: __("Item"),
			fieldtype: "Link",
			options: "Item",
		},
		{
			fieldname: "item_group",
			label: __("Item Group"),
			fieldtype: "Link",
			options: "Item Group",
		},
		{
			fieldname: "asset_category",
			label: __("Asset Category"),
			fieldtype: "Link",
			options: "Asset Category",
		},
		{
			fieldname: "status",
			label: __("AC Status"),
			fieldtype: "Select",
			options: [
				"",
				"Draft",
				"Pending",
				"Partly Received",
				"Fully Received",
				"Partly Invoiced",
				"Fully Invoiced",
				"Closed",
			].join("\n"),
		},
	],

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (column.fieldname === "status" && data) {
			const colour = {
				"Fully Billed":    "green",
				"Partly Billed":   "orange",
				"Fully Received":  "blue",
				"Partly Received": "lightblue",
				"Pending":         "red",
			}[data.status];
			if (colour) {
				value = `<span class="indicator-pill ${colour}">${data.status}</span>`;
			}
		}

		if (column.fieldname === "ac_status" && data) {
			const colour = {
				"Fully Invoiced":  "green",
				"Partly Invoiced": "orange",
				"Fully Received":  "blue",
				"Partly Received": "lightblue",
				"Pending":         "yellow",
				"Draft":           "gray",
				"Closed":          "gray",
			}[data.ac_status];
			if (colour) {
				value = `<span class="indicator-pill ${colour}">${data.ac_status}</span>`;
			}
		}

		if (column.fieldname === "pending_amount" && data && flt(data.pending_amount) > 0) {
			value = `<span style="color:var(--red-500)">${value}</span>`;
		}

		return value;
	},
};
