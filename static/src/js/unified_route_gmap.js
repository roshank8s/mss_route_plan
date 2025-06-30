/** @odoo-module **/
import { Component, useRef, onWillStart, onMounted, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";

export class UnifiedRouteMapView extends Component {
    static template = "mss_route_plan.UnifiedRouteMapView";
    static props = { readonly: Boolean, id: Number, name: String, record: Object };

    setup() {
        this.orm            = useService("orm");
        this.notification   = useService("notification");
        this._gmapApiKey    = false;
        this.mapref         = useRef("googleMap");
        this.recordList     = useRef("recordList");

        // default mode stays "unified"
        this.filters = useState({ driver: "", date: "", mode: "unified" });

        this.unifiedSteps   = [];
        this.deliverySteps  = [];
        this.fsmSteps       = [];
        this.mapElements    = [];
        this.availableDrivers = useState([]);
        this.openInfoWindow   = null;

        onWillStart(async () => {
            const key = await this._getGMapAPIKey();
            if (!key) {
                this.notification.add(
                    _t("Google Map API Key not configured."),
                    { type: "danger", sticky: true }
                );
            }
            await loadJS(
                `https://maps.googleapis.com/maps/api/js?key=${key}&libraries=places,maps,directions,geometry async`
            );
        });

        onMounted(async () => {
            this.map = new google.maps.Map(this.mapref.el, {
                center: { lat: 0, lng: 0 },
                zoom: 2,
            });

            try {
                const [unified, delivery, fsm] = await Promise.all([
                    this.orm.call("route.unified.step", "search_read", [
                        [["step_type","in",["start","job","end"]]],
                        [
                            "id","partner_latitude","partner_longitude",
                            "display_name","driver_name","step_type",
                            "route_sequence","delivery_order_id","task_id","vehicle_id",
                            "delivery_date","planned_date_begin","delivery_address"
                        ]
                    ]),
                    this.orm.call("traktop", "search_read", [
                        [],[
                            "id","partner_latitude","partner_longitude",
                            "display_name","driver_name","step_type",
                            "route_sequence","delivery_order_id","vehicle_id",
                            "delivery_date","travel_time","distance_km","delivery_address"
                        ]
                    ]),
                    this.orm.call("field.service.route.step", "search_read", [
                        [],[
                            "id","partner_latitude","partner_longitude",
                            "display_name","driver_name","step_type",
                            "route_sequence","task_id","vehicle_id",
                            "planned_date_begin","service_duration_minutes",
                            "distance_km","delivery_address"
                        ]
                    ]),
                ]);

                this.unifiedSteps   = unified;
                this.deliverySteps  = delivery.filter(r => ["start","job","end"].includes(r.step_type));
                this.fsmSteps       = fsm.filter(r => ["start","job","end"].includes(r.step_type));

                const allDrivers = new Set([
                    ...unified.map(s => s.driver_name),
                    ...delivery.map(s => s.driver_name),
                    ...fsm.map(s => s.driver_name),
                ].filter(Boolean));
                this.availableDrivers.splice(
                    0,
                    this.availableDrivers.length,
                    ...[...allDrivers].sort()
                );

            } catch (err) {
                console.error("Error fetching route data:", err);
                this.notification.add(
                    _t("Failed to load route data."),
                    { type: "danger" }
                );
                return;
            }

            this._renderControls();
            // ← removed this._renderData() here
            this._setupMobileToggle();
        });
    }

    _renderControls() {
        const cp = document.querySelector(".o_control_panel");
        if (!cp) return;
        const ctr = document.createElement("div");
        ctr.className = "o_map_search_bar d-flex align-items-center gap-2 p-2 bg-light border-bottom";

        // Driver filter
        const dsel = document.createElement("select");
        dsel.className = "form-select form-select-sm";
        dsel.innerHTML = `<option value="">${_t("All Drivers")}</option>`;
        this.availableDrivers.forEach(n => {
            dsel.innerHTML += `<option>${n}</option>`;
        });
        dsel.addEventListener("change", e => {
            this.filters.driver = e.target.value;
            this._renderData();
        });

        // Date filter
        const din = document.createElement("input");
        din.type = "date";
        din.className = "form-control form-control-sm";
        din.addEventListener("input", e => {
            this.filters.date = e.target.value;
            this._renderData();
        });

        // Only two modes: Delivery & Field Service
        const lbl = document.createElement("span");
        lbl.textContent = _t("Show:");
        const grp = document.createElement("div");
        grp.className = "btn-group btn-group-sm";

        const btnD = document.createElement("button");
        btnD.textContent = _t("Delivery Orders");
        const btnF = document.createElement("button");
        btnF.textContent = _t("Field Service");

        const setMode = m => {
            this.filters.mode = m;
            btnD.className = m === "delivery"
                ? "btn btn-primary"
                : "btn btn-outline-primary";
            btnF.className = m === "fsm"
                ? "btn btn-primary"
                : "btn btn-outline-primary";
            this._renderData();
        };
        btnD.onclick = () => setMode("delivery");
        btnF.onclick = () => setMode("fsm");
        grp.append(btnD, btnF);

        // Clear All → back to Unified
        const clr = document.createElement("button");
        clr.textContent = _t("Clear All");
        clr.className = "btn btn-light btn-sm border";
        clr.onclick = () => {
            this.filters.driver = "";
            this.filters.date   = "";
            dsel.value = "";
            din.value = "";
            setMode("unified");  // reset to unified
        };

        ctr.append(dsel, din, lbl, grp, clr);
        cp.insertAdjacentElement("afterend", ctr);

        // initialize the two buttons (unified is default but hidden)
        setMode(this.filters.mode);
    }

    _clearMapAndList() {
        this.recordList.el.innerHTML = "";
        this.mapElements.forEach(el => el.setMap?.(null));
        this.mapElements = [];
    }

    _renderData() {
        this._clearMapAndList();
        const { driver, date, mode } = this.filters;

        // pick the right array:
        let steps = [];
        if (mode === "delivery")   steps = this.deliverySteps;
        else if (mode === "fsm")    steps = this.fsmSteps;
        else                        steps = this.unifiedSteps;

        // find jobs matching driver+date
        const jobs = steps.filter(s => {
            if (s.step_type !== "job") return false;
            const dn = s.driver_name || "";
            const dv = s.delivery_date || s.planned_date_begin || "";
            return (!driver || dn === driver)
                && (!date   || dv.startsWith(date));
        });

        // vehicles that have those jobs
        const vids = [...new Set(jobs.map(j => j.vehicle_id[0]))];

        // now filter all steps for those vids
        const filtered = steps.filter(s =>
            s.vehicle_id
            && vids.includes(s.vehicle_id[0])
            && (!driver || s.driver_name === driver)
        );

        // group by vehicle
        const byV = {};
        for (const s of filtered) {
            const vid = s.vehicle_id[0];
            if (!byV[vid]) {
                const plate = s.vehicle_id[1] || "";
                byV[vid] = {
                    label: [s.driver_name, plate].filter(Boolean).join(" / "),
                    recs: []
                };
            }
            byV[vid].recs.push(s);
        }

        // show the correct Optimize button
        this.orm.call("traktop", "is_admin", []).then(isAdmin => {
            if (isAdmin) {
                let btn = null;
                if (mode === "delivery") {
                    btn = document.createElement("button");
                    btn.textContent = _t("Optimize Delivery");
                    btn.onclick = async () => {
                        try {
                            const action = await this.orm.call(
                                "traktop",
                                "get_optimized_rec_created",
                                []
                            );
                            action && this.env.services.action.doAction(action);
                        } catch (e) {
                            console.error(e);
                            this.notification.add(_t("Delivery optimization failed."), { type: "danger" });
                        }
                    };
                }
                else if (mode === "fsm") {
                    btn = document.createElement("button");
                    btn.textContent = _t("Optimize Field Service");
                    btn.onclick = async () => {
                        try {
                            const action = await this.orm.call(
                                "field.service.route.step",
                                "get_optimized_routes",
                                []
                            );
                            action && this.env.services.action.doAction(action);
                        } catch (e) {
                            console.error(e);
                            this.notification.add(_t("Field Service optimization failed."), { type: "danger" });
                        }
                    };
                }
                else {
                    btn = document.createElement("button");
                    btn.textContent = _t("Optimize Unified");
                    btn.onclick = async () => {
                        try {
                            const action = await this.orm.call(
                                "unified.route.optimizer",
                                "action_run_unified_optimization",
                                []
                            );
                            action && this.env.services.action.doAction(action);
                        } catch (e) {
                            console.error(e);
                            this.notification.add(_t("Unified optimization failed."), { type: "danger" });
                        }
                    };
                }
                if (btn) {
                    btn.className = "btn btn-primary btn-sm o_map_btn";
                    btn.style.marginBottom = "5px";
                    this.recordList.el.appendChild(btn);
                }
            }
            // finally render the markers & routes
            this._renderVehicleRoutes(byV, isAdmin);
        });
    }

    addMarker(position, title, address, label = null, icon = null, markerPositions = {}) {
        if (Object.keys(markerPositions).length) {
            const key = `${position.lat.toFixed(6)},${position.lng.toFixed(6)}`;
            markerPositions[key] = (markerPositions[key] || 0) + 1;
            if (markerPositions[key] > 1) {
                position = {
                    lat: position.lat + markerPositions[key]*0.0001,
                    lng: position.lng + markerPositions[key]*0.0001
                };
            }
        }
        const m = new google.maps.Marker({ position, map: this.map, title, icon,
            label: label ? { text: label, fontSize:"12px", color:"white", fontWeight:"bold" } : null
        });
        const iw = new google.maps.InfoWindow({
            content: `<div><strong>${title}</strong><br/>${address}</div>`
        });
        m.addListener("click", () => {
            this.openInfoWindow && this.openInfoWindow.close();
            iw.open(this.map, m);
            this.openInfoWindow = iw;
        });
        m.infoWindow = iw;
        this.mapElements.push(m);
        return m;
    }

    _renderVehicleRoutes(byVehicle, isAdmin) {
        const icons = {
            start: { url:"/mss_route_plan/static/description/startEnd.svg", scaledSize:new google.maps.Size(40,40) },
            job:   { url:"/mss_route_plan/static/description/pinpoint.svg", scaledSize:new google.maps.Size(30,30) },
            end:   { url:"/mss_route_plan/static/description/startEnd.svg", scaledSize:new google.maps.Size(40,40) },
        };
        let hue = Math.random()*360;
        const nextColor = () => {
            hue = (hue + 137.508) % 360;
            return `hsl(${Math.round(hue*10)/10},65%,50%)`;
        };
        const markerPositions = {};

        for (const [vid, { label:vehLabel, recs }] of Object.entries(byVehicle)) {
            recs.sort((a,b)=>a.route_sequence - b.route_sequence);
            const jobs = recs.filter(r=>r.step_type==="job");
            if (!jobs.length) continue;

            const bounds = new google.maps.LatLngBounds();
            const col = nextColor();

            // header row
            const hdr = document.createElement("li");
            hdr.textContent = vehLabel;
            Object.assign(hdr.style, {
                fontWeight:"bold", color:col,
                cursor:"pointer", margin:"10px 0 5px",
                listStyle:"none"
            });
            const arrow = document.createElement("span");
            arrow.textContent = " ▼";
            hdr.appendChild(arrow);
            const detailUl = document.createElement("ul");
            Object.assign(detailUl.style, {
                listStyle:"none", paddingLeft:"15px", display:"block"
            });
            hdr.addEventListener("click",()=>{
                const show = detailUl.style.display==="none";
                detailUl.style.display = show ? "block" : "none";
                arrow.textContent = show ? " ▲" : " ▼";
                this.map.fitBounds(bounds);
            });
            if (Object.keys(byVehicle).length===1) {
                setTimeout(()=>this.map.fitBounds(bounds),100);
            }
            this.recordList.el.appendChild(hdr);
            this.recordList.el.appendChild(detailUl);

            // start / end
            ["start","end"].forEach(type=>{
                const rec = recs.find(r=>r.step_type===type);
                if(!rec) return;
                const p={ lat:+rec.partner_latitude, lng:+rec.partner_longitude };
                bounds.extend(p);
                this.addMarker(p, `${type.charAt(0).toUpperCase()+type.slice(1)} ${vehLabel}`, "", null, icons[type], markerPositions);
            });

            // jobs
            jobs.forEach((job,i)=>{
                const p={ lat:+job.partner_latitude, lng:+job.partner_longitude };
                bounds.extend(p);
                const m = this.addMarker(p, job.display_name, job.delivery_address, String(i+1), icons.job, markerPositions);
                const li = document.createElement("li");
                li.style.cursor = "pointer";
                let href = "#";
                if (job.delivery_order_id) href = `/web#id=${job.delivery_order_id[0]}&model=stock.picking&view_type=form`;
                if (job.task_id)          href = `/web#id=${job.task_id[0]}&model=project.task&view_type=form`;
                const addr = job.delivery_address
                    ? `<small class="text-muted d-block">${job.delivery_address}</small>`
                    : "";
                li.innerHTML = `<div><a href="${href}" target="_blank" style="font-weight:bold">${job.display_name}</a></div>${addr}`;
                li.onclick = () => {
                    this.map.panTo(p);
                    this.map.setZoom(15);
                    google.maps.event.trigger(m, "click");
                };
                detailUl.appendChild(li);
            });

            // google maps link
            if (!isAdmin) {
                const btn = document.createElement("button");
                btn.textContent = _t("View in Google Maps");
                btn.className = "btn btn-primary btn-sm o_map_btn m-2";
                btn.onclick = ()=> {
                    const pts = [];
                    const srec = recs.find(r=>r.step_type==="start");
                    const erec = recs.find(r=>r.step_type==="end");
                    if (srec) pts.push(`${+srec.partner_latitude},${+srec.partner_longitude}`);
                    jobs.forEach(j=>pts.push(`${+j.partner_latitude},${+j.partner_longitude}`));
                    if (erec) pts.push(`${+erec.partner_latitude},${+erec.partner_longitude}`);
                    if (pts.length>=2) {
                        const ori = pts.shift();
                        const dst = pts.pop();
                        const wp  = encodeURIComponent(pts.join("|"));
                        window.open(
                            `https://www.google.com/maps/dir/?api=1&origin=${ori}&destination=${dst}&waypoints=${wp}`,
                            "_blank"
                        );
                    }
                };
                detailUl.appendChild(btn);
            }

            // polyline
            const srec = recs.find(r=>r.step_type==="start");
            const erec = recs.find(r=>r.step_type==="end");
            if(srec && erec) {
                const ds = new google.maps.DirectionsService();
                const dr = new google.maps.DirectionsRenderer({
                    map:this.map,
                    suppressMarkers:true,
                    polylineOptions:{ strokeColor:col, strokeOpacity:0.8, strokeWeight:4 }
                });
                this.mapElements.push(dr);
                ds.route({
                    origin: { lat:+srec.partner_latitude, lng:+srec.partner_longitude },
                    destination: { lat:+erec.partner_latitude, lng:+erec.partner_longitude },
                    waypoints: jobs.map(j=>({
                        location:{ lat:+j.partner_latitude, lng:+j.partner_longitude },
                        stopover:true
                    })),
                    travelMode: google.maps.TravelMode.DRIVING,
                }, (res,status)=>{
                    if(status===google.maps.DirectionsStatus.OK) {
                        dr.setDirections(res);
                    }
                });
            }
        }
    }

    _setupMobileToggle(){
        if (window.innerWidth>768) return;
        const mapLeft = this.recordList.el.parentElement;
        const btn = document.createElement("div");
        btn.className = "map-toggle-btn-pure";
        this.mapref.el.parentElement.insertBefore(btn,this.mapref.el);
        let open=false;
        const toggle = show => {
            open = show;
            mapLeft.classList.toggle("map-panel-visible",open);
            btn.classList.toggle("flipped",open);
            btn.style.left = open ? "calc(70% - 16px)" : "15px";
        };
        btn.addEventListener("click", e=>{ e.stopPropagation(); toggle(!open); });
        document.addEventListener("click", e=>{
            if(open && !mapLeft.contains(e.target)&&e.target!==btn) toggle(false);
        });
    }

    async _getGMapAPIKey(){
        if(!this._gmapApiKey){
            this._gmapApiKey = await this.orm.call(
                "traktop", "get_google_map_api_key", []
            );
        }
        return this._gmapApiKey;
    }
}

export const unifiedRouteMap = { component: UnifiedRouteMapView };
registry.category("fields").add("unified_route_map", unifiedRouteMap);
