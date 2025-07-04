/** @odoo-module **/

import { registry } from '@web/core/registry';
import { ListRenderer } from '@web/views/list/list_renderer';
import { listView } from '@web/views/list/list_view';

class ListRendererNoSelectors extends ListRenderer {
    setup() {
        super.setup();
        this.props.allowSelectors = false;
    }
}

registry.category('views').add('no_selector_tree', {
    ...listView,
    Renderer: ListRendererNoSelectors,
});
