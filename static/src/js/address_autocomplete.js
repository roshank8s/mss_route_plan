//  address_autocomplete.js
import { Component, useRef,onWillStart,onMounted,onPatched } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";
import { CharField, charField } from "@web/views/fields/char/char_field";

export class AddressAutocompleteGmap extends CharField {
    static template = "web.AddressAutocompleteGmap";
    static props = {
        ...CharField.props,
        LatField: { type: String, optional: true },
        LngField: { type: String, optional: true },
        NELatField: { type: String, optional: true},
        NELngField: { type: String, optional: true},
        SWLatField: { type: String, optional: true},
        SWLngField: { type: String, optional: true},
    };

    setup() {
        super.setup();
        this.orm = useService("orm");
        this._gmapApiKey = false;
        this.marker = false;
        this.mapref = useRef("googleMap");
        this.notification = useService("notification");
        onWillStart(async () => {
                const api_key = await this._getGMapAPIKey();
                if(!api_key){
                  const msg = _t("Google Map Api Key Not configured yet. Go to Settings and Do it.")
                  this.notification.add(msg, {
                        title: _t("Google Map API Key"),
                        type: "danger",
                        sticky: true,
                    });
                }
                var url = `https://maps.googleapis.com/maps/api/js?key=${api_key}&libraries=places,maps async`;
                await loadJS(url);
        });
        onMounted(()=>{
                // Map Added
                this.map = new google.maps.Map(this.mapref.el, {
                            center: {lat: -25.363, lng: 131.044 },
                            zoom: 6,
                          });
                // Add Autocomplete
                this.autocomplete = new google.maps.places.Autocomplete(this.input.el);
                this.autocomplete.setFields(["place_id", "geometry", "name","address_components"]);
                this.autocomplete.addListener('place_changed', () => {
                    const place = this.autocomplete.getPlace();
                    if (place.geometry) {
                        const lat = place.geometry.location.lat();
                        const lng = place.geometry.location.lng();
                        const southwest = place.geometry.viewport.getSouthWest();
                        const northeast = place.geometry.viewport.getNorthEast();
                
                        const swLat = southwest.lat();
                        const swLng = southwest.lng();
                        const neLat = northeast.lat();
                        const neLng = northeast.lng();
                
                        // Update marker and coordinate fields as usual
                        this.setMarker(lat, lng, neLat, neLng, swLat, swLng);
                        this.setLatLng(lat, lng, neLat, neLng, swLat, swLng);
                
                        // Instead of directly setting the value from input,
                        // call getAddressFromCoords to reverse-geocode the full address
                        this.getAddressFromCoords(lat, lng);
                    }
                });
                
                var lat = this.props.record.data[this.props.LatField];
                var lng =  this.props.record.data[this.props.LngField];
                var swLat = this.props.record.data[this.props.SWLatField];
                var swLng = this.props.record.data[this.props.SWLngField];
                var neLat = this.props.record.data[this.props.NELatField];
                var neLng = this.props.record.data[this.props.NELngField];
                if (lat && lng && swLat && swLng && neLat && neLng) {
                    this.setMarker(lat,lng,neLat,neLng,swLat,swLng);
                    this.setLatLng(lat,lng,neLat,neLng,swLat,swLng);

                }
        })
    }

    setValue(value){
        this.props.record.update({ [this.props.name]: value});
    }
    setLatLng(lat,lng,neLat,neLng,swLat,swLng){
         this.props.record.update({ [this.props.LatField]: lat,
                             [this.props.LngField]: lng,
                             [this.props.NELatField] : neLat,
                             [this.props.NELngField] : neLng,
                             [this.props.SWLatField] : swLat,
                             [this.props.SWLngField] : swLng,
          });
    }

    setMarker(lat, lng, neLat, neLng, swLat, swLng) {
        if (neLat && neLng && swLat && swLng) {
            const bounds = new google.maps.LatLngBounds(
                new google.maps.LatLng(swLat, swLng),
                new google.maps.LatLng(neLat, neLng)
            );
            this.map.fitBounds(bounds);
        }

        if (this.marker) {
            this.marker.setMap(null);
        }

        this.marker = new google.maps.Marker({
            position: { lat: parseFloat(lat), lng: parseFloat(lng) },
            map: this.map,
            draggable: true,
        });

        this.map.setCenter({ lat: parseFloat(lat), lng: parseFloat(lng) });

        google.maps.event.addListener(this.marker, "dragend", (event) => {
            const newLat = event.latLng.lat();
            const newLng = event.latLng.lng();
            this.setLatLng(newLat, newLng, neLat, neLng, swLat, swLng);
            this.getAddressFromCoords(newLat, newLng);
        });
    }

    async getAddressFromCoords(lat, lng) {
        const geocoder = new google.maps.Geocoder();
        const latLng = { lat: parseFloat(lat), lng: parseFloat(lng) };

        geocoder.geocode({ location: latLng }, (results, status) => {
            console.log("Geocode Status:", status);
            if (status === "OK" && results[0]) {
                const address = results[0].formatted_address;
                console.log("Address Found:", address);

                if (this.input && this.input.el) {
                    this.input.el.value = address;
                    this.setValue(address);
                }
                this.notification.add(_t(`Address updated: ${address}`), { type: "success" });
            } else {
                console.error("Geocode Error:", status);
                this.notification.add(_t(`Unable to retrieve address. Error: ${status}`), { type: "danger" });
            }
        });
    }


    async _getGMapAPIKey() {
                if (!this._gmapApiKey) {
                    this._gmapApiKey = await this.orm.call("ir.config_parameter", "get_param", [
                                    "address_autocomplete_gmap_widget.google_map_api_key"
                                ]);
                }
                return this._gmapApiKey;
            }


}



export const addressAutocompleteGmap = {
    component: AddressAutocompleteGmap,
    supportedTypes: ["char"],
    supportedOptions: [
        {
            label: _t("Latitude"),
            name: "latitude",
            type: "char",
            help: _t(
                "Latitude Field"
            ),
        },
        {
            label: _t("Longitude"),
            name: "longitude",
            type: "char",
            help: _t(
                "Longitude Field"
            ),
        },
        {
            label: _t("NE Latitude"),
            name: "ne_latitude",
            type: "char",
            help: _t(
                "North-East Latitude Field"
            ),
        },
        {
          label: _t("NE Longitude"),
          name: "ne_longitude",
          type: "char",
          help: _t(
              "North-East Longitude Field"
          ),
        },
        {
            label: _t("SW Latitude"),
            name: "sw_latitude",
            type: "char",
            help: _t(
                "South-West Latitude Field"
            ),
        },
        {
            label: _t("SW Longitude"),
            name: "sw_longitude",
            type: "char",
            help: _t(
                "South-West Longitude Field"
            ),
        }


    ],
    relatedFields: ({ options }) => {
        const relatedFields = [{ name: "display_name", type: "char" }];
        if (options.latitude) {
            relatedFields.push({ name: options.latitude, type: "char", readonly: false });
        }
        if (options.longitude) {
            relatedFields.push({ name: options.longitude, type: "char", readonly: false });
        }
        if (options.ne_latitude) {
            relatedFields.push({ name: options.ne_latitude, type: "char", readonly: false });
        }
        if (options.ne_longitude) {
            relatedFields.push({ name: options.ne_longitude, type: "char", readonly: false });
        }
        if (options.sw_latitude) {
            relatedFields.push({ name: options.sw_latitude, type: "char", readonly: false });
        }
        if (options.sw_longitude) {
            relatedFields.push({ name: options.sw_longitude, type: "char", readonly: false });
        }
        return relatedFields;
    },
     extractProps({ attrs, options, string }, dynamicInfo){
            return {
                    LatField : options.latitude,
                    LngField : options.longitude,
                    NELatField : options.ne_latitude,
                    NELngField : options.ne_longitude,
                    SWLatField : options.sw_latitude,
                    SWLngField : options.sw_longitude,

            }

     },

};

registry.category("fields").add("address_autocomplete_gmap_widget", addressAutocompleteGmap);
