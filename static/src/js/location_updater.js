/** @odoo-module **/
// File: location_updater.js
import { rpc } from "@web/core/network/rpc";

// Function to send location update to the backend
function updateUserLocation(latitude, longitude, speed) {
    // Create payload with latitude, longitude, and speed in km/h
    const payload = {
        params: {
            latitude: latitude,
            longitude: longitude,
            speed: speed  // speed now in km/h
        }
    };

    // Use fetch API to send a POST request with the payload as JSON
    fetch('/update_user_location', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
    })
    .then(response => response.json())
    .then(data => console.log("Update response:", data))
    .catch(error => console.error("Error updating location:", error));
}

// Check if Geolocation API is available
if (navigator.geolocation) {
    // Use watchPosition to continuously monitor location updates
    navigator.geolocation.watchPosition(
        function (position) {
            const latitude = position.coords.latitude;
            const longitude = position.coords.longitude;
            let speed = position.coords.speed; // speed is in m/s

            // Convert speed from m/s to km/h if available; default to 0 if not.
            if (speed !== null) {
                speed = speed * 3.6; // Convert m/s to km/h
            } else {
                speed = 0;
            }

            console.log(`Latitude: ${latitude}, Longitude: ${longitude}, Speed: ${speed} km/h`);

            // Send the updated location and speed (in km/h) to your backend
            updateUserLocation(latitude, longitude, speed);
        },
        function (error) {
            console.error("Error obtaining location:", error);
        },
        {
            enableHighAccuracy: true,
            maximumAge: 30000, // Accept a cached position up to 30 seconds old.
            timeout: 27000     // Timeout after 27 seconds.
        }
    );
} else {
    console.error("Geolocation is not supported by this browser.");
}



document.addEventListener('DOMContentLoaded', () => {
    // Immediately update location and then every 5 seconds.
    updateUserLocation();
    setInterval(updateUserLocation, 12000);
});
