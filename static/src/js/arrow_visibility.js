/** @odoo-module **/

import { registry } from "@web/core/registry";
import { ListRenderer } from "@web/views/list/list_renderer";
import { useEffect } from "@odoo/owl";

export class GroupSortableListRenderer extends ListRenderer {

    setup() {
        super.setup();
        this.updateGrouped();

        // Dynamically watch changes to grouping
        useEffect(() => {
            this.updateGrouped();
        }, () => [this.props.list.groupBy]);
    }

    updateGrouped() {
        const groupBy = this.props.list.groupBy;
        console.log("Group by (live)", groupBy);
        this.isGrouped = groupBy && groupBy.length > 0;
    
        // Instead of full re-render, update the move_up/move_down buttons visibility
        document.querySelectorAll('button[name="move_up"], button[name="move_down"]').forEach((button) => {
            if (this.isGrouped) {
                button.style.display = "";
            } else {
                button.style.display = "none";
            }
        });
    }
}

registry.category("views").add("group_sortable_list", {
    ...registry.category("views").get("list"),
    Renderer: GroupSortableListRenderer,
});
