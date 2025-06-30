// File: address_multiple_markers_gmap.js
import { Component, useRef, onWillStart, onMounted, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";

export class AddressMultipleMarkersGmap extends Component {
    static template = "web.AddressMultipleMarkersGmap";
    static props = {
        readonly: Boolean,
        id: Number,
        name: String,
        record: Object,
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this._gmapApiKey = false;
        this.mapref = useRef("googleMap");
        this.recordList = useRef("recordList");
        
        // --- State for filters and storing data ---
        this.filters = useState({ driver: "", date: "" });
        this.allRecords = [];
        this.allVehicleData = [];
        this.mapElements = []; 
        this.availableDrivers = useState([]); // NEW: State to hold the list of drivers for the dropdown
        this.openInfoWindow = null;

        onWillStart(async () => {
            const key = await this._getGMapAPIKey();
            if (!key) {
                this.notification.add(
                    _t("Google Map API Key not configured. Please setup in Settings."),
                    { title: _t("API Key Missing"), type: "danger", sticky: true }
                );
            }
            await loadJS(
                `https://maps.googleapis.com/maps/api/js?key=${key}&libraries=places,maps,directions async`
            );
        });

        onMounted(async () => {
            // 1) Initialize map
            this.map = new google.maps.Map(this.mapref.el, {
                center: { lat: 0, lng: 0 },
                zoom: 2,
            });
            
            // 2) Fetch all data once
            try {
                const [records, vehicleData] = await Promise.all([
                    this.orm.call("traktop", "search_read", [
                        [],
                        [
                            "id", "partner_latitude", "partner_longitude", "display_name", 
                            "delivery_address", "driver_name", "vehicle_id", "route_sequence", 
                            "step_type", "delivery_date",
                        ],
                    ]),
                    this.orm.call("traktop", "fetch_vehicle_data", []),
                ]);
                this.allRecords = records;
                this.allVehicleData = vehicleData;

                // NEW: Populate the unique list of drivers for the dropdown
                const driverNames = new Set(
                    this.allRecords.map(r => r.driver_name).filter(Boolean)
                );
                this.availableDrivers.splice(0, this.availableDrivers.length, ...Array.from(driverNames).sort());

            } catch (err) {
                console.error("Error fetching initial data:", err);
                this.notification.add(_t("Failed to load route data."), { type: "danger" });
                return;
            }

            // 3) Render UI elements and initial map
            this._renderControls();
            this._processAndRenderData();
            
            this._setupLiveLocationUpdates();
            this._setupMobileToggle();
        });
    }
    addMarker(position, title, address, label = null, icon = null, markerPositions = {}) {
        console.log("Adding marker at position:", position, "with title:", title);
        // Offset overlapping markers if positions object is provided
        if (Object.keys(markerPositions).length > 0) {
            const key = `${position.lat.toFixed(6)},${position.lng.toFixed(6)}`;
            if (markerPositions[key] === undefined) {
                markerPositions[key] = 0;
            } else {
                markerPositions[key]++;
                position = { lat: position.lat + (markerPositions[key] * 0.0001), lng: position.lng + (markerPositions[key] * 0.0001) };
            }
        }

        const m = new google.maps.Marker({
            position, map: this.map, title, icon,
            label: label ? { text: label, color: "white", fontSize: "12px", fontWeight: "bold" } : null
        });

        const iw = new google.maps.InfoWindow({ content: `<div><strong>${title || ""}</strong><br/>${address || ""}</div>` });

        // The single, centralized "close-then-open" logic
        m.addListener("click", () => {
            if (this.openInfoWindow) {
                this.openInfoWindow.close();
            }
            iw.open(this.map, m);
            this.openInfoWindow = iw;
        });

        m.infoWindow = iw;
        this.mapElements.push(m);
        return m;
    }


    _renderControls() {
        const controlPanel = document.querySelector(".o_control_panel");
        if (!controlPanel) return;

        this.orm.call("mss_route_plan.user.registration", "search_read", [[]], { fields: ["usage_display"], limit: 1 }).then(result => {
            const usageDisplay = result.length ? result[0].usage_display : "N/A";
            if (!document.querySelector(".custom-usage-banner")) {
                const banner = document.createElement("div");
                banner.className = "custom-usage-banner";
                banner.innerText = `Usage Info: you have used ${usageDisplay} optimization credits this month.`;
                controlPanel.insertAdjacentElement("afterend", banner);
                this._createSearchBar(banner);
            }
        });
    }

    /**
     * UPDATED: Creates and injects the search bar with a driver dropdown.
     */
    _createSearchBar(anchorElement) {
        const searchContainer = document.createElement("div");
        searchContainer.className = "o_map_search_bar d-flex align-items-center gap-2 p-2 bg-light border-bottom";

        // --- Driver Dropdown ---
        const driverSelect = document.createElement("select");
        driverSelect.className = "form-select form-select-sm";
        
        // Add a default "All Drivers" option
        const allDriversOption = document.createElement("option");
        allDriversOption.value = "";
        allDriversOption.textContent = _t("All Drivers");
        driverSelect.appendChild(allDriversOption);

        // Populate with available drivers
        this.availableDrivers.forEach(driverName => {
            const option = document.createElement("option");
            option.value = driverName;
            option.textContent = driverName;
            driverSelect.appendChild(option);
        });
        
        // Event listener: update filter state and re-render immediately on change
        driverSelect.addEventListener("change", (e) => {
            this.filters.driver = e.target.value;
            this._processAndRenderData(); // Filter right away
        });

        // --- Date filter ---
        const dateInput = document.createElement("input");
        dateInput.type = "date";
        dateInput.className = "form-control form-control-sm";
        dateInput.placeholder = "Filter by date..."; 
        dateInput.addEventListener("input", (e) => this.filters.date = e.target.value);

        // --- Filter button (useful for applying the date filter) ---
        const filterButton = document.createElement("button");
        filterButton.textContent = _t("Filter by Date");
        filterButton.className = "btn btn-secondary btn-sm";
        filterButton.addEventListener("click", () => this._processAndRenderData());

        // --- Clear button ---
        const clearButton = document.createElement("button");
        clearButton.textContent = _t("Clear All");
        clearButton.className = "btn btn-light btn-sm border";
        clearButton.addEventListener("click", () => {
            // Reset UI elements
            driverSelect.value = "";
            dateInput.value = "";
            // Reset state
            this.filters.driver = "";
            this.filters.date = "";
            // Re-render with no filters
            this._processAndRenderData();
        });
        
        searchContainer.append(driverSelect, dateInput, filterButton, clearButton);
        anchorElement.insertAdjacentElement("afterend", searchContainer);
    }
    
    _clearMapAndList() {
        this.recordList.el.innerHTML = "";
        this.mapElements.forEach(element => element.setMap(null));
        this.mapElements = [];
    }

    /**
     * UPDATED: Main logic with updated filtering for exact driver match.
     */
    async _processAndRenderData() {
        this._clearMapAndList();

        try {
            // UPDATED: Filter records based on state (exact match for driver)
            const driverFilter = this.filters.driver;
            const dateFilter = this.filters.date;

            const filteredRecords = this.allRecords.filter(r => {
                const driverMatch = !driverFilter || r.driver_name === driverFilter;
                const dateMatch = !dateFilter || (r.delivery_date && r.delivery_date.startsWith(dateFilter));
                return driverMatch && dateMatch;
            });

            // Group filtered steps by vehicle_id
            const byVehicle = {};
            for (const r of filteredRecords) {
                if (!r.vehicle_id || !r.vehicle_id[0]) continue;
                const vid = r.vehicle_id[0];
                if (!byVehicle[vid]) {
                    const plate = r.vehicle_id[1] || "";
                    const label = [r.driver_name, plate].filter(Boolean).join(" / ");
                    byVehicle[vid] = { label, recs: [] };
                }
                byVehicle[vid].recs.push(r);
            }

            // --- Render Optimization Button for Admin ---
            const isAdmin = await this.orm.call("traktop", "is_admin", []);
            if (isAdmin) {
                const optimizationBtn = document.createElement("button");
                optimizationBtn.textContent = "Optimization";
                optimizationBtn.className = "btn btn-primary btn-sm o_map_btn";
                Object.assign(optimizationBtn.style, {
                    marginBottom: "5px",
                    fontSize: "15px",
                });
                optimizationBtn.addEventListener("click", async () => {
                     try {
                        const response = await this.orm.call("traktop", "get_optimized_rec_created", []);
                        if (response && response.params) {
                            this.notification.add(response.params.message, { title: response.params.title, type: response.params.type, sticky: response.params.sticky });
                            if (response.params.next && response.params.next.tag === 'reload') location.reload();
                        } else if (response && response.type === "ir.actions.act_window") {
                            this.env.services.action.doAction(response);
                        }
                    } catch (error) {
                        console.error("Error during optimization:", error);
                        this.notification.add(_t("Optimization failed."), { title: _t("Error"), type: "danger" });
                    }
                });
                this.recordList.el.appendChild(optimizationBtn);
            }
            
            this._renderVehicleRoutes(byVehicle, isAdmin);

        } catch (err) {
            console.error("Error rendering route data:", err);
            this.notification.add(_t("Failed to render route data."), { type: "danger" });
        }
    }
    

    _renderVehicleRoutes(byVehicle, isAdmin) {
        const icons = {
            start: { url: "/mss_route_plan/static/description/startEnd.svg", scaledSize: new google.maps.Size(40, 40) },
            job: { url: "/mss_route_plan/static/description/pinpoint.svg", scaledSize: new google.maps.Size(30, 30) },
            end: { url: "/mss_route_plan/static/description/startEnd.svg", scaledSize: new google.maps.Size(40, 40) },
        };
        let _lastHue = Math.random() * 360;
        const getRandomColor = () => {
            _lastHue = (_lastHue + 137.508) % 360;
            return `hsl(${Math.round(_lastHue * 10) / 10}, 65%, 50%)`;
        };
        const markerPositions = {};
        
        for (const [vid, { label: vehLabel, recs }] of Object.entries(byVehicle)) {
            recs.sort((a, b) => a.route_sequence - b.route_sequence);
            const jobs = recs.filter(r => r.step_type === "job");
            if (!jobs.length) continue;

            const bounds = new google.maps.LatLngBounds();
            const color = getRandomColor();
            
            const hdr = document.createElement("li");
            hdr.textContent = vehLabel;
            Object.assign(hdr.style, { fontWeight: "bold", color, cursor: "pointer", margin: "10px 0 5px", listStyle: "none" });
            const arrow = document.createElement("span");
            arrow.textContent = " ▼";
            hdr.appendChild(arrow);
            const detailUl = document.createElement("ul");
            Object.assign(detailUl.style, { listStyle: "none", paddingLeft: "15px", display: "block" }); // Default to open
            hdr.addEventListener("click", () => {
                const show = detailUl.style.display === "none";
                detailUl.style.display = show ? "block" : "none";
                arrow.textContent = show ? " ▲" : " ▼";
                this.map.fitBounds(bounds);
            });
            if (Object.keys(byVehicle).length === 1) { // If only one driver is shown, auto-focus
                 setTimeout(() => this.map.fitBounds(bounds), 100);
            }

            const startRec = recs.find(r => r.step_type === "start");
            const endRec = recs.find(r => r.step_type === "end");
            let startPt, endPt;
            if (startRec && endRec) {
                startPt = { lat: +startRec.partner_latitude, lng: +startRec.partner_longitude };
                endPt = { lat: +endRec.partner_latitude, lng: +endRec.partner_longitude };
            } else {
                const vinfo = this.allVehicleData.find(v => v.id === +vid);
                if (vinfo) {
                    startPt = { lat: vinfo.start[1], lng: vinfo.start[0] };
                    endPt = { lat: vinfo.end[1], lng: vinfo.end[0] };
                }
            }

            if (!isAdmin) {
                const gmapsBtn = document.createElement("button");
                gmapsBtn.textContent = "View in Google Maps";
                gmapsBtn.className = "btn btn-primary btn-sm o_map_btn m-2";
                gmapsBtn.addEventListener("click", () => {
                    const points = [];
                    if (startPt) points.push(`${startPt.lat},${startPt.lng}`);
                    jobs.forEach(job => points.push(`${+job.partner_latitude},${+job.partner_longitude}`));
                    if (endPt) points.push(`${endPt.lat},${endPt.lng}`);
                    if (points.length >= 2) {
                        const origin = points[0];
                        const destination = points.pop();
                        const waypoints = points.slice(1).join("|");
                        window.open(`https://www.google.com/maps/dir/?api=1&origin=${origin}&destination=${destination}&waypoints=${encodeURIComponent(waypoints)}`, "_blank");
                    }
                });
                this.recordList.el.appendChild(gmapsBtn);
            }
            this.recordList.el.appendChild(hdr);
            this.recordList.el.appendChild(detailUl);

            if (startPt) { bounds.extend(startPt); this.addMarker(startPt, `Start ${vehLabel}`, "", null, icons.start, markerPositions); }
            if (endPt) { bounds.extend(endPt); this.addMarker(endPt, `End ${vehLabel}`, "", null, icons.end, markerPositions); }
            
            jobs.forEach((job, index) => {
                const pos = { lat: +job.partner_latitude, lng: +job.partner_longitude };
                bounds.extend(pos);
                const marker = this.addMarker(pos, job.display_name, job.delivery_address, String(index + 1), icons.job, markerPositions);
                const li = document.createElement("li");
                li.style.cursor = "pointer";
                li.innerHTML = `<div><a href="/web#id=${job.id}&model=sale.order&view_type=form" target="_blank" style="font-weight: bold;">${job.display_name}</a></div><div style="font-size: small; color: #666;">${job.delivery_address}</div>`;
                li.addEventListener("click", () => {
                    this.map.panTo(pos);
                    this.map.setZoom(15);
                    new google.maps.event.trigger(marker, 'click');
                });
                detailUl.appendChild(li);
            });

            if (startPt && endPt) {
                const ds = new google.maps.DirectionsService();
                const dr = new google.maps.DirectionsRenderer({ map: this.map, suppressMarkers: true, polylineOptions: { strokeColor: color, strokeOpacity: 0.8, strokeWeight: 4 } });
                this.mapElements.push(dr);
                ds.route({
                    origin: startPt,
                    destination: endPt,
                    waypoints: jobs.map(j => ({ location: { lat: +j.partner_latitude, lng: +j.partner_longitude }, stopover: true })),
                    travelMode: google.maps.TravelMode.DRIVING,
                }, (res, status) => {
                    if (status === google.maps.DirectionsStatus.OK) dr.setDirections(res);
                });
            }
        }
    }

    _setupLiveLocationUpdates() {
        let userLiveMarkers = {};
        const liveIcon = {
            url: "/mss_route_plan/static/src/img/box-truck.png",
            scaledSize: new google.maps.Size(40, 40),
            anchor: new google.maps.Point(20, 20),
        };

        const updateLive = async () => {
            try {
                const parts = await this.orm.call("res.partner", "search_read", [ [], ["live_latitude", "live_longitude", "name", "id"] ]);
                parts
                    .filter(p => !isNaN(parseFloat(p.live_latitude)) && !isNaN(parseFloat(p.live_longitude)) && +p.live_latitude !== 0 && +p.live_longitude !== 0)
                    .forEach(p => {
                        const pos = { lat: +p.live_latitude, lng: +p.live_longitude };
                        if (userLiveMarkers[p.id]) {
                            userLiveMarkers[p.id].setPosition(pos);
                        } else {
                            // FIXED: This now correctly calls the shared component method
                            userLiveMarkers[p.id] = this.addMarker(
                                pos,
                                p.name,
                                _t("Live Location"),
                                null,
                                liveIcon
                            );
                        }
                    });
            } catch (e) {
                console.error("Live location update error:", e);
            }
        };
        updateLive();
        setInterval(updateLive, 5000);
    }

    _setupMobileToggle() {
        // This function is unchanged
        if (window.innerWidth > 768) return;
        const mapLeftView = this.recordList.el.parentElement;
        const toggleBtn = document.createElement("div");
        toggleBtn.className = "map-toggle-btn-pure";
        this.mapref.el.parentElement.insertBefore(toggleBtn, this.mapref.el);
        let isOpen = false;
        const togglePanel = (show) => {
            isOpen = show;
            mapLeftView.classList.toggle("map-panel-visible", isOpen);
            toggleBtn.classList.toggle("flipped", isOpen);
            toggleBtn.style.left = isOpen ? "calc(70% - 16px)" : "15px";
        };
        toggleBtn.addEventListener("click", (e) => { e.stopPropagation(); togglePanel(!isOpen); });
        document.addEventListener("click", (e) => {
            if (isOpen && !mapLeftView.contains(e.target) && e.target !== toggleBtn) togglePanel(false);
        });
    }

    async _getGMapAPIKey() {
        if (!this._gmapApiKey) {
            this._gmapApiKey = await this.orm.call("traktop", "get_google_map_api_key", []);
        }
        return this._gmapApiKey;
    }
}

export const addressMultipleMarkersGmap = {
    component: AddressMultipleMarkersGmap,
};
registry.category("fields").add(
    "address_multiple_markers_gmap",
    addressMultipleMarkersGmap
);
