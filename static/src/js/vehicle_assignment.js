/** @odoo-module **/
import { Component, useRef, useState, onWillStart, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { pivotView } from "@web/views/pivot/pivot_view";

export class VehicleAssignment extends Component {
    static template = "mss_route_plan.VehicleAssignment";

    setup() {
        this.orm = useService("orm");
        this.viewService = useService("view");
        this.notification = useService("notification");
        this.pivotRef = useRef("pivotContainer");
        this.listRef = useRef("listContainer");
        this.state = useState({ vehicleId: null });

        onWillStart(async () => {
            const views = await this.viewService.loadViews({
                resModel: "fleet.vehicle",
                views: [[false, "pivot"]],
            });
            this.pivotArch = views.views.pivot.arch;
            this.pivotFields = views.views.pivot.fields;
        });

        onMounted(async () => {
            await this._renderPivot();
            await this._loadList();
        });
    }

    _todayWeekday() {
        return new Date().toLocaleDateString("en-US", { weekday: "long" }).toLowerCase();
    }

    async _renderPivot() {
        const { Model, Renderer, Controller } = pivotView;
        this.pivotModel = new Model(this.env, {
            resModel: "fleet.vehicle",
            domain: [["delivery_days.name", "=", this._todayWeekday()]],
            context: {},
            fields: this.pivotFields,
            arch: this.pivotArch,
        });
        await this.pivotModel.load();
        const renderer = new Renderer(this.env, { model: this.pivotModel });
        this.pivotController = new Controller(this.env, { model: this.pivotModel, renderer });
        this.pivotController.mount(this.pivotRef.el);
        this.pivotRef.el.addEventListener("click", (ev) => {
            const cell = ev.target.closest("th[data-row-id]");
            if (cell) {
                const vid = parseInt(cell.dataset.rowId, 10);
                if (!isNaN(vid)) {
                    this.state.vehicleId = vid;
                    this._loadList();
                }
            }
        });
    }

    async _loadList() {
        const today = new Date().toISOString().split("T")[0];
        const domain = [
            ["delivery_date", ">=", today + " 00:00:00"],
            ["delivery_date", "<=", today + " 23:59:59"],
            ["vehicle_id", "=", false],
        ];
        const records = await this.orm.searchRead("route.planing", domain, [
            "id",
            "delivery_order_id",
            "delivery_address",
        ]);
        this._renderList(records);
    }

    _renderList(records) {
        const el = this.listRef.el;
        el.innerHTML = "";
        records.forEach((rec) => {
            const li = document.createElement("li");
            li.className = "list-group-item d-flex justify-content-between align-items-center";
            const name = rec.delivery_order_id ? rec.delivery_order_id[1] : rec.id;
            li.innerHTML = `<span>${name} - ${rec.delivery_address || ""}</span>`;
            const btn = document.createElement("button");
            btn.className = "btn btn-primary btn-sm";
            btn.textContent = this.env._t("Assign to This Vehicle");
            btn.addEventListener("click", async () => {
                if (!this.state.vehicleId) {
                    this.notification.add(this.env._t("Select a vehicle first."), { type: "danger" });
                    return;
                }
                await this.orm.call("route.planing", "assign_to_vehicle", [rec.id, this.state.vehicleId]);
                this._loadList();
            });
            li.appendChild(btn);
            el.appendChild(li);
        });
    }
}

registry.category("actions").add("vehicle_assignment", VehicleAssignment);
