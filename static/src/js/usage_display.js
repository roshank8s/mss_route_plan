// /** @odoo-module **/

// import { ListRenderer } from "@web/views/list/list_renderer";
// import { registry } from "@web/core/registry";
// import { onMounted } from "@odoo/owl";

// class CustomListRenderer extends ListRenderer {
//     setup() {
//         super.setup();
//         onMounted(() => {
//             this.injectBanner();
//         });
//     }

//     injectBanner() {
//         const breadcrumb = document.querySelector('.o_breadcrumb');
//         if (breadcrumb) {
//             const banner = document.createElement('div');
//             banner.className = "alert alert-info text-center mb-2";
//             banner.innerText = "🚀 Banner Added to List View!";
//             breadcrumb.parentNode.insertBefore(banner, breadcrumb);
//         }
//     }
// }

// registry.category("views").patch("list", {
//     Renderer: CustomListRenderer,
// });
