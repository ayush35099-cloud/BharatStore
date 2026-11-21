/**
 * BharatStore — Complete Frontend Application Logic
 * Integrates Rosier Foods design system with Amazon/Flipkart marketplace discovery
 * Features: Light/Dark theme, Cart & Wishlist persistence, Hub selection,
 * OpenSearch typo-tolerant search & suggestions, ACID row locking checkout, and Admin portal.
 */

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// Global State
const initialMode = localStorage.getItem("bharatstore_shopping_mode") || "ONLINE";
const appState = {
  products: [],
  shoppingMode: initialMode,
  retailCart: {},
  onlineCart: {},
  cart: {},
  retailCarts: [],
  selectedRetailStores: new Set([1, 2, 3, 4, 5]),
  pendingSwitchMode: null,
  wishlist: new Set(JSON.parse(localStorage.getItem("bharatstore_wishlist") || "[]")),
  currentCity: localStorage.getItem("bharatstore_selected_city") || "Mumbai",
  deliveryLocation: JSON.parse(localStorage.getItem("bharatstore_delivery_location") || "null") || {
    city: "Mumbai",
    area: "Bandra West",
    pincode: "400050",
    address_line: "Flat 402, Sea Green Apts, Worli Sea Face",
    formatted: "Bandra West, Mumbai",
    distance_km: 0.5
  },
  citiesData: [],
  detectedGPS: null,
  currentCustomer: JSON.parse(localStorage.getItem("bharatstore_current_customer") || JSON.stringify({
    name: "Priya Sharma",
    email: "priya.sharma@example.in",
    phone: "+91 98201 12345",
    city: "Mumbai",
    address: "Flat 402, Sea Green Apts, Worli Sea Face, Mumbai 400030"
  })),
  activeCoupon: null
};

// -----------------------------------------------------------------------------
// 1. Initialization & Theme Switching
// -----------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", async () => {
  initTheme();
  await initShoppingMode();
  await syncCartWithBackend();
  initDeliveryLocation();
  initDealTimer();

  // If on Homepage
  if (document.getElementById("deals-products-container")) {
    loadHomepageSections();
  }

  // If on Products Catalog Page
  if (document.getElementById("catalog-products-grid")) {
    initCatalogPage();
  }
});

function initTheme() {
  const currentTheme = document.documentElement.getAttribute("data-theme") || "light";
  const icon = document.getElementById("theme-icon");
  if (icon) {
    icon.className = currentTheme === "dark" ? "fa-solid fa-sun" : "fa-solid fa-moon";
  }
}

function toggleTheme() {
  const currentTheme = document.documentElement.getAttribute("data-theme") || "light";
  const nextTheme = currentTheme === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", nextTheme);
  localStorage.setItem("bharatstore_theme", nextTheme);
  const icon = document.getElementById("theme-icon");
  if (icon) {
    icon.className = nextTheme === "dark" ? "fa-solid fa-sun" : "fa-solid fa-moon";
  }
  showToast(`Switched to ${nextTheme === 'dark' ? 'Espresso Dark' : 'Cream Linen Light'} theme`);
}

// -----------------------------------------------------------------------------
// Phase 3: Dynamic Delivery Location & GPS Selector Engine
// -----------------------------------------------------------------------------
async function initDeliveryLocation() {
  try {
    const res = await fetch("/api/location/current");
    if (res.ok) {
      const data = await res.json();
      if (data.success && data.location) {
        appState.deliveryLocation = data.location;
        appState.currentCity = data.location.city || appState.currentCity;
        localStorage.setItem("bharatstore_delivery_location", JSON.stringify(data.location));
        localStorage.setItem("bharatstore_selected_city", appState.currentCity);
      }
    }
  } catch (err) {
    console.warn("Could not sync server delivery location:", err);
  }
  updateDeliveryLocationUI(appState.deliveryLocation);
  loadSupportedCitiesAndAreas();
}

function updateDeliveryLocationUI(loc) {
  if (!loc) return;
  const display = document.getElementById("current-hub-display");
  if (display) {
    display.textContent = loc.formatted || `${loc.city} Hub`;
  }
  const label = document.getElementById("recommended-hub-label");
  if (label) {
    label.textContent = `${loc.city} Hub`;
  }
  const heroStore = document.getElementById("retail-hero-store-name");
  if (heroStore && loc.nearest_hub) {
    heroStore.textContent = loc.nearest_hub;
  }
  const heroMeta = document.getElementById("retail-hero-store-meta");
  if (heroMeta && loc.formatted) {
    const distText = loc.distance_km ? `${loc.distance_km} km away` : '1.8 km away';
    heroMeta.textContent = `${loc.formatted} • ${distText} • 2-Hour Express Delivery (₹20) or Pickup (FREE)`;
  }
}

function updateHubUI() {
  updateDeliveryLocationUI(appState.deliveryLocation);
}

function openLocationSelectorModal() {
  const modal = document.getElementById("location-selector-modal");
  if (modal) {
    modal.classList.add("open");
    // Ensure form is filled with active state
    if (appState.deliveryLocation) {
      const citySelect = document.getElementById("loc-modal-city");
      if (citySelect && appState.deliveryLocation.city) {
        citySelect.value = appState.deliveryLocation.city;
        handleModalCityChange(appState.deliveryLocation.city);
      }
      const streetInput = document.getElementById("loc-modal-street");
      if (streetInput && appState.deliveryLocation.address_line) {
        streetInput.value = appState.deliveryLocation.address_line;
      }
      const pinInput = document.getElementById("loc-modal-pincode");
      if (pinInput && appState.deliveryLocation.pincode) {
        pinInput.value = appState.deliveryLocation.pincode;
      }
    }
    loadModalSavedAddresses();
  }
}

function closeLocationSelectorModal(e) {
  if (e && e.target !== e.currentTarget && !e.target.classList.contains("drawer-close-btn")) return;
  const modal = document.getElementById("location-selector-modal");
  if (modal) modal.classList.remove("open");
  const legacy = document.getElementById("hub-modal-overlay");
  if (legacy) legacy.classList.remove("open");
}

function openHubSwitchModal() {
  openLocationSelectorModal();
}

function closeHubSwitchModal(e) {
  closeLocationSelectorModal(e);
}

function selectDeliveryHub(hubName) {
  appState.currentCity = hubName;
  localStorage.setItem("bharatstore_selected_city", hubName);
  const citySelect = document.getElementById("loc-modal-city");
  if (citySelect) {
    citySelect.value = hubName;
    handleModalCityChange(hubName);
  }
  confirmSelectedDeliveryLocation();
  if (document.getElementById("catalog-products-grid")) {
    applyFilters();
  }
}

async function loadSupportedCitiesAndAreas() {
  try {
    const res = await fetch("/api/location/cities-areas");
    const data = await res.json();
    if (data.success && data.cities) {
      appState.citiesData = data.cities;
      const currentCity = appState.deliveryLocation?.city || appState.currentCity || "Mumbai";
      handleModalCityChange(currentCity);
    }
  } catch (err) {
    console.error("Failed to load cities/areas data:", err);
  }
}

function handleModalCityChange(cityName) {
  const cityData = (appState.citiesData || []).find(c => c.city.toLowerCase() === (cityName || "").toLowerCase());
  const areaSelect = document.getElementById("loc-modal-area");
  const pinInput = document.getElementById("loc-modal-pincode");

  if (!cityData || !areaSelect) return;

  areaSelect.innerHTML = cityData.areas.map((a, i) => `
    <option value="${a.name}" ${i === 0 ? 'selected' : ''}>${a.name} (${a.distance_km} km)</option>
  `).join("");

  if (pinInput && cityData.areas.length > 0) {
    pinInput.value = cityData.areas[0].pincode;
  }
}

function handleModalAreaChange(areaName) {
  const citySelect = document.getElementById("loc-modal-city");
  const pinInput = document.getElementById("loc-modal-pincode");
  if (!citySelect || !pinInput) return;

  const cityName = citySelect.value;
  const cityData = (appState.citiesData || []).find(c => c.city.toLowerCase() === cityName.toLowerCase());
  if (!cityData) return;

  const area = cityData.areas.find(a => a.name.toLowerCase() === areaName.toLowerCase());
  if (area) {
    pinInput.value = area.pincode;
  }
}

async function detectGPSLocation() {
  const btn = document.getElementById("gps-detect-btn");
  const statusBox = document.getElementById("gps-status-box");
  const statusText = document.getElementById("gps-status-text");

  if (!navigator.geolocation) {
    if (statusBox && statusText) {
      statusBox.style.display = "block";
      statusText.innerHTML = `<span style="color:var(--color-danger);"><i class="fa-solid fa-triangle-exclamation"></i> Geolocation is not supported by this browser. Please select your area manually below.</span>`;
    }
    showToast("Geolocation not supported. Please select area manually.", "warning");
    return;
  }

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> <span>Acquiring GPS Satellite Signal...</span>`;
  }
  if (statusBox && statusText) {
    statusBox.style.display = "block";
    statusText.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Contacting browser Geolocation API...`;
  }

  navigator.geolocation.getCurrentPosition(
    async (position) => {
      const lat = position.coords.latitude;
      const lng = position.coords.longitude;
      appState.detectedGPS = { lat, lng };

      try {
        if (statusText) statusText.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Validating coordinates with BharatStore routing engine...`;
        const res = await fetch("/api/location/validate-coords", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ latitude: lat, longitude: lng })
        });
        const data = await res.json();
        if (data.success && data.valid) {
          if (statusText) {
            statusText.innerHTML = `
              <div style="background:var(--color-primary-light); padding:10px 12px; border-radius:var(--radius-sm); border:1px solid var(--color-primary); color:var(--color-primary-dark); line-height:1.4;">
                <i class="fa-solid fa-circle-check"></i> <strong>GPS Verified:</strong> ${lat.toFixed(4)}°N, ${lng.toFixed(4)}°E<br>
                <span>Nearest store hub: <strong>${data.nearest_hub}</strong> (${data.distance_km} km away). Please confirm your neighbourhood below.</span>
              </div>
            `;
          }
          const citySelect = document.getElementById("loc-modal-city");
          if (citySelect) {
            citySelect.value = data.nearest_city;
            handleModalCityChange(data.nearest_city);
          }
          showToast(`GPS located! Nearest physical store: ${data.nearest_hub} (${data.distance_km} km)`);
        } else {
          if (statusText) {
            statusText.innerHTML = `<span style="color:var(--color-warning);">${data.error || 'Could not map GPS coordinates. Please select manually.'}</span>`;
          }
        }
      } catch (err) {
        console.error("GPS validation error:", err);
        if (statusText) statusText.innerHTML = `<span style="color:var(--color-warning);">Coordinate validation offline. Please select your area manually below.</span>`;
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = `<i class="fa-solid fa-location-crosshairs"></i> <span>Use My Current Location (GPS)</span>`;
        }
      }
    },
    (err) => {
      let msg = "Could not detect GPS location. Please select your area manually below.";
      if (err.code === 1) {
        msg = "Location permission denied. Please select your city and neighbourhood manually below.";
      } else if (err.code === 2) {
        msg = "GPS position unavailable. Please choose your location from the supported metro areas.";
      } else if (err.code === 3) {
        msg = "GPS request timed out. Please select your location manually.";
      }

      if (statusText) {
        statusText.innerHTML = `<span style="color:var(--color-danger);"><i class="fa-solid fa-triangle-exclamation"></i> ${msg}</span>`;
      }
      showToast(msg, "warning");

      if (btn) {
        btn.disabled = false;
        btn.innerHTML = `<i class="fa-solid fa-location-crosshairs"></i> <span>Use My Current Location (GPS)</span>`;
      }
    },
    { timeout: 8000, enableHighAccuracy: true }
  );
}

async function loadModalSavedAddresses() {
  const container = document.getElementById("modal-saved-address-pills");
  if (!container) return;

  try {
    const res = await fetch("/api/customer/addresses");
    const data = await res.json();
    if (data.success && data.addresses && data.addresses.length > 0) {
      container.innerHTML = data.addresses.map(a => `
        <button type="button" class="btn-secondary" style="font-size:11.5px; padding:6px 10px; justify-content:flex-start; text-align:left;" onclick="selectSavedAddressIntoModal(${a.id})">
          <i class="fa-solid fa-${a.address_type === 'WORK' ? 'briefcase' : (a.address_type === 'HOME' ? 'house' : 'location-dot')}" style="color:var(--color-primary);"></i>
          <span><strong>${a.address_type}:</strong> ${escapeHtml(a.city)} (${escapeHtml(a.pincode)})</span>
        </button>
      `).join("");
      window.modalSavedAddressesCache = data.addresses;
    } else {
      container.innerHTML = `<span style="font-size:11.5px; color:var(--color-text-muted);">No saved addresses yet. Add one in your profile!</span>`;
    }
  } catch (err) {
    container.innerHTML = "";
  }
}

function selectSavedAddressIntoModal(addrId) {
  const addr = (window.modalSavedAddressesCache || []).find(a => a.id === addrId);
  if (!addr) return;

  const citySelect = document.getElementById("loc-modal-city");
  if (citySelect) {
    citySelect.value = addr.city;
    handleModalCityChange(addr.city);
  }
  const streetInput = document.getElementById("loc-modal-street");
  if (streetInput) {
    streetInput.value = `${addr.address_line1}${addr.address_line2 ? ', ' + addr.address_line2 : ''}`;
  }
  const pinInput = document.getElementById("loc-modal-pincode");
  if (pinInput) {
    pinInput.value = addr.pincode;
  }
  const landInput = document.getElementById("loc-modal-landmark");
  if (landInput && addr.landmark) {
    landInput.value = addr.landmark;
  }

  showToast(`Loaded ${addr.address_type} address: ${addr.city}`);
}

async function confirmSelectedDeliveryLocation() {
  const citySelect = document.getElementById("loc-modal-city");
  const areaSelect = document.getElementById("loc-modal-area");
  const streetInput = document.getElementById("loc-modal-street");
  const pinInput = document.getElementById("loc-modal-pincode");

  const city = citySelect?.value || appState.currentCity || "Mumbai";
  const area = areaSelect?.value || "Bandra West";
  const street = streetInput?.value?.trim() || "Flat 402, Sea Green Apts, Worli Sea Face";
  const pincode = pinInput?.value?.trim() || "400050";

  if (!/^[1-9][0-9]{5}$/.test(pincode)) {
    showToast("Please enter a valid 6-digit Indian PIN code (e.g. 400050).", "error");
    if (pinInput) pinInput.focus();
    return;
  }

  const payload = {
    city: city,
    area: area,
    address_line: street,
    pincode: pincode,
    latitude: appState.detectedGPS ? appState.detectedGPS.lat : null,
    longitude: appState.detectedGPS ? appState.detectedGPS.lng : null,
    source: appState.detectedGPS ? "gps" : "manual"
  };

  try {
    const res = await fetch("/api/location/set-current", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.success && data.location) {
      appState.deliveryLocation = data.location;
      appState.currentCity = data.location.city;
      localStorage.setItem("bharatstore_delivery_location", JSON.stringify(data.location));
      localStorage.setItem("bharatstore_selected_city", data.location.city);
      updateDeliveryLocationUI(data.location);
      closeLocationSelectorModal();
      showToast(`📍 Delivery location set: ${data.location.formatted}`);
    } else {
      showToast(data.error || "Could not set delivery location.", "error");
    }
  } catch (err) {
    console.error("Error setting location:", err);
    showToast("Network error setting delivery location.", "error");
  }
}

// -----------------------------------------------------------------------------
// 1b. Dual Shopping Mode Management & Basket Isolation
// -----------------------------------------------------------------------------
async function initShoppingMode() {
  // 1. Sync mode with server Flask session
  try {
    const res = await fetch("/api/shopping-mode");
    if (res.ok) {
      const data = await res.json();
      if (data.mode && ["RETAIL_NEAR_ME", "ONLINE"].includes(data.mode)) {
        appState.shoppingMode = data.mode;
        localStorage.setItem("bharatstore_shopping_mode", data.mode);
      }
    }
  } catch (err) {
    console.debug("Shopping mode session sync check:", err);
  }

  // 2. Point active cart to the mode-specific basket
  if (appState.shoppingMode === "RETAIL_NEAR_ME") {
    appState.cart = appState.retailCart || {};
  } else {
    appState.cart = appState.onlineCart || {};
  }
  localStorage.setItem("bharatstore_cart", JSON.stringify(appState.cart));

  // 3. Update UI states
  updateModeUI();
  updateModeNav();
  updateHeaderBadges();
}

function updateModeUI() {
  const isRetail = appState.shoppingMode === "RETAIL_NEAR_ME";
  const btnRetail = document.getElementById("mode-btn-retail");
  const btnOnline = document.getElementById("mode-btn-online");

  if (btnRetail) {
    btnRetail.classList.toggle("active", isRetail);
    btnRetail.setAttribute("aria-checked", isRetail ? "true" : "false");
  }
  if (btnOnline) {
    btnOnline.classList.toggle("active", !isRetail);
    btnOnline.setAttribute("aria-checked", !isRetail ? "true" : "false");
  }

  // Update card highlights if on /select-mode page or modal
  const pageCardRetail = document.getElementById("page-card-retail");
  const pageCardOnline = document.getElementById("page-card-online");
  if (pageCardRetail) pageCardRetail.classList.toggle("active-mode-card", isRetail);
  if (pageCardOnline) pageCardOnline.classList.toggle("active-mode-card", !isRetail);

  const modalCardRetail = document.getElementById("modal-card-retail");
  const modalCardOnline = document.getElementById("modal-card-online");
  if (modalCardRetail) modalCardRetail.classList.toggle("active-mode-card", isRetail);
  if (modalCardOnline) modalCardOnline.classList.toggle("active-mode-card", !isRetail);
}

function updateModeNav() {
  const isRetail = appState.shoppingMode === "RETAIL_NEAR_ME";
  document.querySelectorAll(".retail-only-nav").forEach(el => {
    el.classList.toggle("nav-hidden", !isRetail);
  });
  document.querySelectorAll(".online-only-nav").forEach(el => {
    el.classList.toggle("nav-hidden", isRetail);
  });
  const homeLink = document.getElementById("nav-mode-home");
  if (homeLink) {
    homeLink.setAttribute("href", isRetail ? "/retail" : "/");
  }
}

function handleModeSwitchRequest(targetMode) {
  if (targetMode === appState.shoppingMode) {
    const name = targetMode === "RETAIL_NEAR_ME" ? "Retail Near Me" : "Online Shopping";
    showToast(`Already shopping in ${name} mode.`);
    return;
  }

  const currentItems = Object.values(appState.cart);
  const itemCount = currentItems.reduce((sum, item) => sum + item.qty, 0);

  if (itemCount > 0) {
    // Current cart has items! Prompt confirmation modal to isolate and preserve the basket.
    appState.pendingSwitchMode = targetMode;
    openModeSwitchModal(targetMode, itemCount);
  } else {
    // Cart is empty, switch immediately without interruption
    executeModeSwitch(targetMode);
  }
}

function openModeSwitchModal(targetMode, itemCount) {
  const modal = document.getElementById("mode-switch-modal-overlay");
  if (!modal) {
    const confirmSwitch = confirm(`Your cart contains ${itemCount} items. Switching modes will preserve your items in a separate basket. Proceed?`);
    if (confirmSwitch) executeModeSwitch(targetMode);
    return;
  }

  const currentModeName = appState.shoppingMode === "RETAIL_NEAR_ME" ? "Retail Near Me" : "Online Shopping";
  const targetModeName = targetMode === "RETAIL_NEAR_ME" ? "Retail Near Me" : "Online Shopping";
  const storeLabel = appState.shoppingMode === "RETAIL_NEAR_ME" ? `BharatStore ${appState.currentCity} Store` : "Online Marketplace";

  const msgEl = document.getElementById("mode-confirm-message");
  if (msgEl) {
    msgEl.innerHTML = `Your basket currently contains <strong>${itemCount} item${itemCount > 1 ? 's' : ''}</strong> from <strong>${storeLabel}</strong> (${currentModeName}).<br><br>Switching to <strong>${targetModeName}</strong> will safely preserve your current items in a separate basket. Would you like to proceed?`;
  }

  const previewEl = document.getElementById("mode-confirm-cart-preview");
  if (previewEl) {
    const items = Object.values(appState.cart).slice(0, 3);
    previewEl.innerHTML = `
      <div style="font-size: 11.5px; font-weight: 700; color: var(--color-text-muted); margin-bottom: 8px; text-transform: uppercase;">Preserved Basket Preview:</div>
      <div style="display:flex; gap:8px; flex-wrap:wrap;">
        ${items.map(it => `
          <div style="display:flex; align-items:center; gap:6px; background:var(--color-bg-canvas); padding:4px 8px; border-radius:var(--radius-sm); border:1px solid var(--color-border); font-size:12px;">
            <img src="${it.product.image_url}" alt="" style="width:24px; height:24px; object-fit:cover; border-radius:4px;">
            <span style="max-width:120px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${it.product.title}</span>
            <span style="font-weight:700; color:var(--color-primary);">×${it.qty}</span>
          </div>
        `).join("")}
        ${Object.values(appState.cart).length > 3 ? `<span style="font-size:11px; align-self:center; color:var(--color-text-muted);">+${Object.values(appState.cart).length - 3} more</span>` : ''}
      </div>
    `;
  }

  modal.classList.add("open");
}

function closeModeSwitchModal(e) {
  const modal = document.getElementById("mode-switch-modal-overlay");
  if (modal) modal.classList.remove("open");
  appState.pendingSwitchMode = null;
}

function confirmModeSwitchProceed() {
  const targetMode = appState.pendingSwitchMode;
  closeModeSwitchModal();
  if (targetMode) {
    executeModeSwitch(targetMode);
  }
}

async function executeModeSwitch(targetMode) {
  // 1. Save current cart to its specific bucket
  if (appState.shoppingMode === "RETAIL_NEAR_ME") {
    appState.retailCart = appState.cart;
    localStorage.setItem("bharatstore_retail_cart", JSON.stringify(appState.retailCart));
  } else {
    appState.onlineCart = appState.cart;
    localStorage.setItem("bharatstore_online_cart", JSON.stringify(appState.onlineCart));
  }

  // 2. Persist to server session
  try {
    const res = await fetch("/api/shopping-mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: targetMode })
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      console.warn("Server mode update notice:", data.error);
    }
  } catch (err) {
    console.debug("Offline mode sync fallback:", err);
  }

  // 3. Switch active state
  appState.shoppingMode = targetMode;
  localStorage.setItem("bharatstore_shopping_mode", targetMode);
  localStorage.setItem("bharatstore_mode_selected", "true");

  // 4. Restore the other basket
  if (targetMode === "RETAIL_NEAR_ME") {
    appState.cart = appState.retailCart || {};
  } else {
    appState.cart = appState.onlineCart || {};
  }
  localStorage.setItem("bharatstore_cart", JSON.stringify(appState.cart));

  // 5. Update UI
  updateModeUI();
  updateModeNav();
  updateHeaderBadges();
  renderCartDrawer();

  const restoredCount = Object.values(appState.cart).reduce((sum, item) => sum + item.qty, 0);
  const modeName = targetMode === "RETAIL_NEAR_ME" ? "🛍️ Retail Near Me (15 km Quick Commerce)" : "🌐 Online Shopping (Pan-India Marketplace)";
  showToast(`Switched to ${modeName}.${restoredCount > 0 ? ` Restored your ${targetMode === 'RETAIL_NEAR_ME' ? 'retail' : 'online'} basket (${restoredCount} items).` : ''}`);

  if (document.getElementById("cart-page-items-list")) {
    renderCartPage();
  }

  // 6. Seamless Mode-Aware Navigation Transition
  const currentPath = window.location.pathname;
  if (targetMode === "RETAIL_NEAR_ME") {
    // If not already on retail page, navigate to Retail Near Me experience
    if (currentPath !== "/retail") {
      setTimeout(() => {
        window.location.href = "/retail";
      }, 300);
      return;
    }
    // If location is not set yet, prompt location/store selector
    if (!localStorage.getItem("bharatstore_selected_city")) {
      setTimeout(() => {
        openHubSwitchModal();
      }, 400);
    }
  } else if (targetMode === "ONLINE") {
    // If on retail page or select-mode, navigate to full online marketplace homepage
    if (currentPath === "/retail" || currentPath === "/select-mode") {
      setTimeout(() => {
        window.location.href = "/?view=online";
      }, 300);
      return;
    }
  }
}

function openModeSelectModal() {
  const modal = document.getElementById("mode-selection-modal");
  if (modal) modal.classList.add("open");
}

function closeModeSelectModal(e) {
  const modal = document.getElementById("mode-selection-modal");
  if (modal) modal.classList.remove("open");
}

function selectModeFromModal(targetMode) {
  closeModeSelectModal();
  handleModeSwitchRequest(targetMode);
}

function selectModeAndNavigate(targetMode) {
  handleModeSwitchRequest(targetMode);
  setTimeout(() => {
    if (targetMode === "RETAIL_NEAR_ME") {
      window.location.href = "/retail";
    } else {
      window.location.href = "/?view=online";
    }
  }, 250);
}

function handleNearbyStoresNav() {
  const nearbyEl = document.getElementById("nearby-stores-section");
  if (nearbyEl) {
    nearbyEl.scrollIntoView({ behavior: "smooth" });
  } else {
    window.location.href = "/retail/stores";
  }
}

// -----------------------------------------------------------------------------
// 2. Cart Management (Backend Database Authoritative Source of Truth)
// -----------------------------------------------------------------------------
async function syncCartWithBackend() {
  try {
    const isRetail = appState.shoppingMode === "RETAIL_NEAR_ME";
    if (isRetail) {
      let locParams = "";
      if (appState.deliveryLocation && appState.deliveryLocation.latitude && appState.deliveryLocation.longitude) {
        locParams = `?customer_lat=${appState.deliveryLocation.latitude}&customer_lng=${appState.deliveryLocation.longitude}`;
      }
      const res = await fetch(`/api/cart/retail${locParams}`);
      if (res.ok) {
        const data = await res.json();
        const shops = data.shops || [];
        appState.retailCarts = shops;
        appState.cart = {};
        let totalItems = 0;
        shops.forEach(shop => {
          (shop.items || []).forEach(it => {
            const key = `${shop.store_id}_${it.product_id}`;
            appState.cart[key] = {
              id: it.item_id,
              key: key,
              store_id: shop.store_id,
              store_name: shop.store_name,
              fulfillment: it.fulfillment || shop.fulfillment || "delivery",
              product: {
                id: it.product_id,
                title: it.title,
                brand: it.brand,
                price: it.unit_price,
                image_url: it.image_url,
                stock: it.live_stock,
                category: it.category
              },
              qty: it.quantity
            };
            totalItems += it.quantity;
          });
        });
        appState.retailCart = { ...appState.cart };
        if (totalItems === 0) {
          localStorage.removeItem("bharatstore_retail_cart");
          localStorage.removeItem("bharatstore_cart");
        } else {
          localStorage.setItem("bharatstore_retail_cart", JSON.stringify(appState.retailCart));
          localStorage.setItem("bharatstore_cart", JSON.stringify(appState.cart));
        }
      }
    } else {
      const res = await fetch("/api/cart/online");
      if (res.ok) {
        const data = await res.json();
        const cartData = data.cart || {};
        const items = cartData.items || [];
        appState.cart = {};
        let totalItems = 0;
        items.forEach(it => {
          appState.cart[it.product_id] = {
            id: it.item_id,
            key: it.product_id,
            product: {
              id: it.product_id,
              title: it.title,
              brand: it.brand,
              price: it.unit_price,
              image_url: it.image_url,
              stock: it.live_stock,
              category: it.category
            },
            qty: it.quantity,
            fulfillment: "delivery"
          };
          totalItems += it.quantity;
        });
        appState.onlineCart = { ...appState.cart };
        if (totalItems === 0) {
          localStorage.removeItem("bharatstore_online_cart");
          localStorage.removeItem("bharatstore_cart");
        } else {
          localStorage.setItem("bharatstore_online_cart", JSON.stringify(appState.onlineCart));
          localStorage.setItem("bharatstore_cart", JSON.stringify(appState.cart));
        }
      }
    }
  } catch (err) {
    console.warn("Backend cart sync notice:", err);
  } finally {
    updateHeaderBadges();
    renderCartDrawer();
    if (document.getElementById("cart-page-items-list")) {
      renderCartPage();
    }
    if (document.getElementById("checkout-items-preview")) {
      initCheckoutPage();
    }
  }
}

function saveCart() {
  updateHeaderBadges();
  renderCartDrawer();
}

function updateHeaderBadges() {
  const items = Object.values(appState.cart);
  const totalItems = items.reduce((sum, item) => sum + (item.qty || 0), 0);
  const totalAmount = items.reduce((sum, item) => sum + (((item.product && item.product.price) || 0) * (item.qty || 0)), 0);

  const cartBadge = document.getElementById("cart-badge-count");
  if (cartBadge) cartBadge.textContent = totalItems;
  const drawerCount = document.getElementById("drawer-cart-count");
  if (drawerCount) drawerCount.textContent = totalItems;
  const subtotalEl = document.getElementById("header-cart-subtotal");
  if (subtotalEl) subtotalEl.textContent = `₹${totalAmount.toLocaleString('en-IN')}`;
  const wishlistBadge = document.getElementById("wishlist-badge-count");
  if (wishlistBadge) wishlistBadge.textContent = appState.wishlist.size;
}

async function addToCart(productId, qty = 1, storeId = null, storeName = null, fulfillment = "delivery") {
  const isRetail = appState.shoppingMode === "RETAIL_NEAR_ME";
  if (isRetail) {
    const sId = storeId || parseInt(localStorage.getItem("bharatstore_selected_store_id") || "1");
    try {
      const res = await fetch(`/api/cart/retail/${sId}/add`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          product_id: productId,
          quantity: qty,
          fulfillment: fulfillment || "delivery"
        })
      });
      const data = await res.json();
      if (!res.ok || !data.success) {
        showToast(data.error || "Cannot add product to store basket", true);
        return;
      }
      await syncCartWithBackend();
      showToast(`Added to ${data.cart?.store_name || `Store #${sId}`} basket!`);
    } catch (e) {
      console.error("Retail add to cart error:", e);
      showToast("Network error while adding to basket", true);
    }
  } else {
    try {
      const res = await fetch("/api/cart/online/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          product_id: productId,
          quantity: qty
        })
      });
      const data = await res.json();
      if (!res.ok || !data.success) {
        showToast(data.error || "Cannot add product to online cart", true);
        return;
      }
      await syncCartWithBackend();
      showToast("Added to Online Shopping cart!");
    } catch (e) {
      console.error("Online add to cart error:", e);
      showToast("Network error while adding to cart", true);
    }
  }
}

async function updateCartItemQty(keyOrId, delta) {
  let item = appState.cart[keyOrId];
  if (!item) {
    item = Object.values(appState.cart).find(it => it.id === Number(keyOrId) || (it.product && it.product.id === Number(keyOrId)) || it.key === String(keyOrId));
  }
  if (!item) return;

  const newQty = item.qty + delta;
  if (newQty <= 0) {
    await removeCartItem(item.id || keyOrId);
    return;
  }

  try {
    const res = await fetch(`/api/cart/items/${item.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ quantity: newQty })
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      showToast(data.error || "Could not update item quantity", true);
      return;
    }
    await syncCartWithBackend();
  } catch (err) {
    console.error("Update item qty error:", err);
  }
}

async function removeCartItem(keyOrId) {
  let item = appState.cart[keyOrId];
  if (!item) {
    item = Object.values(appState.cart).find(it => it.id === Number(keyOrId) || (it.product && it.product.id === Number(keyOrId)) || it.key === String(keyOrId));
  }
  const itemId = item ? item.id : keyOrId;
  try {
    const res = await fetch(`/api/cart/items/${itemId}`, {
      method: "DELETE"
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      showToast(data.error || "Could not remove item", true);
      return;
    }
    await syncCartWithBackend();
    showToast("Item removed from basket");
  } catch (err) {
    console.error("Remove cart item error:", err);
  }
}

async function clearCart() {
  const isRetail = appState.shoppingMode === "RETAIL_NEAR_ME";
  try {
    if (isRetail) {
      await fetch("/api/cart/retail/clear", { method: "DELETE" });
    } else {
      await fetch("/api/cart/online/clear", { method: "DELETE" });
    }
    await syncCartWithBackend();
    showToast("Basket cleared.");
  } catch (err) {
    console.error("Clear cart error:", err);
  }
}

async function clearStoreBasket(storeId) {
  try {
    await fetch(`/api/cart/retail/${storeId}/clear`, { method: "DELETE" });
    await syncCartWithBackend();
    showToast("Store basket cleared.");
  } catch (err) {
    console.error("Clear store basket error:", err);
  }
}

async function updateShopFulfillment(storeIdOrShopName, value) {
  let sId = Number(storeIdOrShopName);
  if (isNaN(sId)) {
    const found = (appState.retailCarts || []).find(s => s.store_name === storeIdOrShopName);
    if (found) sId = found.store_id;
  }
  const items = Object.values(appState.cart).filter(it => it.store_id === sId);
  for (const it of items) {
    try {
      await fetch(`/api/cart/items/${it.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fulfillment: value })
      });
    } catch (e) {
      console.warn("Fulfillment update error:", e);
    }
  }
  await syncCartWithBackend();
  showToast(`Fulfillment updated: ${value === 'pickup' ? 'Store Counter Pickup (FREE)' : '2-Hour Delivery'}`);
}

function openCartDrawer() {
  const drawer = document.getElementById("cart-drawer-overlay");
  if (drawer && !drawer.classList.contains("open")) {
    drawer.classList.add("open");
    document.body.style.overflow = "hidden";
    renderCartDrawer();
  }
}

function toggleCartDrawer() {
  const drawer = document.getElementById("cart-drawer-overlay");
  if (drawer) {
    drawer.classList.toggle("open");
    if (drawer.classList.contains("open")) {
      document.body.style.overflow = "hidden";
      renderCartDrawer();
    } else {
      document.body.style.overflow = "";
    }
  }
}

function closeCartDrawer(e) {
  const drawer = document.getElementById("cart-drawer-overlay");
  if (drawer) {
    drawer.classList.remove("open");
    document.body.style.overflow = "";
  }
}

function toggleCartDrawerShopSelection(storeId, isChecked) {
  if (!appState.selectedRetailStores) {
    appState.selectedRetailStores = new Set();
  }
  const sId = Number(storeId);
  if (isChecked) {
    appState.selectedRetailStores.add(sId);
  } else {
    appState.selectedRetailStores.delete(sId);
  }
  renderCartDrawer();
}

function proceedToCheckoutFromDrawer() {
  closeCartDrawer();
  const isRetail = appState.shoppingMode === "RETAIL_NEAR_ME";
  if (isRetail) {
    let selectedIds = [];
    if (appState.selectedRetailStores && appState.selectedRetailStores.size > 0) {
      selectedIds = Array.from(appState.selectedRetailStores);
    } else {
      selectedIds = (appState.retailCarts || [])
        .filter(s => (s.items || []).length > 0)
        .map(s => s.store_id);
    }
    if (selectedIds.length > 0) {
      window.location.href = `/checkout?mode=retail&stores=${selectedIds.join(",")}`;
    } else {
      window.location.href = "/checkout?mode=retail";
    }
  } else {
    window.location.href = "/checkout?mode=online";
  }
}

function renderCartDrawer() {
  const container = document.getElementById("cart-drawer-items-container");
  const totalEl = document.getElementById("drawer-cart-total");
  const checkoutBtn = document.getElementById("drawer-checkout-btn");
  if (!container) return;

  const items = Object.values(appState.cart);
  if (items.length === 0) {
    container.innerHTML = `
      <div style="text-align:center; padding: 48px 16px; color: var(--color-text-muted);">
        <i class="fa-solid fa-bag-shopping" style="font-size: 36px; margin-bottom: 12px; color: var(--color-border-strong);"></i>
        <h4 style="font-size: 15px; margin-bottom: 6px;">Your basket is empty</h4>
        <p style="font-size: 12px;">Add authentic goods from our catalog to get started.</p>
      </div>
    `;
    if (totalEl) totalEl.textContent = "₹0";
    if (checkoutBtn) {
      checkoutBtn.innerHTML = `<i class="fa-solid fa-lock"></i> Proceed to Checkout`;
      checkoutBtn.style.pointerEvents = "auto";
      checkoutBtn.style.opacity = "1";
    }
    return;
  }

  let subtotal = 0;

  if (appState.shoppingMode === "RETAIL_NEAR_ME") {
    // Group by physical grocery shop
    const shopGroups = {};
    items.forEach(item => {
      const p = item.product;
      const sName = item.store_name || "Bharat Fresh Mart";
      const sId = Number(item.store_id || 1);
      if (!shopGroups[sName]) {
        shopGroups[sName] = {
          name: sName,
          store_id: sId,
          fulfillment: item.fulfillment || 'delivery',
          items: [],
          subtotal: 0
        };
      }
      shopGroups[sName].items.push(item);
      const itemSub = p.price * item.qty;
      shopGroups[sName].subtotal += itemSub;
    });

    if (!appState.selectedRetailStores) {
      appState.selectedRetailStores = new Set(Object.values(shopGroups).map(g => g.store_id));
    }

    let selectedShopCount = 0;
    Object.values(shopGroups).forEach(group => {
      if (appState.selectedRetailStores.has(group.store_id)) {
        subtotal += group.subtotal;
        selectedShopCount++;
      }
    });

    container.innerHTML = Object.values(shopGroups).map(group => {
      const isSelected = appState.selectedRetailStores.has(group.store_id);
      return `
      <div class="shop-cart-group" style="${isSelected ? '' : 'opacity:0.65; border-color:var(--color-border);'}">
        <div class="shop-cart-group-header">
          <label style="display:flex; align-items:center; gap:8px; cursor:pointer; margin:0;">
            <input 
              type="checkbox" 
              class="shop-cart-checkbox" 
              data-store-id="${group.store_id}" 
              ${isSelected ? 'checked' : ''} 
              onchange="toggleCartDrawerShopSelection(${group.store_id}, this.checked)"
              style="width:16px; height:16px; accent-color:var(--color-primary); cursor:pointer;"
            >
            <span class="shop-cart-group-title"><i class="fa-solid fa-shop" style="color:var(--color-primary); margin-right:4px;"></i> ${escapeHtml(group.name)}</span>
          </label>
          <span style="font-size:12px; font-weight:700; color:var(--color-primary);">₹${group.subtotal.toLocaleString('en-IN')}</span>
        </div>

        <div style="padding:6px 12px; background:var(--color-bg-subtle); border-bottom:1px solid var(--color-border-subtle); display:flex; justify-content:space-between; align-items:center; font-size:11px;">
          <span style="font-weight:600; color:var(--color-text-muted);"><i class="fa-solid fa-truck"></i> Fulfillment:</span>
          <select onchange="updateShopFulfillment('${group.name.replace(/'/g, "\\'")}', this.value)" style="font-size:11px; padding:2px 6px; border-radius:4px; border:1px solid var(--color-border); background:var(--color-bg-surface); cursor:pointer;">
            <option value="delivery" ${group.fulfillment === 'delivery' ? 'selected' : ''}>Standard Delivery (₹20)</option>
            <option value="pickup" ${group.fulfillment === 'pickup' ? 'selected' : ''}>Store Pickup</option>
          </select>
        </div>

        <div class="shop-cart-items-list">
          ${group.items.map(item => {
            const p = item.product;
            return `
              <div class="drawer-item" style="padding:8px 0; border-bottom:1px solid var(--color-border-subtle);">
                <img src="${p.image_url}" alt="${escapeHtml(p.title)}" style="width:48px; height:48px; object-fit:contain; border-radius:4px; border:1px solid var(--color-border); padding:2px;">
                <div style="flex:1;">
                  <div class="drawer-item-title" style="font-size:12.5px;">${escapeHtml(p.title)}</div>
                  <div class="drawer-item-price" style="font-size:13px;">₹${p.price.toLocaleString('en-IN')}</div>
                  <div class="drawer-qty-control" style="margin-top:4px;">
                    <button onclick="updateCartItemQty('${item.id || item.key}', -1)">-</button>
                    <span>${item.qty}</span>
                    <button onclick="updateCartItemQty('${item.id || item.key}', 1)">+</button>
                  </div>
                </div>
                <button onclick="removeCartItem('${item.id || item.key}')" style="background:transparent; border:none; color:var(--color-danger); cursor:pointer; padding:4px;" title="Remove">
                  <i class="fa-solid fa-trash-can"></i>
                </button>
              </div>
            `;
          }).join("")}
        </div>

        <div class="shop-cart-subtotal-bar">
          <span style="color:var(--color-text-muted);">Shop Items: ${group.items.reduce((s, i) => s + i.qty, 0)}</span>
          <span>Shop Subtotal: ₹${group.subtotal.toLocaleString('en-IN')}</span>
        </div>
      </div>
    `;
    }).join("");

    if (checkoutBtn) {
      if (selectedShopCount > 0) {
        checkoutBtn.innerHTML = `<i class="fa-solid fa-lock"></i> Proceed to Checkout (${selectedShopCount} ${selectedShopCount === 1 ? 'shop' : 'shops'})`;
        checkoutBtn.style.pointerEvents = "auto";
        checkoutBtn.style.opacity = "1";
      } else {
        checkoutBtn.innerHTML = `<i class="fa-solid fa-lock"></i> Select a shop to checkout`;
        checkoutBtn.style.pointerEvents = "none";
        checkoutBtn.style.opacity = "0.5";
      }
    }
  } else {
    // Online Shopping Mode standard rendering
    container.innerHTML = items.map(item => {
      const p = item.product;
      const itemTotal = p.price * item.qty;
      subtotal += itemTotal;
      return `
        <div class="drawer-item">
          <img src="${p.image_url}" alt="${escapeHtml(p.title)}">
          <div>
            <div class="drawer-item-title">${escapeHtml(p.title)}</div>
            <div class="drawer-item-price">₹${p.price.toLocaleString('en-IN')}</div>
            <div class="drawer-qty-control">
              <button onclick="updateCartItemQty('${item.id || item.key || p.id}', -1)">-</button>
              <span>${item.qty}</span>
              <button onclick="updateCartItemQty('${item.id || item.key || p.id}', 1)">+</button>
            </div>
          </div>
          <button onclick="removeCartItem('${item.id || item.key || p.id}')" style="background:transparent; border:none; color:var(--color-danger); cursor:pointer;" title="Remove">
            <i class="fa-solid fa-trash-can"></i>
          </button>
        </div>
      `;
    }).join("");

    if (checkoutBtn) {
      checkoutBtn.innerHTML = `<i class="fa-solid fa-lock"></i> Proceed to Checkout`;
      checkoutBtn.style.pointerEvents = "auto";
      checkoutBtn.style.opacity = "1";
    }
  }

  if (totalEl) totalEl.textContent = `₹${subtotal.toLocaleString('en-IN')}`;
}

// -----------------------------------------------------------------------------
// 3. Wishlist Operations
// -----------------------------------------------------------------------------
function saveWishlist() {
  localStorage.setItem("bharatstore_wishlist", JSON.stringify([...appState.wishlist]));
  updateHeaderBadges();
}

function toggleWishlist(productId) {
  if (appState.wishlist.has(productId)) {
    appState.wishlist.delete(productId);
    showToast("Removed from wishlist");
  } else {
    appState.wishlist.add(productId);
    showToast("Saved to your wishlist!");
  }
  saveWishlist();

  // Update button visual if present on screen (both catalog cards and product details page)
  document.querySelectorAll(`.wishlist-float-btn[data-product-id="${productId}"], .detail-wishlist-action-btn[data-product-id="${productId}"]`).forEach(btn => {
    const isSaved = appState.wishlist.has(productId);
    btn.classList.toggle("active", isSaved);
    if (btn.classList.contains("detail-wishlist-action-btn")) {
      btn.innerHTML = isSaved
        ? '<i class="fa-solid fa-heart" style="color:#E03131;"></i> Saved in Wishlist'
        : '<i class="fa-regular fa-heart"></i> Add to Wishlist';
    } else {
      btn.innerHTML = isSaved ? '<i class="fa-solid fa-heart" style="color:#E03131;"></i>' : '<i class="fa-regular fa-heart"></i>';
    }
  });

  if (document.getElementById("wishlist-products-grid")) {
    renderWishlistPage();
  }
}

// -----------------------------------------------------------------------------
// 4. Product Card Template & UI State Generators
// -----------------------------------------------------------------------------
function createProductSkeletonHTML(count = 4) {
  let html = "";
  for (let i = 0; i < count; i++) {
    html += `
      <div class="product-card product-card-skeleton">
        <div class="skeleton-thumb shimmer"></div>
        <div class="product-card-body">
          <div class="skeleton-line shimmer" style="width: 35%; height: 12px; margin-bottom: 8px;"></div>
          <div class="skeleton-line shimmer" style="width: 85%; height: 16px; margin-bottom: 8px;"></div>
          <div class="skeleton-line shimmer" style="width: 60%; height: 14px; margin-bottom: 12px;"></div>
          <div class="skeleton-line shimmer" style="width: 45%; height: 18px; margin-bottom: 14px;"></div>
          <div class="skeleton-line shimmer" style="width: 100%; height: 36px; border-radius: var(--radius-sm);"></div>
        </div>
      </div>
    `;
  }
  return html;
}

function createErrorStateHTML(message, retryFnName) {
  return `
    <div class="ui-state-box ui-error-state">
      <div class="ui-state-icon"><i class="fa-solid fa-circle-exclamation"></i></div>
      <h4 class="ui-state-title">Unable to Connect to Store Hub</h4>
      <p class="ui-state-desc">${message || 'We could not fetch live products from the physical hub network.'}</p>
      ${retryFnName ? `<button class="btn-primary" onclick="${retryFnName}()"><i class="fa-solid fa-rotate-right"></i> Retry Connection</button>` : ''}
    </div>
  `;
}

function createEmptyStateHTML(title, desc) {
  return `
    <div class="ui-state-box ui-empty-state">
      <div class="ui-state-icon"><i class="fa-solid fa-box-open"></i></div>
      <h4 class="ui-state-title">${title || 'No Products Found'}</h4>
      <p class="ui-state-desc">${desc || 'Check back soon as local store inventory is updated daily.'}</p>
    </div>
  `;
}

function createProductCardHTML(p) {
  const isWishlisted = appState.wishlist.has(p.id);
  const discountPercent = p.original_price && p.original_price > p.price
    ? Math.round(((p.original_price - p.price) / p.original_price) * 100)
    : 0;

  let stockClass = "product-stock-tag";
  let stockText = `<i class="fa-solid fa-check"></i> In Stock (${p.stock} units)`;
  if (p.stock <= 0) {
    stockClass += " out-stock";
    stockText = `<i class="fa-solid fa-circle-xmark"></i> Out of Stock`;
  } else if (p.stock <= 5) {
    stockClass += " low-stock";
    stockText = `<i class="fa-solid fa-triangle-exclamation"></i> Only ${p.stock} left at ${appState.currentCity} Hub`;
  }

  const badgeText = discountPercent >= 20 ? `${discountPercent}% OFF` : (p.rating >= 4.8 ? "Top Rated" : "Verified Hub");

  return `
    <div class="product-card" data-product-id="${p.id}">
      <div class="product-card-thumb">
        <span class="product-badge-tag ${discountPercent >= 25 ? 'product-badge-deal' : ''}">${badgeText}</span>
        <button class="wishlist-float-btn ${isWishlisted ? 'active' : ''}" data-product-id="${p.id}" onclick="toggleWishlist(${p.id})" title="Wishlist">
          <i class="${isWishlisted ? 'fa-solid fa-heart' : 'fa-regular fa-heart'}" style="${isWishlisted ? 'color:#E03131;' : ''}"></i>
        </button>
        <a href="/product/${p.id}" style="width:100%; height:100%;">
          <img src="${p.image_url}" alt="${p.title}" loading="lazy">
        </a>
      </div>

      <div class="product-card-body">
        <span class="product-card-brand">${p.brand}</span>
        <a href="/product/${p.id}" class="product-card-title" title="${p.title}">${p.title}</a>
        
        <div class="product-card-rating">
          <span class="star-rating"><i class="fa-solid fa-star"></i> ${p.rating}</span>
          <span class="rating-count-text">(${p.rating_count ? p.rating_count.toLocaleString() : '50+'})</span>
        </div>

        <div class="product-card-pricing">
          <span class="current-price">₹${p.price.toLocaleString('en-IN')}</span>
          ${p.original_price && p.original_price > p.price ? `<span class="original-price">₹${p.original_price.toLocaleString('en-IN')}</span>` : ''}
          ${discountPercent > 0 ? `<span class="discount-percentage">${discountPercent}% off</span>` : ''}
        </div>

        <div class="${stockClass}">
          ${stockText}
        </div>

        <div class="product-card-actions">
          <button class="btn-add-cart" onclick="addToCart(${p.id})" ${p.stock <= 0 ? 'disabled' : ''}>
            <i class="fa-solid fa-bag-shopping"></i> Add to Cart
          </button>
          <button class="btn-quick-view" onclick="openQuickView(${p.id})" title="Quick View">
            <i class="fa-regular fa-eye"></i>
          </button>
        </div>
      </div>
    </div>
  `;
}

// -----------------------------------------------------------------------------
// 5. Homepage Sections Populator (with Skeletons, Error & Empty Handling)
// -----------------------------------------------------------------------------
async function loadHomepageSections() {
  const dealsContainer = document.getElementById("deals-products-container");
  const trendingContainer = document.getElementById("trending-products-container");
  const bestsellersContainer = document.getElementById("bestsellers-products-container");
  const recommendedContainer = document.getElementById("recommended-products-container");

  // Show loading skeletons immediately
  if (dealsContainer) dealsContainer.innerHTML = createProductSkeletonHTML(4);
  if (trendingContainer) trendingContainer.innerHTML = createProductSkeletonHTML(8);
  if (bestsellersContainer) bestsellersContainer.innerHTML = createProductSkeletonHTML(4);
  if (recommendedContainer) recommendedContainer.innerHTML = createProductSkeletonHTML(4);

  try {
    const res = await fetch("/api/products");
    if (!res.ok) throw new Error(`HTTP ${res.status}: Failed to fetch products from backend API`);
    const data = await res.json();
    appState.products = data.products || [];

    if (appState.products.length === 0) {
      const emptyHtml = createEmptyStateHTML("Catalog Updating", "Physical store inventory is syncing with cloud nodes.");
      if (dealsContainer) dealsContainer.innerHTML = emptyHtml;
      if (trendingContainer) trendingContainer.innerHTML = emptyHtml;
      if (bestsellersContainer) bestsellersContainer.innerHTML = emptyHtml;
      if (recommendedContainer) recommendedContainer.innerHTML = emptyHtml;
      return;
    }

    // 1. Deals Section: Products with highest discount %
    const deals = [...appState.products]
      .filter(p => p.original_price && p.original_price > p.price)
      .sort((a, b) => ((b.original_price - b.price) / b.original_price) - ((a.original_price - a.price) / a.original_price))
      .slice(0, 4);

    if (dealsContainer) {
      dealsContainer.innerHTML = deals.length > 0 
        ? deals.map(p => createProductCardHTML(p)).join("")
        : createEmptyStateHTML("No Active Deals", "Check back later for flash discounts.");
    }

    // 2. Trending Section
    renderTrendingProducts(appState.products.slice(0, 8));

    // 3. Best Sellers: Sort by rating_count * rating
    const bestsellers = [...appState.products]
      .sort((a, b) => (b.rating_count || 0) - (a.rating_count || 0))
      .slice(0, 4);

    if (bestsellersContainer) {
      bestsellersContainer.innerHTML = bestsellers.length > 0
        ? bestsellers.map(p => createProductCardHTML(p)).join("")
        : createEmptyStateHTML("No Best Sellers", "Catalog will populate based on shopper activity.");
    }

    // 4. Recommended for Hub: Products available in current city
    const recommended = [...appState.products]
      .filter(p => !p.cities || p.cities.includes(appState.currentCity))
      .slice(0, 4);

    if (recommendedContainer) {
      recommendedContainer.innerHTML = recommended.length > 0
        ? recommended.map(p => createProductCardHTML(p)).join("")
        : createEmptyStateHTML("No Hub Recommendations", `No specific items found for ${appState.currentCity} Hub.`);
    }

  } catch (err) {
    console.error("Error loading homepage sections:", err);
    const errHtml = createErrorStateHTML(err.message, "loadHomepageSections");
    if (dealsContainer) dealsContainer.innerHTML = errHtml;
    if (trendingContainer) trendingContainer.innerHTML = errHtml;
    if (bestsellersContainer) bestsellersContainer.innerHTML = errHtml;
    if (recommendedContainer) recommendedContainer.innerHTML = errHtml;
  }
}

function renderTrendingProducts(list) {
  const container = document.getElementById("trending-products-container");
  if (container) {
    container.innerHTML = list.map(p => createProductCardHTML(p)).join("");
  }
}

function filterTrendingTab(category, btnElement) {
  document.querySelectorAll("#trending-products-container").forEach(c => {});
  if (btnElement) {
    btnElement.parentElement.querySelectorAll("button").forEach(b => b.style.backgroundColor = "transparent");
    btnElement.style.backgroundColor = "var(--color-primary-light)";
  }
  if (category === "all") {
    renderTrendingProducts(appState.products.slice(0, 8));
  } else {
    const filtered = appState.products.filter(p => p.category === category).slice(0, 8);
    renderTrendingProducts(filtered);
  }
}

// Deal Timer Countdown
function initDealTimer() {
  const timerEl = document.getElementById("deal-countdown-timer");
  if (!timerEl) return;
  let secondsLeft = 8 * 3600 + 42 * 60 + 15;
  setInterval(() => {
    secondsLeft--;
    if (secondsLeft <= 0) secondsLeft = 12 * 3600;
    const h = Math.floor(secondsLeft / 3600);
    const m = Math.floor((secondsLeft % 3600) / 60);
    const s = secondsLeft % 60;
    timerEl.textContent = `${String(h).padStart(2, '0')}h : ${String(m).padStart(2, '0')}m : ${String(s).padStart(2, '0')}s`;
  }, 1000);
}

// -----------------------------------------------------------------------------
// 6. Catalog Page (/products) Filtering, Sorting & Pagination
// -----------------------------------------------------------------------------
let catalogFilteredProducts = [];
let catalogCurrentPage = 1;
const catalogItemsPerPage = 12;

async function initCatalogPage() {
  const grid = document.getElementById("catalog-products-grid");
  if (grid) {
    grid.innerHTML = createProductSkeletonHTML(catalogItemsPerPage);
  }

  try {
    const urlParams = new URLSearchParams(window.location.search);
    const catParam = urlParams.get("category") || window.ACTIVE_CATEGORY_PARAM || "";
    const qParam = (urlParams.get("q") || window.SEARCH_QUERY_PARAM || "").trim();

    let endpoint = "/api/products";
    const isRetailMode = (appState.shoppingMode === "RETAIL_NEAR_ME" || window.CURRENT_SHOPPING_MODE === "RETAIL_NEAR_ME");
    if (qParam) {
      endpoint = `/api/search?q=${encodeURIComponent(qParam)}`;
      if (isRetailMode) endpoint += "&mode=RETAIL_NEAR_ME";
      window.CATALOG_LOADED_VIA_OPENSEARCH = true;
    } else {
      if (isRetailMode) endpoint += "?mode=RETAIL_NEAR_ME";
      window.CATALOG_LOADED_VIA_OPENSEARCH = false;
    }

    const res = await fetch(endpoint);
    if (!res.ok) throw new Error(`HTTP ${res.status}: Failed to fetch products catalog`);
    const data = await res.json();
    appState.products = data.products || data.results || [];

    if (catParam) {
      const radio = document.querySelector(`input[name="cat_filter"][value="${catParam}"]`);
      if (radio) radio.checked = true;
      const title = document.getElementById("catalog-title");
      if (title) title.textContent = catParam;
      const bc = document.getElementById("breadcrumb-category");
      if (bc) bc.textContent = catParam;
    }

    if (qParam) {
      const title = document.getElementById("catalog-title");
      if (title) {
        const engineLabel = data.engine || "Aiven OpenSearch";
        title.innerHTML = `Search Results for "${qParam}" <span class="badge-opensearch" style="display:inline-block; margin-left:10px; font-size:12px; font-weight:600; padding:3px 10px; border-radius:20px; background:rgba(0,75,141,0.1); color:var(--color-navy); border:1px solid rgba(0,75,141,0.2);"><i class="fa-solid fa-bolt"></i> ${engineLabel}</span>`;
      }
    }

    applyFilters();
  } catch (err) {
    console.error("Error initializing catalog page:", err);
    if (grid) {
      grid.innerHTML = createErrorStateHTML(err.message, "initCatalogPage");
    }
  }
}

function toggleMobileFilterSidebar() {
  const sidebar = document.getElementById("catalog-filter-sidebar");
  if (sidebar) {
    sidebar.classList.toggle("mobile-open");
  }
}

function applyFilters() {
  catalogCurrentPage = 1;
  const selectedCatRadio = document.querySelector('input[name="cat_filter"]:checked');
  const selectedCategory = selectedCatRadio ? selectedCatRadio.value : "";
  const selectedPriceRadio = document.querySelector('input[name="price_filter"]:checked');
  const priceRange = selectedPriceRadio ? selectedPriceRadio.value : "all";
  const rating4 = document.getElementById("filter-rating-4")?.checked;
  const rating45 = document.getElementById("filter-rating-45")?.checked;
  const inStockOnly = document.getElementById("filter-in-stock-only")?.checked;
  const hubSelect = document.getElementById("filter-hub-select")?.value || "All";

  const urlParams = new URLSearchParams(window.location.search);
  const qParam = (urlParams.get("q") || "").toLowerCase().trim();

  const isRetail = (appState.shoppingMode === "RETAIL_NEAR_ME" || window.CURRENT_SHOPPING_MODE === "RETAIL_NEAR_ME");
  const ALLOWED_GROCERY_CATEGORIES = [
    "Daily Essentials & Groceries",
    "Dairy & Breakfast",
    "Rice & Grains",
    "Cooking Essentials",
    "Fresh Produce",
    "Snacks & Beverages",
    "Household Essentials",
    "Personal Care",
    "Packaged Foods"
  ];
  const NON_GROCERY_CATS = [
    "Mobiles & Tablets",
    "Laptops & Computers",
    "Audio & Wearables",
    "Home & Kitchen",
    "Fashion & Apparel",
    "Electronics"
  ];

  catalogFilteredProducts = appState.products.filter(p => {
    // Mode Isolation: Retail Near Me must be grocery-only
    if (isRetail) {
      if (NON_GROCERY_CATS.includes(p.category) || NON_GROCERY_CATS.includes(p.sub_category)) return false;
      const isGrocery = (p.category === "Daily Essentials & Groceries" || ALLOWED_GROCERY_CATEGORIES.includes(p.sub_category) || ALLOWED_GROCERY_CATEGORIES.includes(p.category));
      if (!isGrocery) return false;
    }

    // 1. Category / Sub-Category
    if (selectedCategory) {
      const matchCat = (p.category === selectedCategory || p.sub_category === selectedCategory);
      if (!matchCat) return false;
    }

    // 2. Search Query (typo-tolerant matching fallback if not pre-fetched via OpenSearch)
    if (qParam && !window.CATALOG_LOADED_VIA_OPENSEARCH) {
      const matchText = `${p.title} ${p.brand} ${p.category} ${p.description}`.toLowerCase();
      if (!matchText.includes(qParam)) return false;
    }

    // 3. Price
    if (priceRange === "under_1000" && p.price >= 1000) return false;
    if (priceRange === "1000_5000" && (p.price < 1000 || p.price > 5000)) return false;
    if (priceRange === "5000_25000" && (p.price < 5000 || p.price > 25000)) return false;
    if (priceRange === "above_25000" && p.price <= 25000) return false;

    // 4. Rating
    if (rating45 && p.rating < 4.5) return false;
    if (rating4 && p.rating < 4.0) return false;

    // 5. In Stock
    if (inStockOnly && p.stock <= 0) return false;

    // 6. Hub
    if (hubSelect !== "All" && p.cities && !p.cities.includes(hubSelect)) return false;

    return true;
  });

  // Apply sorting
  const sortVal = document.getElementById("catalog-sort-select")?.value || "featured";
  sortCatalogProducts(sortVal, false);

  renderCatalogGrid();
}

function sortCatalogProducts(sortVal, triggerRender = true) {
  if (sortVal === "price_low") {
    catalogFilteredProducts.sort((a, b) => a.price - b.price);
  } else if (sortVal === "price_high") {
    catalogFilteredProducts.sort((a, b) => b.price - a.price);
  } else if (sortVal === "rating") {
    catalogFilteredProducts.sort((a, b) => b.rating - a.rating);
  } else if (sortVal === "discount") {
    catalogFilteredProducts.sort((a, b) => {
      const discA = a.original_price ? (a.original_price - a.price) / a.original_price : 0;
      const discB = b.original_price ? (b.original_price - b.price) / b.original_price : 0;
      return discB - discA;
    });
  }
  if (triggerRender) renderCatalogGrid();
}

function changeCatalogPage(page) {
  const totalPages = Math.ceil(catalogFilteredProducts.length / catalogItemsPerPage) || 1;
  if (page < 1 || page > totalPages) return;
  catalogCurrentPage = page;
  renderCatalogGrid();

  const titleEl = document.getElementById("catalog-title");
  if (titleEl) {
    titleEl.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function renderCatalogGrid() {
  const grid = document.getElementById("catalog-products-grid");
  const countEl = document.getElementById("catalog-results-count");
  const emptyEl = document.getElementById("catalog-empty-state");
  const paginationContainer = document.getElementById("catalog-pagination-container");
  if (!grid) return;

  const totalItems = catalogFilteredProducts.length;
  const totalPages = Math.ceil(totalItems / catalogItemsPerPage) || 1;
  if (catalogCurrentPage > totalPages) catalogCurrentPage = totalPages;

  const startIndex = (catalogCurrentPage - 1) * catalogItemsPerPage;
  const endIndex = startIndex + catalogItemsPerPage;
  const pageProducts = catalogFilteredProducts.slice(startIndex, endIndex);

  if (countEl) {
    if (totalItems === 0) {
      countEl.textContent = "0";
    } else {
      countEl.textContent = `${startIndex + 1}–${Math.min(endIndex, totalItems)} of ${totalItems}`;
    }
  }

  if (totalItems === 0) {
    grid.innerHTML = "";
    if (emptyEl) emptyEl.style.display = "block";
    if (paginationContainer) paginationContainer.innerHTML = "";
  } else {
    if (emptyEl) emptyEl.style.display = "none";
    grid.innerHTML = pageProducts.map(p => createProductCardHTML(p)).join("");

    // Render Pagination Controls
    if (paginationContainer) {
      if (totalPages <= 1) {
        paginationContainer.innerHTML = "";
      } else {
        let pagesHtml = `
          <button class="pagination-btn" onclick="changeCatalogPage(${catalogCurrentPage - 1})" ${catalogCurrentPage === 1 ? 'disabled' : ''}>
            <i class="fa-solid fa-chevron-left"></i> Prev
          </button>
        `;

        for (let p = 1; p <= totalPages; p++) {
          pagesHtml += `
            <button class="pagination-btn ${p === catalogCurrentPage ? 'active' : ''}" onclick="changeCatalogPage(${p})">
              ${p}
            </button>
          `;
        }

        pagesHtml += `
          <button class="pagination-btn" onclick="changeCatalogPage(${catalogCurrentPage + 1})" ${catalogCurrentPage === totalPages ? 'disabled' : ''}>
            Next <i class="fa-solid fa-chevron-right"></i>
          </button>
        `;

        paginationContainer.innerHTML = pagesHtml;
      }
    }
  }
}

let catalogBaseProductsCache = null;

async function applyStoreFilter(storeId) {
  const isRetail = (appState.shoppingMode === "RETAIL_NEAR_ME" || window.CURRENT_SHOPPING_MODE === "RETAIL_NEAR_ME");
  if (!isRetail) return;

  if (!catalogBaseProductsCache && appState.products && appState.products.length > 0) {
    catalogBaseProductsCache = [...appState.products];
  }

  if (!storeId) {
    if (catalogBaseProductsCache) {
      appState.products = [...catalogBaseProductsCache];
    }
    applyFilters();
    return;
  }

  try {
    const res = await fetch(`/api/stores/${storeId}/inventory`);
    const data = await res.json();
    if (data.inventory && Array.isArray(data.inventory)) {
      appState.products = data.inventory.map(item => ({
        id: item.product_id,
        title: item.title,
        brand: item.brand,
        category: item.category,
        sub_category: item.sub_category,
        price: item.selling_price !== undefined ? item.selling_price : item.price,
        original_price: item.original_price,
        stock: item.stock_quantity !== undefined ? item.stock_quantity : item.stock,
        is_available: item.is_available,
        image_url: item.image_url,
        rating: item.rating || 4.7,
        rating_count: item.rating_count || 120,
        description: item.description,
        sku: item.sku,
        store_id: item.store_id,
        store_name: data.store_name
      }));
      applyFilters();
    }
  } catch (err) {
    console.error("Store filter error:", err);
  }
}

function resetCatalogFilters() {
  const allCat = document.querySelector('input[name="cat_filter"][value=""]');
  if (allCat) allCat.checked = true;
  const allStore = document.querySelector('input[name="store_filter"][value=""]');
  if (allStore) allStore.checked = true;
  if (catalogBaseProductsCache) {
    appState.products = [...catalogBaseProductsCache];
  }
  const allPrice = document.querySelector('input[name="price_filter"][value="all"]');
  if (allPrice) allPrice.checked = true;
  if (document.getElementById("filter-rating-4")) document.getElementById("filter-rating-4").checked = false;
  if (document.getElementById("filter-rating-45")) document.getElementById("filter-rating-45").checked = false;
  if (document.getElementById("filter-in-stock-only")) document.getElementById("filter-in-stock-only").checked = false;
  if (document.getElementById("filter-hub-select")) document.getElementById("filter-hub-select").value = "All";
  applyFilters();
}

// -----------------------------------------------------------------------------
// 7. Search Autocomplete with OpenSearch API
// -----------------------------------------------------------------------------
let searchDebounceTimer = null;
async function handleSearchAutocomplete(query) {
  clearTimeout(searchDebounceTimer);
  const box = document.getElementById("search-suggestions-box");
  if (!box) return;

  if (!query || query.trim().length < 2) {
    box.style.display = "none";
    return;
  }

  searchDebounceTimer = setTimeout(async () => {
    try {
      const modeParam = appState.shoppingMode ? `&mode=${encodeURIComponent(appState.shoppingMode)}` : '';
      const storeParam = appState.selectedStoreId ? `&store_id=${encodeURIComponent(appState.selectedStoreId)}` : '';
      const res = await fetch(`/api/search/suggestions?q=${encodeURIComponent(query.trim())}${modeParam}${storeParam}`);
      const data = await res.json();
      const suggestions = data.suggestions || [];

      if (suggestions.length === 0) {
        box.style.display = "none";
        return;
      }

      box.innerHTML = suggestions.map(s => `
        <div class="suggestion-item" onclick="selectSearchSuggestion('${s.title.replace(/'/g, "\\'")}')">
          <div class="suggestion-left">
            <i class="fa-solid fa-magnifying-glass" style="color:var(--color-primary); font-size:12px;"></i>
            <span>${escapeHtml(s.title)}</span>
          </div>
          <div style="display:flex; align-items:center; gap:8px;">
            <span style="font-weight:700; color:var(--color-primary); font-size:12px;">₹${(s.selling_price || s.price || 0).toLocaleString('en-IN')}</span>
            <span class="suggestion-cat">${escapeHtml(s.category)}</span>
          </div>
        </div>
      `).join("");
      box.style.display = "block";
    } catch (err) {
      console.error("Suggestions error:", err);
      box.style.display = "none";
    }
  }, 250);
}

function selectSearchSuggestion(title) {
  const input = document.getElementById("header-search-input");
  if (input) input.value = title;
  const box = document.getElementById("search-suggestions-box");
  if (box) box.style.display = "none";
  if (appState.shoppingMode === "RETAIL_NEAR_ME") {
    window.location.href = `/products?q=${encodeURIComponent(title)}&mode=retail`;
  } else {
    window.location.href = `/products?q=${encodeURIComponent(title)}&mode=online`;
  }
}

document.addEventListener("click", (e) => {
  const box = document.getElementById("search-suggestions-box");
  if (box && !e.target.closest(".header-search-form")) {
    box.style.display = "none";
  }
});

// -----------------------------------------------------------------------------
// 8. Quick View Modal
// -----------------------------------------------------------------------------
let quickViewActiveQty = 1;

async function openQuickView(productId) {
  const modal = document.getElementById("quick-view-overlay");
  const content = document.getElementById("quick-view-content");
  if (!modal || !content) return;

  quickViewActiveQty = 1;

  let product = appState.products.find(p => p.id === productId);
  if (!product) {
    try {
      const res = await fetch(`/api/products/${productId}`);
      const data = await res.json();
      product = data.product;
    } catch (e) {
      console.error("QuickView fetch error:", e);
    }
  }
  if (!product) return;

  const isWishlisted = appState.wishlist.has(product.id);
  const discountPercent = product.original_price && product.original_price > product.price
    ? Math.round(((product.original_price - product.price) / product.original_price) * 100)
    : 0;

  let stockClass = "product-stock-tag";
  let stockText = `<i class="fa-solid fa-check"></i> In Stock (${product.stock} units available)`;
  if (product.stock <= 0) {
    stockClass += " out-stock";
    stockText = `<i class="fa-solid fa-circle-xmark"></i> Out of Stock`;
  } else if (product.stock <= 5) {
    stockClass += " low-stock";
    stockText = `<i class="fa-solid fa-triangle-exclamation"></i> Only ${product.stock} left in physical store`;
  }

  content.innerHTML = `
    <div style="height:340px; border-radius:var(--radius-lg); overflow:hidden; border:1px solid var(--color-border); background:var(--color-bg-subtle); position:relative;">
      ${discountPercent > 0 ? `<span class="product-badge-tag product-badge-deal" style="top:12px; left:12px;">${discountPercent}% OFF</span>` : ''}
      <button class="wishlist-float-btn ${isWishlisted ? 'active' : ''}" style="top:12px; right:12px;" onclick="toggleWishlist(${product.id}); this.classList.toggle('active');">
        <i class="${isWishlisted ? 'fa-solid fa-heart' : 'fa-regular fa-heart'}" style="${isWishlisted ? 'color:#E03131;' : ''}"></i>
      </button>
      <img src="${product.image_url}" alt="${product.title}" style="width:100%; height:100%; object-fit:cover;">
    </div>
    <div style="display:flex; flex-direction:column;">
      <span class="product-card-brand">${product.brand}</span>
      <h3 style="font-size:20px; line-height:1.3; margin-bottom:8px;">${product.title}</h3>
      
      <div class="product-card-rating" style="margin-bottom:12px;">
        <span class="star-rating"><i class="fa-solid fa-star"></i> ${product.rating}</span>
        <span class="rating-count-text">(${product.rating_count ? product.rating_count.toLocaleString() : '50+'} verified ratings)</span>
      </div>

      <div class="product-card-pricing" style="margin-bottom:12px;">
        <span class="current-price" style="font-size:24px;">₹${product.price.toLocaleString('en-IN')}</span>
        ${product.original_price && product.original_price > product.price ? `<span class="original-price" style="font-size:16px;">₹${product.original_price.toLocaleString('en-IN')}</span>` : ''}
        ${discountPercent > 0 ? `<span class="discount-percentage">${discountPercent}% off</span>` : ''}
      </div>

      <div class="${stockClass}" style="margin-bottom:14px;">
        ${stockText}
      </div>

      <p style="font-size:13px; color:var(--color-text-body); line-height:1.6; margin-bottom:16px; flex:1;">
        ${product.description}
      </p>

      <div style="display:flex; align-items:center; gap:12px; margin-bottom:16px;">
        <span style="font-size:13px; font-weight:600; color:var(--color-text-muted);">Quantity:</span>
        <div class="drawer-qty-control" style="background:var(--color-bg-subtle);">
          <button onclick="modifyQuickViewQty(-1, ${product.stock})">-</button>
          <span id="quick-view-qty-val">1</span>
          <button onclick="modifyQuickViewQty(1, ${product.stock})">+</button>
        </div>
      </div>

      <div style="display:flex; gap:12px;">
        <button class="btn-primary" style="flex:1; justify-content:center;" onclick="addToCart(${product.id}, quickViewActiveQty); closeQuickViewModal();" ${product.stock <= 0 ? 'disabled' : ''}>
          <i class="fa-solid fa-bag-shopping"></i> Add to Basket
        </button>
        <a href="/product/${product.id}" class="btn-secondary" style="padding:10px 18px;">
          Full Details &rarr;
        </a>
      </div>
    </div>
  `;
  modal.classList.add("open");
}

function modifyQuickViewQty(delta, maxStock) {
  quickViewActiveQty = Math.max(1, Math.min(maxStock || 50, quickViewActiveQty + delta));
  const el = document.getElementById("quick-view-qty-val");
  if (el) el.textContent = quickViewActiveQty;
}

function closeQuickViewModal(e) {
  const modal = document.getElementById("quick-view-overlay");
  if (modal) modal.classList.remove("open");
}

// -----------------------------------------------------------------------------
// 9. Detailed Cart Page (/cart) — Multi-Store Retail & Online Isolation
// -----------------------------------------------------------------------------
function renderCartPage() {
  const container = document.getElementById("cart-page-items-list");
  const countEl = document.getElementById("page-cart-item-count");
  const emptyView = document.getElementById("cart-empty-view");
  const contentWrapper = document.getElementById("cart-content-wrapper");
  if (!container) return;

  const items = Object.values(appState.cart);
  const totalCount = items.reduce((s, i) => s + (i.qty || 0), 0);
  if (countEl) countEl.textContent = totalCount;

  if (items.length === 0) {
    if (contentWrapper) contentWrapper.style.display = "none";
    if (emptyView) emptyView.style.display = "block";
    return;
  }

  if (contentWrapper) contentWrapper.style.display = "grid";
  if (emptyView) emptyView.style.display = "none";

  const isRetail = appState.shoppingMode === "RETAIL_NEAR_ME";

  // Hide or show Free shipping meter for online vs retail
  const meterBox = document.getElementById("shipping-meter-bar")?.closest('div[style*="background:var(--color-bg-surface)"]');
  if (meterBox) {
    meterBox.style.display = isRetail ? "none" : "block";
  }

  if (isRetail) {
    // -------------------------------------------------------------
    // Master Retail Cart View: Grouped by Shop with Per-Store Controls
    // -------------------------------------------------------------
    const shopMap = {};
    (appState.retailCarts || []).forEach(s => {
      shopMap[s.store_id] = {
        store_id: s.store_id,
        store_name: s.store_name,
        area: s.area || "",
        city: s.city || "",
        distance_km: s.distance_km || 2.5,
        delivery_fee: s.delivery_fee != null ? s.delivery_fee : 20.0,
        fulfillment: s.fulfillment || "delivery",
        items: []
      };
    });

    items.forEach(it => {
      const sId = it.store_id || 1;
      if (!shopMap[sId]) {
        shopMap[sId] = {
          store_id: sId,
          store_name: it.store_name || `Store #${sId}`,
          area: "Indiranagar",
          city: appState.currentCity || "Bengaluru",
          distance_km: 2.5,
          delivery_fee: 20.0,
          fulfillment: it.fulfillment || "delivery",
          items: []
        };
      }
      shopMap[sId].items.push(it);
    });

    const activeShops = Object.values(shopMap).filter(s => s.items.length > 0);

    if (activeShops.length === 0) {
      if (contentWrapper) contentWrapper.style.display = "none";
      if (emptyView) emptyView.style.display = "block";
      return;
    }

    if (!appState.selectedRetailStores) {
      appState.selectedRetailStores = new Set(activeShops.map(s => s.store_id));
    }

    let combinedSelectedSubtotal = 0;
    let combinedSelectedDelivery = 0;

    container.innerHTML = `
      <div style="margin-bottom:16px; padding:12px 16px; background:var(--color-bg-subtle); border-radius:var(--radius-md); font-size:13px; color:var(--color-text-main);">
        <i class="fa-solid fa-store" style="color:var(--color-primary); margin-right:6px;"></i>
        You have active baskets across <strong>${activeShops.length} neighbourhood retail store${activeShops.length > 1 ? 's' : ''}</strong>. Select the baskets you wish to checkout or checkout each store individually.
      </div>
      ${activeShops.map(shop => {
        const isSelected = appState.selectedRetailStores.has(shop.store_id);
        const shopSubtotal = shop.items.reduce((sum, it) => sum + (((it.product && it.product.price) || 0) * it.qty), 0);
        const fee = (shop.fulfillment === 'pickup') ? 0 : shop.delivery_fee;
        const shopTotal = shopSubtotal + fee;

        if (isSelected) {
          combinedSelectedSubtotal += shopSubtotal;
          combinedSelectedDelivery += fee;
        }

        return `
          <div class="retail-shop-basket-card" style="background:var(--color-bg-surface); border:1.5px solid ${isSelected ? 'var(--color-primary)' : 'var(--color-border)'}; border-radius:var(--radius-lg); padding:20px; margin-bottom:24px; box-shadow:var(--shadow-sm);">
            
            <!-- Store Header -->
            <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--color-border-subtle); padding-bottom:14px; margin-bottom:14px;">
              <div style="display:flex; align-items:center; gap:12px;">
                <input type="checkbox" id="check-store-${shop.store_id}" ${isSelected ? 'checked' : ''} onchange="toggleStoreCheckoutSelect(${shop.store_id})" style="width:18px; height:18px; cursor:pointer;" title="Include in multi-store checkout">
                <div>
                  <h3 style="font-size:16px; font-weight:700; margin:0 0 2px 0;">
                    <i class="fa-solid fa-shop" style="color:var(--color-primary);"></i> ${escapeHtml(shop.store_name)}
                  </h3>
                  <span style="font-size:12px; color:var(--color-text-muted);">
                    <i class="fa-solid fa-location-dot"></i> ${escapeHtml(shop.area)}, ${escapeHtml(shop.city)} &bull; Distance: <strong>${shop.distance_km} km</strong>
                  </span>
                </div>
              </div>

              <button class="btn-secondary" onclick="clearStoreBasket(${shop.store_id})" style="font-size:11.5px; padding:4px 9px; color:var(--color-danger); border-color:var(--color-danger-light);">
                <i class="fa-solid fa-trash-can"></i> Clear Store Basket
              </button>
            </div>

            <!-- Fulfillment Toggle -->
            <div style="background:var(--color-bg-subtle); padding:10px 14px; border-radius:var(--radius-md); margin-bottom:14px; display:flex; flex-wrap:wrap; gap:16px; align-items:center; font-size:12.5px;">
              <span style="font-weight:700; color:var(--color-text-main);"><i class="fa-solid fa-truck-fast"></i> Delivery Method:</span>
              <label style="display:flex; align-items:center; gap:6px; cursor:pointer;">
                <input type="radio" name="store_fulfill_${shop.store_id}" value="delivery" ${shop.fulfillment !== 'pickup' ? 'checked' : ''} onchange="updateShopFulfillment(${shop.store_id}, 'delivery')">
                <span>2-Hour Delivery (₹${shop.delivery_fee})</span>
              </label>
              <label style="display:flex; align-items:center; gap:6px; cursor:pointer;">
                <input type="radio" name="store_fulfill_${shop.store_id}" value="pickup" ${shop.fulfillment === 'pickup' ? 'checked' : ''} onchange="updateShopFulfillment(${shop.store_id}, 'pickup')">
                <span>Store Pickup (<strong style="color:var(--color-sage);">FREE ₹0</strong>)</span>
              </label>
            </div>

            <!-- Store Items List -->
            <div style="display:flex; flex-direction:column; gap:12px; margin-bottom:16px;">
              ${shop.items.map(it => {
                const p = it.product;
                const itTotal = (p.price || 0) * it.qty;
                return `
                  <div style="display:grid; grid-template-columns:64px 1fr auto auto; gap:16px; align-items:center; padding:10px 0; border-bottom:1px solid var(--color-border-subtle);">
                    <img src="${p.image_url}" alt="${p.title}" style="width:64px; height:64px; object-fit:contain; border-radius:var(--radius-sm); border:1px solid var(--color-border); padding:2px;">
                    <div>
                      <h4 style="font-size:13.5px; margin:0 0 4px 0;"><a href="/product/${p.id}">${escapeHtml(p.title)}</a></h4>
                      <span style="font-size:12px; color:var(--color-primary); font-weight:700;">₹${(p.price || 0).toLocaleString('en-IN')} / unit</span>
                      <div style="font-size:11px; color:var(--color-text-muted); margin-top:2px;">Store Stock: ${p.stock || 20} units</div>
                    </div>
                    <div style="display:flex; align-items:center; border:1px solid var(--color-border); border-radius:var(--radius-sm); overflow:hidden;">
                      <button onclick="updateCartItemQty('${it.id || it.key}', -1)" style="padding:4px 10px; background:var(--color-bg-subtle); border:none; cursor:pointer; font-weight:700;">-</button>
                      <span style="padding:4px 12px; font-weight:700; font-size:13px;">${it.qty}</span>
                      <button onclick="updateCartItemQty('${it.id || it.key}', 1)" style="padding:4px 10px; background:var(--color-bg-subtle); border:none; cursor:pointer; font-weight:700;">+</button>
                    </div>
                    <div style="text-align:right;">
                      <div style="font-size:15px; font-weight:800; color:var(--color-text-main);">₹${itTotal.toLocaleString('en-IN')}</div>
                      <button onclick="removeCartItem('${it.id || it.key}')" style="background:transparent; border:none; color:var(--color-danger); font-size:11px; cursor:pointer; margin-top:2px;">
                        <i class="fa-solid fa-trash-can"></i> Remove
                      </button>
                    </div>
                  </div>
                `;
              }).join("")}
            </div>

            <!-- Store Subtotal & Checkout This Store Action -->
            <div style="display:flex; justify-content:space-between; align-items:center; padding-top:12px; border-top:1px dashed var(--color-border);">
              <div>
                <span style="font-size:12px; color:var(--color-text-muted);">Basket Subtotal: ₹${shopSubtotal.toLocaleString('en-IN')} + Delivery: ₹${fee}</span>
                <div style="font-size:15px; font-weight:800; color:var(--color-primary);">Store Total: ₹${shopTotal.toLocaleString('en-IN')}</div>
              </div>
              <button class="btn-primary" onclick="checkoutSingleRetailStore(${shop.store_id})" style="font-size:12.5px; padding:8px 16px;">
                <i class="fa-solid fa-bag-shopping"></i> Checkout This Store Only
              </button>
            </div>

          </div>
        `;
      }).join("")}
    `;

    // Update Right Summary box for Multi-Store Retail
    const selectedCount = appState.selectedRetailStores.size;
    const grandTotal = combinedSelectedSubtotal + combinedSelectedDelivery;

    document.getElementById("summary-subtotal").textContent = `₹${combinedSelectedSubtotal.toLocaleString('en-IN')}`;
    document.getElementById("summary-discount").textContent = "-₹0";
    document.getElementById("summary-shipping").textContent = `₹${combinedSelectedDelivery.toLocaleString('en-IN')}`;
    document.getElementById("summary-grand-total").textContent = `₹${grandTotal.toLocaleString('en-IN')}`;

    const checkoutBtn = document.querySelector('#cart-content-wrapper a[href*="checkout"]') || document.querySelector('#cart-content-wrapper button[onclick*="Checkout"]');
    if (checkoutBtn) {
      checkoutBtn.setAttribute("href", "javascript:void(0)");
      checkoutBtn.setAttribute("onclick", "proceedToRetailMultiStoreCheckout()");
      checkoutBtn.innerHTML = `<i class="fa-solid fa-lock"></i> Checkout Selected Stores (${selectedCount})`;
      checkoutBtn.style.opacity = selectedCount > 0 ? "1" : "0.5";
      checkoutBtn.style.pointerEvents = selectedCount > 0 ? "auto" : "none";
    }

  } else {
    // -------------------------------------------------------------
    // Online Shopping Mode Standard Cart
    // -------------------------------------------------------------
    let subtotal = 0;
    container.innerHTML = items.map(item => {
      const p = item.product;
      const itemTotal = ((p && p.price) || 0) * item.qty;
      subtotal += itemTotal;
      return `
        <div style="display:grid; grid-template-columns:80px 1fr auto auto; gap:20px; align-items:center; padding-bottom:18px; margin-bottom:18px; border-bottom:1px solid var(--color-border-subtle);">
          <img src="${p.image_url}" alt="${p.title}" style="width:80px; height:80px; object-fit:cover; border-radius:var(--radius-md); border:1px solid var(--color-border);">
          <div>
            <span style="font-size:11px; text-transform:uppercase; font-weight:700; color:var(--color-primary);">${p.brand || 'Authentic'}</span>
            <h4 style="font-size:14.5px; font-weight:600; margin-bottom:4px;"><a href="/product/${p.id}">${escapeHtml(p.title)}</a></h4>
            <span style="font-size:11.5px; color:var(--color-sage);"><i class="fa-solid fa-boxes-stacked"></i> Catalog Stock: ${p.stock || 20} units</span>
          </div>
          <div style="display:flex; align-items:center; border:1px solid var(--color-border); border-radius:var(--radius-sm); overflow:hidden;">
            <button onclick="updateCartItemQty('${item.id || p.id}', -1)" style="padding:6px 12px; background:var(--color-bg-subtle); border:none; cursor:pointer; font-weight:700;">-</button>
            <span style="padding:6px 14px; font-weight:700; font-size:13px;">${item.qty}</span>
            <button onclick="updateCartItemQty('${item.id || p.id}', 1)" style="padding:6px 12px; background:var(--color-bg-subtle); border:none; cursor:pointer; font-weight:700;">+</button>
          </div>
          <div style="text-align:right;">
            <div style="font-size:16px; font-weight:800; color:var(--color-text-main);">₹${itemTotal.toLocaleString('en-IN')}</div>
            <button onclick="removeCartItem('${item.id || p.id}')" style="background:transparent; border:none; color:var(--color-danger); font-size:12px; cursor:pointer; margin-top:4px;">
              <i class="fa-solid fa-trash-can"></i> Remove
            </button>
          </div>
        </div>
      `;
    }).join("");

    // Update Free shipping meter (Threshold: ₹499)
    const meterBar = document.getElementById("shipping-meter-bar");
    const meterVal = document.getElementById("shipping-meter-val");
    const meterText = document.getElementById("shipping-meter-text");
    if (meterBar && meterVal && meterText) {
      if (subtotal >= 499) {
        meterBar.style.width = "100%";
        meterVal.textContent = "100%";
        meterText.innerHTML = `<i class="fa-solid fa-circle-check" style="color:var(--color-sage);"></i> Congratulations! You've unlocked FREE Physical Hub Delivery!`;
      } else {
        const pct = Math.round((subtotal / 499) * 100);
        const remaining = 499 - subtotal;
        meterBar.style.width = `${pct}%`;
        meterVal.textContent = `${pct}%`;
        meterText.innerHTML = `<i class="fa-solid fa-truck-fast"></i> Add ₹${remaining.toLocaleString('en-IN')} more to unlock FREE Hub Delivery!`;
      }
    }

    let discount = 0;
    if (appState.activeCoupon === "BHARAT10") {
      discount = Math.round(subtotal * 0.1);
    }

    document.getElementById("summary-subtotal").textContent = `₹${subtotal.toLocaleString('en-IN')}`;
    document.getElementById("summary-discount").textContent = `-₹${discount.toLocaleString('en-IN')}`;
    document.getElementById("summary-shipping").textContent = "FREE";
    document.getElementById("summary-grand-total").textContent = `₹${(subtotal - discount).toLocaleString('en-IN')}`;

    const checkoutBtn = document.querySelector('#cart-content-wrapper a[href*="checkout"]') || document.querySelector('#cart-content-wrapper button[onclick*="Checkout"]');
    if (checkoutBtn) {
      checkoutBtn.setAttribute("href", "/checkout?mode=online");
      checkoutBtn.removeAttribute("onclick");
      checkoutBtn.innerHTML = `<i class="fa-solid fa-lock"></i> Proceed to Checkout`;
      checkoutBtn.style.opacity = "1";
      checkoutBtn.style.pointerEvents = "auto";
    }
  }
}

function toggleStoreCheckoutSelect(storeId) {
  if (!appState.selectedRetailStores) {
    appState.selectedRetailStores = new Set();
  }
  const sId = Number(storeId);
  if (appState.selectedRetailStores.has(sId)) {
    appState.selectedRetailStores.delete(sId);
  } else {
    appState.selectedRetailStores.add(sId);
  }
  renderCartPage();
}

function checkoutSingleRetailStore(storeId) {
  window.location.href = `/checkout?mode=retail&store_id=${storeId}`;
}

function proceedToRetailMultiStoreCheckout() {
  const selected = Array.from(appState.selectedRetailStores || []);
  if (selected.length === 0) {
    alert("Please select at least one store basket for checkout.");
    return;
  }
  window.location.href = `/checkout?mode=retail&stores=${selected.join(",")}`;
}

function applyCouponCode() {
  const code = (document.getElementById("coupon-code-input")?.value || "").toUpperCase().trim();
  if (code === "BHARAT10") {
    appState.activeCoupon = code;
    showToast("Coupon BHARAT10 applied! 10% discount added.");
    renderCartPage();
  } else {
    alert("Invalid promo code. Use code BHARAT10 for 10% instant off!");
  }
}

// -----------------------------------------------------------------------------
// 10. Wishlist Page (/wishlist)
// -----------------------------------------------------------------------------
async function renderWishlistPage() {
  const grid = document.getElementById("wishlist-products-grid");
  const countEl = document.getElementById("page-wishlist-count");
  const emptyView = document.getElementById("wishlist-empty-view");
  if (!grid) return;

  if (appState.products.length === 0) {
    const res = await fetch("/api/products");
    const data = await res.json();
    appState.products = data.products || [];
  }

  const savedList = appState.products.filter(p => appState.wishlist.has(p.id));
  if (countEl) countEl.textContent = savedList.length;

  if (savedList.length === 0) {
    grid.innerHTML = "";
    if (emptyView) emptyView.style.display = "block";
  } else {
    if (emptyView) emptyView.style.display = "none";
    grid.innerHTML = savedList.map(p => createProductCardHTML(p)).join("");
  }
}

// -----------------------------------------------------------------------------
// 11. Checkout & Transactional ACID Execution (/checkout) — Multi-Store Support
// -----------------------------------------------------------------------------
async function initCheckoutPage() {
  const container = document.getElementById("checkout-items-preview");
  const subtotalEl = document.getElementById("checkout-subtotal");
  const totalEl = document.getElementById("checkout-grand-total");
  const btn = document.getElementById("btn-submit-order");
  if (!container) return;

  container.innerHTML = `
    <div style="text-align:center; padding:24px 12px; color:var(--color-text-muted); font-size:13px;">
      <i class="fa-solid fa-spinner fa-spin" style="color:var(--color-primary); font-size:18px; margin-bottom:8px;"></i>
      <div>Loading your store baskets & calculating totals...</div>
    </div>
  `;

  if (typeof initShoppingMode === "function") {
    await initShoppingMode();
  }

  const urlParams = new URLSearchParams(window.location.search);
  let checkoutMode = urlParams.get("mode");
  if (!checkoutMode) {
    checkoutMode = (appState.shoppingMode === "RETAIL_NEAR_ME") ? "retail" : "online";
  } else {
    checkoutMode = checkoutMode.toLowerCase();
  }

  let retailShops = [];
  let onlineItems = [];

  if (checkoutMode === "retail") {
    try {
      let locParams = "";
      if (appState.deliveryLocation && appState.deliveryLocation.latitude && appState.deliveryLocation.longitude) {
        locParams = `?customer_lat=${appState.deliveryLocation.latitude}&customer_lng=${appState.deliveryLocation.longitude}`;
      }
      const res = await fetch(`/api/cart/retail${locParams}`);
      if (res.ok) {
        const data = await res.json();
        retailShops = data.shops || [];
        appState.retailCarts = retailShops;
      }
    } catch (e) {
      console.error("Retail checkout sync error:", e);
    }

    // Auto-detect fallback if retail cart is empty and mode wasn't explicitly set in URL
    if (retailShops.length === 0 && !urlParams.get("mode")) {
      try {
        const resO = await fetch("/api/cart/online");
        if (resO.ok) {
          const dataO = await resO.json();
          const oItems = (dataO.cart && dataO.cart.items) || [];
          if (oItems.length > 0) {
            checkoutMode = "online";
            onlineItems = oItems;
          }
        }
      } catch (e) {}
    }
  } else {
    try {
      const resO = await fetch("/api/cart/online");
      if (resO.ok) {
        const dataO = await resO.json();
        onlineItems = (dataO.cart && dataO.cart.items) || [];
      }
    } catch (e) {
      console.error("Online checkout sync error:", e);
    }

    // Auto-detect fallback if online cart is empty and mode wasn't explicitly set in URL
    if (onlineItems.length === 0 && !urlParams.get("mode")) {
      try {
        const resR = await fetch("/api/cart/retail");
        if (resR.ok) {
          const dataR = await resR.json();
          const rShops = dataR.shops || [];
          if (rShops.length > 0) {
            checkoutMode = "retail";
            retailShops = rShops;
            appState.retailCarts = retailShops;
          }
        }
      } catch (e) {}
    }
  }

  if (checkoutMode === "retail") {
    const urlStoreId = urlParams.get("store_id");
    const urlStores = urlParams.get("stores");
    let targetStoreIds = null;
    if (urlStoreId) {
      targetStoreIds = [Number(urlStoreId)];
    } else if (urlStores) {
      targetStoreIds = urlStores.split(",").map(Number);
    }

    let activeShops = retailShops.filter(s => (s.items || []).length > 0);
    if (targetStoreIds && targetStoreIds.length > 0) {
      activeShops = activeShops.filter(s => targetStoreIds.includes(s.store_id));
    }

    if (activeShops.length === 0) {
      container.innerHTML = `<p style="font-size:13px; color:var(--color-text-muted);">No items in selected store basket. <a href="/retail" style="color:var(--color-primary); font-weight:700;">Browse Retail Near Me</a></p>`;
      if (btn) btn.disabled = true;
      if (subtotalEl) subtotalEl.textContent = "₹0";
      if (totalEl) totalEl.textContent = "₹0";
      return;
    }

    let combinedSubtotal = 0;
    let combinedDelivery = 0;

    container.innerHTML = activeShops.map(st => {
      const isPickup = (st.fulfillment === "pickup" || st.fulfillment_type === "pickup");
      const fee = isPickup ? 0 : (st.delivery_fee != null ? st.delivery_fee : 20.0);
      combinedSubtotal += st.subtotal;
      combinedDelivery += fee;

      return `
        <div class="checkout-store-basket-card" style="background:var(--color-bg-base); padding:12px 14px; border-radius:var(--radius-md); border:1px solid var(--color-border); margin-bottom:12px;">
          <div style="display:flex; justify-content:space-between; align-items:center; font-weight:700; font-size:13px; margin-bottom:8px; color:var(--color-primary); border-bottom:1px solid var(--color-border-subtle); padding-bottom:6px;">
            <span><i class="fa-solid fa-shop"></i> ${escapeHtml(st.store_name)}</span>
            <span>Subtotal: ₹${st.subtotal.toLocaleString('en-IN')}</span>
          </div>
          ${(st.items || []).map(it => `
            <div style="display:flex; justify-content:space-between; align-items:center; font-size:12px; color:var(--color-text-body); padding:4px 0; gap:8px;">
              <span style="flex:1; word-break:break-word; overflow-wrap:anywhere; white-space:normal;">
                <strong>${it.quantity}x</strong> ${escapeHtml(it.title)}
              </span>
              <strong style="white-space:nowrap; color:var(--color-text-main);">₹${((it.unit_price || 0) * it.quantity).toLocaleString('en-IN')}</strong>
            </div>
          `).join("")}
          <div style="display:flex; justify-content:space-between; font-size:11.5px; color:var(--color-text-muted); margin-top:8px; padding-top:6px; border-top:1px dashed var(--color-border);">
            <span>Fulfillment (${isPickup ? 'Store Counter Pickup' : 'Hyperlocal 2-Hour Delivery'})</span>
            <span style="font-weight:700; color:${fee === 0 ? 'var(--color-sage)' : 'var(--color-primary)'};">${fee === 0 ? 'FREE' : '₹' + fee}</span>
          </div>
        </div>
      `;
    }).join("");

    if (subtotalEl) subtotalEl.textContent = `₹${combinedSubtotal.toLocaleString('en-IN')}`;
    const grandTotal = combinedSubtotal + combinedDelivery;
    if (totalEl) totalEl.textContent = `₹${grandTotal.toLocaleString('en-IN')}`;
    if (btn) btn.disabled = false;

  } else {
    if (onlineItems.length === 0) {
      container.innerHTML = `<p style="font-size:13px; color:var(--color-text-muted);">No items in cart. <a href="/products" style="color:var(--color-primary); font-weight:700;">Browse catalog</a></p>`;
      if (btn) btn.disabled = true;
      if (subtotalEl) subtotalEl.textContent = "₹0";
      if (totalEl) totalEl.textContent = "₹0";
      return;
    }

    let subtotal = 0;
    container.innerHTML = onlineItems.map(it => {
      const itemTotal = (it.unit_price || 0) * it.quantity;
      subtotal += itemTotal;
      return `
        <div style="display:flex; justify-content:space-between; align-items:center; font-size:12.5px; padding:4px 0; gap:8px;">
          <span style="flex:1; word-break:break-word; overflow-wrap:anywhere; white-space:normal;">
            <strong>${it.quantity}x</strong> ${escapeHtml(it.title)}
          </span>
          <strong style="white-space:nowrap; color:var(--color-text-main);">₹${itemTotal.toLocaleString('en-IN')}</strong>
        </div>
      `;
    }).join("");

    if (subtotalEl) subtotalEl.textContent = `₹${subtotal.toLocaleString('en-IN')}`;
    if (totalEl) totalEl.textContent = `₹${subtotal.toLocaleString('en-IN')}`;
    if (btn) btn.disabled = false;
  }

  // Phase 3: Load Saved Addresses into Checkout
  await loadCheckoutSavedAddresses();
}

async function loadCheckoutSavedAddresses() {
  const container = document.getElementById("checkout-saved-addresses-list");
  if (!container) return;

  try {
    const res = await fetch("/api/customer/addresses");
    const data = await res.json();
    if (!data.success || !data.addresses || data.addresses.length === 0) {
      container.innerHTML = `
        <div style="font-size:12px; color:var(--color-text-muted); background:var(--color-bg-base); padding:10px 14px; border-radius:var(--radius-sm); border:1px dashed var(--color-border);">
          No saved addresses found. Using active delivery location details below.
        </div>
      `;
      prefillGuestCheckoutLocation();
      return;
    }

    window.checkoutSavedAddressesList = data.addresses;
    let defaultAddr = data.addresses.find(a => a.is_default) || data.addresses[0];

    container.innerHTML = data.addresses.map((a) => `
      <label style="display:flex; align-items:flex-start; gap:10px; padding:10px 14px; border:1.5px solid ${a.id === defaultAddr.id ? 'var(--color-primary)' : 'var(--color-border)'}; border-radius:var(--radius-md); background:${a.id === defaultAddr.id ? 'var(--color-primary-light)' : 'var(--color-bg-base)'}; cursor:pointer;" class="checkout-addr-radio-label" id="checkout-addr-card-${a.id}">
        <input type="radio" name="checkout_saved_addr" value="${a.id}" ${a.id === defaultAddr.id ? 'checked' : ''} onchange="selectSavedAddressForCheckout(${a.id})" style="margin-top:3px;">
        <div style="flex:1;">
          <div style="display:flex; align-items:center; gap:8px;">
            <strong style="font-size:13px; color:var(--color-text-main);">${escapeHtml(a.full_name)}</strong>
            <span class="badge-status badge-confirmed" style="font-size:10px; font-weight:800;">${a.address_type}</span>
            ${a.is_default ? '<span style="background:var(--color-primary); color:#FFF; font-size:9px; font-weight:800; padding:1px 6px; border-radius:var(--radius-full);">DEFAULT</span>' : ''}
          </div>
          <p style="font-size:12px; color:var(--color-text-body); margin-top:2px; line-height:1.4;">
            ${escapeHtml(a.address_line1)}${a.address_line2 ? ', ' + escapeHtml(a.address_line2) : ''}, ${escapeHtml(a.city)} — ${escapeHtml(a.pincode)} &bull; Tel: ${escapeHtml(a.phone)}
          </p>
        </div>
      </label>
    `).join("");

    if (defaultAddr) {
      applyAddressToCheckoutForm(defaultAddr);
    }
  } catch (err) {
    console.error("Error loading checkout addresses:", err);
    prefillGuestCheckoutLocation();
  }
}

function selectSavedAddressForCheckout(addrId) {
  const addr = (window.checkoutSavedAddressesList || []).find(a => a.id === addrId);
  if (!addr) return;

  document.querySelectorAll(".checkout-addr-radio-label").forEach(el => {
    el.style.borderColor = "var(--color-border)";
    el.style.background = "var(--color-bg-base)";
  });
  const selectedCard = document.getElementById(`checkout-addr-card-${addrId}`);
  if (selectedCard) {
    selectedCard.style.borderColor = "var(--color-primary)";
    selectedCard.style.background = "var(--color-primary-light)";
  }

  applyAddressToCheckoutForm(addr);
}

function applyAddressToCheckoutForm(addr) {
  const nameEl = document.getElementById("checkout-customer-name");
  const phoneEl = document.getElementById("checkout-customer-phone");
  const addrEl = document.getElementById("checkout-shipping-address");
  const cityEl = document.getElementById("checkout-shipping-city");
  const pinEl = document.getElementById("checkout-pincode");

  if (nameEl) nameEl.value = addr.full_name;
  if (phoneEl) phoneEl.value = addr.phone;
  if (addrEl) {
    addrEl.value = `${addr.address_line1}${addr.address_line2 ? ', ' + addr.address_line2 : ''}${addr.landmark ? ' (' + addr.landmark + ')' : ''}`;
  }
  if (cityEl) {
    cityEl.value = addr.city;
    updateCheckoutCity(addr.city);
  }
  if (pinEl) pinEl.value = addr.pincode;
}

function selectNewAddressOption() {
  document.querySelectorAll('input[name="checkout_saved_addr"]').forEach(r => r.checked = false);
  document.querySelectorAll(".checkout-addr-radio-label").forEach(el => {
    el.style.borderColor = "var(--color-border)";
    el.style.background = "var(--color-bg-base)";
  });
  const nameEl = document.getElementById("checkout-customer-name");
  const addrEl = document.getElementById("checkout-shipping-address");
  const pinEl = document.getElementById("checkout-pincode");
  if (nameEl) nameEl.focus();
  if (addrEl) addrEl.value = "";
  if (pinEl) pinEl.value = "";
  showToast("Enter your delivery address below.");
}

async function prefillGuestCheckoutLocation() {
  try {
    const res = await fetch("/api/location/current");
    const data = await res.json();
    if (data.success && data.location) {
      const loc = data.location;
      const cityEl = document.getElementById("checkout-shipping-city");
      const pinEl = document.getElementById("checkout-pincode");
      const addrEl = document.getElementById("checkout-shipping-address");
      if (cityEl && loc.city) {
        cityEl.value = loc.city;
        updateCheckoutCity(loc.city);
      }
      if (pinEl && loc.pincode) pinEl.value = loc.pincode;
      if (addrEl && loc.address_line) addrEl.value = loc.address_line;
    }
  } catch (e) {}
}

function updateCheckoutCity(cityName) {
  appState.currentCity = cityName;
  localStorage.setItem("bharatstore_selected_city", cityName);
}

let placedOrderRef = null;

async function placeOrderFromCheckout() {
  const urlParams = new URLSearchParams(window.location.search);
  const checkoutMode = urlParams.get("mode") || (appState.shoppingMode === "RETAIL_NEAR_ME" ? "retail" : "online");

  const customerName = document.getElementById("checkout-customer-name")?.value || "Priya Sharma";
  const customerEmail = document.getElementById("checkout-customer-email")?.value || "priya.sharma@example.in";
  const customerPhone = document.getElementById("checkout-customer-phone")?.value || "+91 98201 12345";
  const shippingAddress = document.getElementById("checkout-shipping-address")?.value || "Flat 402, Sea Green Apts, Worli Sea Face";
  const shippingCity = document.getElementById("checkout-shipping-city")?.value || "Bengaluru";
  const paymentMethod = document.querySelector('input[name="checkout_payment_method"]:checked')?.value || "UPI";

  // Open Transaction Monitor Modal
  const modal = document.getElementById("tx-modal-overlay");
  if (modal) modal.classList.add("open");

  setTxStep("step-db", "PostgreSQL: Acquiring Row Lock (SELECT ... FOR UPDATE)...");

  if (checkoutMode === "retail") {
    const urlStoreId = urlParams.get("store_id");
    const urlStores = urlParams.get("stores");
    let targetStoreIds = null;
    if (urlStoreId) {
      targetStoreIds = [Number(urlStoreId)];
    } else if (urlStores) {
      targetStoreIds = urlStores.split(",").map(Number);
    } else if (appState.selectedRetailStores && appState.selectedRetailStores.size > 0) {
      targetStoreIds = Array.from(appState.selectedRetailStores);
    } else if (appState.retailCarts && appState.retailCarts.length > 0) {
      targetStoreIds = appState.retailCarts.filter(s => (s.items || []).length > 0).map(s => s.store_id);
    } else {
      targetStoreIds = Array.from(new Set(Object.values(appState.cart).map(it => it.store_id || 1)));
    }

    try {
      const res = await fetch("/api/checkout/retail/multi-store", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          selected_store_ids: targetStoreIds,
          customer_info: {
            name: customerName,
            email: customerEmail,
            phone: customerPhone,
            address: shippingAddress,
            city: shippingCity
          },
          delivery_address: {
            formatted: shippingAddress,
            city: shippingCity,
            latitude: appState.deliveryLocation?.latitude || 12.9784,
            longitude: appState.deliveryLocation?.longitude || 77.6408
          },
          payment_method: paymentMethod
        })
      });

      const data = await res.json();
      if (!res.ok || !data.success) {
        setTxStep("step-db", `ROLLBACK: ${data.error || 'Checkout failed.'}`, true);
        alert(`Checkout failed: ${data.error || 'Unknown error'}`);
        return;
      }

      placedOrderRef = {
        order_id: data.parent_order_id,
        order_number: data.parent_order_number
      };

      setTxStep("step-db", `COMMITTED: Master Order #${data.parent_order_number} (${data.stores_count} store suborders, 0 Overselling)`);

      setTimeout(() => {
        setTxStep("step-state", `Parent Order and ${data.stores_count} suborders registered in 'CONFIRMED' status.`);
      }, 400);

      setTimeout(async () => {
        setTxStep("step-kafka", `Published event '${data.kafka_event?.event_id || 'EVT-RET-ORDER'}' to topic 'order-events'`);
        const finishBtn = document.getElementById("btn-tx-finish");
        if (finishBtn) finishBtn.style.display = "inline-flex";

        await syncCartWithBackend();
      }, 800);

    } catch (err) {
      setTxStep("step-db", `Network error: ${err.message}`, true);
    }

  } else {
    // Online checkout
    try {
      const res = await fetch("/api/checkout/online", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          customer_info: {
            name: customerName,
            email: customerEmail,
            phone: customerPhone,
            address: shippingAddress,
            city: shippingCity
          },
          payment_method: paymentMethod
        })
      });

      const data = await res.json();
      if (!res.ok || !data.success) {
        setTxStep("step-db", `ROLLBACK: ${data.error || 'Checkout failed.'}`, true);
        alert(`Checkout failed: ${data.error || 'Unknown error'}`);
        return;
      }

      const ord = data.order || {};
      placedOrderRef = {
        order_id: ord.order_id || ord.id,
        order_number: ord.order_number
      };

      setTxStep("step-db", `COMMITTED: Order #${ord.order_number} (0 Overselling)`);

      setTimeout(() => {
        setTxStep("step-state", `Order registered in '${ord.status}' status with stock reserved.`);
      }, 400);

      setTimeout(async () => {
        setTxStep("step-kafka", `Published event '${ord.kafka_event?.event_id || 'EVT-ONLINE-ORDER'}' to topic 'order-events'`);
        const finishBtn = document.getElementById("btn-tx-finish");
        if (finishBtn) finishBtn.style.display = "inline-flex";

        await syncCartWithBackend();
      }, 800);

    } catch (err) {
      setTxStep("step-db", `Network error: ${err.message}`, true);
    }
  }
}

async function logoutUser() {
  try {
    await fetch("/api/auth/logout", { method: "POST" });
  } catch (e) {}
  localStorage.removeItem("bharatstore_retail_cart");
  localStorage.removeItem("bharatstore_online_cart");
  localStorage.removeItem("bharatstore_cart");
  appState.cart = {};
  appState.retailCart = {};
  appState.onlineCart = {};
  appState.retailCarts = [];
  updateHeaderBadges();
  renderCartDrawer();
  window.location.href = "/login";
}

function setTxStep(stepId, text, isError = false) {
  const el = document.getElementById(stepId);
  if (!el) return;
  const p = el.querySelector("p");
  if (p) {
    p.textContent = text;
    p.style.color = isError ? "var(--color-danger)" : "var(--color-text-main)";
    p.style.fontWeight = isError ? "700" : "500";
  }
}

function closeTxModal() {
  const modal = document.getElementById("tx-modal-overlay");
  if (modal) modal.classList.remove("open");
}

function redirectToOrderConfirmation() {
  if (placedOrderRef) {
    location.href = `/order/${placedOrderRef.order_id}`;
  } else {
    location.href = "/orders";
  }
}

// -----------------------------------------------------------------------------
// 12. Order History Page (/orders)
// -----------------------------------------------------------------------------
let allLoadedOrders = [];

async function loadUserOrders() {
  const container = document.getElementById("orders-page-list-container");
  const emptyEl = document.getElementById("orders-empty-state");
  if (!container) return;

  try {
    const res = await fetch("/api/orders?limit=50");
    const data = await res.json();
    allLoadedOrders = data.orders || [];

    if (allLoadedOrders.length === 0) {
      container.innerHTML = "";
      if (emptyEl) emptyEl.style.display = "block";
    } else {
      if (emptyEl) emptyEl.style.display = "none";
      renderOrdersList(allLoadedOrders);
    }
  } catch (err) {
    console.error("Error loading orders:", err);
  }
}

function renderOrdersList(list) {
  const container = document.getElementById("orders-page-list-container");
  if (!container) return;

  if (!list || list.length === 0) {
    container.innerHTML = `
      <div style="text-align:center; padding:56px 20px; background:var(--color-bg-surface); border-radius:var(--radius-xl); border:1px solid var(--color-border); max-width:600px; margin:auto;">
        <i class="fa-solid fa-box-open" style="font-size:48px; color:var(--color-border-strong); margin-bottom:14px;"></i>
        <h4 style="font-size:16px; margin-bottom:6px;">No Orders in this Status</h4>
        <p style="color:var(--color-text-muted); font-size:13px; margin:0 0 18px 0;">There are no active orders matching the selected lifecycle filter.</p>
        <button class="btn-secondary" onclick="filterOrdersTab('all')" style="font-size:12.5px;">View All Orders</button>
      </div>
    `;
    return;
  }

  container.innerHTML = list.map(o => {
    let statusClass = "badge-pending";
    const st = (o.status || "PENDING").toUpperCase();
    if (st === "CONFIRMED") statusClass = "badge-confirmed";
    else if (st === "PROCESSING") statusClass = "badge-confirmed";
    else if (st === "DISPATCHED" || st === "SHIPPED" || st === "OUT_FOR_DELIVERY") statusClass = "badge-confirmed";
    else if (st === "DELIVERED") statusClass = "badge-confirmed";
    else if (st === "CANCELLED") statusClass = "badge-cancelled";

    const isRetail = (o.shopping_mode === "RETAIL_NEAR_ME");
    const modeBadge = isRetail
      ? `<span style="background:#ECFDF5; color:#059669; border:1px solid #A7F3D0; font-size:10.5px; font-weight:700; padding:2px 7px; border-radius:4px;"><i class="fa-solid fa-store"></i> RETAIL NEAR ME</span>`
      : `<span style="background:#EFF6FF; color:#2563EB; border:1px solid #BFDBFE; font-size:10.5px; font-weight:700; padding:2px 7px; border-radius:4px;"><i class="fa-solid fa-globe"></i> ONLINE MARKETPLACE</span>`;

    // Multi-store or store badges
    let storesHtml = "";
    if (o.suborders && o.suborders.length > 0) {
      storesHtml = `
        <div style="display:flex; flex-wrap:wrap; gap:6px; margin-top:6px;">
          ${o.suborders.map(s => `
            <span style="font-size:11px; background:var(--color-bg-subtle); border:1px solid var(--color-border); padding:2px 8px; border-radius:4px; color:var(--color-text-main);">
              <i class="fa-solid fa-shop" style="color:var(--color-primary);"></i> ${escapeHtml(s.store_name || ('Store #' + s.store_id))}
            </span>
          `).join("")}
        </div>
      `;
    } else if (o.store_name) {
      storesHtml = `
        <div style="margin-top:6px;">
          <span style="font-size:11px; background:var(--color-bg-subtle); border:1px solid var(--color-border); padding:2px 8px; border-radius:4px; color:var(--color-text-main);">
            <i class="fa-solid fa-shop" style="color:var(--color-primary);"></i> ${escapeHtml(o.store_name)}
          </span>
        </div>
      `;
    }

    // Items preview
    let itemsPreview = "";
    if (o.items && o.items.length > 0) {
      itemsPreview = `
        <div style="display:flex; flex-wrap:wrap; gap:6px; margin-top:10px;">
          ${o.items.slice(0, 4).map(i => `
            <span style="font-size:11.5px; background:var(--color-bg-subtle); border:1px solid var(--color-border-subtle); padding:2px 8px; border-radius:4px; color:var(--color-text-body);">
              ${escapeHtml(i.title || i.product_title || 'Item')} <strong style="color:var(--color-text-main);">× ${i.quantity}</strong>
            </span>
          `).join("")}
          ${o.items.length > 4 ? `<span style="font-size:11px; color:var(--color-text-muted); align-self:center;">+${o.items.length - 4} more</span>` : ''}
        </div>
      `;
    }

    return `
      <div style="background:var(--color-bg-surface); border:1px solid var(--color-border); border-radius:var(--radius-xl); overflow:hidden; box-shadow:var(--shadow-sm);">
        <div style="background:var(--color-bg-subtle); padding:16px 24px; display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--color-border); font-size:12.5px; flex-wrap:wrap; gap:12px;">
          <div style="display:flex; gap:24px; flex-wrap:wrap;">
            <div>
              <span style="color:var(--color-text-muted); display:block; font-size:11px; text-transform:uppercase;">ORDER PLACED</span>
              <strong>${o.created_at || 'Just now'}</strong>
            </div>
            <div>
              <span style="color:var(--color-text-muted); display:block; font-size:11px; text-transform:uppercase;">TOTAL AMOUNT</span>
              <strong style="color:var(--color-primary); font-size:14px;">₹${Number(o.total_amount).toLocaleString('en-IN')}</strong>
            </div>
            <div>
              <span style="color:var(--color-text-muted); display:block; font-size:11px; text-transform:uppercase;">FULFILLMENT MODE</span>
              <div style="margin-top:2px;">${modeBadge}</div>
            </div>
          </div>
          <div>
            <span style="color:var(--color-text-muted); font-size:11px;">ORDER # <strong>${o.order_number}</strong></span>
          </div>
        </div>

        <div style="padding:20px 24px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:16px;">
          <div style="flex:1; min-width:280px;">
            <div style="display:flex; align-items:center; gap:10px; margin-bottom:8px; flex-wrap:wrap;">
              <span class="badge-status ${statusClass}" style="font-weight:700;">${o.status}</span>
              <span style="font-size:12px; color:var(--color-text-muted);">
                Payment: <strong style="color:var(--color-text-main);">${o.payment_status || 'PENDING'}</strong> (${o.payment_method || 'UPI'})
              </span>
            </div>
            ${storesHtml}
            ${itemsPreview}
          </div>
          <div style="display:flex; gap:10px;">
            <a href="/order/${o.id}" class="btn-primary" style="font-size:13px; padding:9px 18px; text-decoration:none;">
              <i class="fa-solid fa-receipt"></i> View Order Details
            </a>
          </div>
        </div>
      </div>
    `;
  }).join("");
}

function filterOrdersTab(status, btnElement) {
  if (btnElement) {
    btnElement.parentElement.querySelectorAll("button").forEach(b => {
      b.style.backgroundColor = "transparent";
      b.style.color = "var(--color-text-main)";
      b.style.borderColor = "var(--color-border)";
    });
    btnElement.style.backgroundColor = "var(--color-primary-light)";
    btnElement.style.color = "var(--color-primary)";
    btnElement.style.borderColor = "var(--color-primary)";
  }

  const s = (status || "").toUpperCase();
  if (s === "ALL") {
    renderOrdersList(allLoadedOrders);
  } else if (s === "PENDING") {
    renderOrdersList(allLoadedOrders.filter(o => o.status === "PENDING" || o.status === "PENDING_PAYMENT"));
  } else if (s === "CONFIRMED") {
    renderOrdersList(allLoadedOrders.filter(o => o.status === "CONFIRMED"));
  } else if (s === "PROCESSING") {
    renderOrdersList(allLoadedOrders.filter(o => o.status === "PROCESSING"));
  } else if (s === "DISPATCHED") {
    renderOrdersList(allLoadedOrders.filter(o => o.status === "DISPATCHED" || o.status === "SHIPPED" || o.status === "OUT_FOR_DELIVERY"));
  } else if (s === "DELIVERED") {
    renderOrdersList(allLoadedOrders.filter(o => o.status === "DELIVERED"));
  } else if (s === "CANCELLED") {
    renderOrdersList(allLoadedOrders.filter(o => o.status === "CANCELLED"));
  } else {
    renderOrdersList(allLoadedOrders.filter(o => o.status === s));
  }
}

// -----------------------------------------------------------------------------
// 13. Admin Dashboard & Operations (/admin)
// -----------------------------------------------------------------------------
function getAdminToken() {
  let token = localStorage.getItem("bharatstore_admin_token") || "";
  if (!token) {
    token = prompt("Enter your BharatStore Admin Secret Key (configured in ADMIN_API_KEY):");
    if (token) {
      token = token.trim();
      localStorage.setItem("bharatstore_admin_token", token);
    }
  }
  return token || "";
}

function promptUpdateAdminToken() {
  const current = localStorage.getItem("bharatstore_admin_token") || "";
  const entered = prompt("Update BharatStore Admin Secret Key:", current);
  if (entered !== null) {
    localStorage.setItem("bharatstore_admin_token", entered.trim());
    showToast("Admin token updated.");
    location.reload();
  }
}

async function loadAdminDashboardStats() {
  try {
    const res = await fetch("/api/admin/stats", {
      headers: { "X-Admin-Token": getAdminToken() }
    });
    const data = await res.json();
    if (data.stats) {
      document.getElementById("kpi-revenue").textContent = `₹${data.stats.total_revenue.toLocaleString('en-IN')}`;
      document.getElementById("kpi-orders").textContent = data.stats.total_orders;
      document.getElementById("kpi-products").textContent = data.stats.total_products;
      document.getElementById("kpi-low-stock").textContent = data.stats.low_stock_count;
    }

    // Recent orders
    const ordersRes = await fetch("/api/orders?limit=8");
    const ordersData = await ordersRes.json();
    const tbody = document.getElementById("admin-recent-orders-body");
    if (tbody && ordersData.orders) {
      tbody.innerHTML = ordersData.orders.map(o => `
        <tr>
          <td><a href="/order/${o.id}" style="color:var(--color-primary); font-weight:700;">#${o.order_number}</a></td>
          <td>${o.customer_name}</td>
          <td>${o.shipping_city}</td>
          <td><strong>₹${Number(o.total_amount).toLocaleString('en-IN')}</strong></td>
          <td><span class="badge-status ${o.status === 'CONFIRMED' ? 'badge-confirmed' : 'badge-pending'}">${o.status}</span></td>
          <td>${o.payment_status}</td>
          <td><a href="/order/${o.id}" class="btn-secondary" style="font-size:11px; padding:4px 10px;">Inspect</a></td>
        </tr>
      `).join("");
    }
  } catch (err) {
    console.error("Admin stats error:", err);
  }
}

async function triggerAdminResetInventory() {
  if (!confirm("Restore catalog stock back to original physical seed inventory counts?")) return;
  const res = await fetch("/api/admin/reset-inventory", {
    method: "POST",
    headers: { "X-Admin-Token": getAdminToken() }
  });
  const data = await res.json();
  if (data.success) {
    showToast("Inventory stock reset to initial levels.");
    setTimeout(() => location.reload(), 800);
  }
}

async function triggerConcurrencyRaceTest() {
  showToast("Firing 10 simultaneous buyers on last 1 remaining item...");
  const res = await fetch("/api/test/concurrency", {
    method: "POST",
    headers: { "X-Admin-Token": getAdminToken() }
  });
  const data = await res.json();
  alert(`ACID Concurrency Stress Test Result:\n\n${data.verdict}\n\nSuccessful Purchases: ${data.successful_purchases}\nRejected Transactions: ${data.rejected_transactions}\nFinal Stock in DB: ${data.final_stock_in_db}`);
}

// Admin Products Table
let allAdminProducts = [];

async function loadAdminProductsTable() {
  const tbody = document.getElementById("admin-products-table-body");
  if (!tbody) return;
  try {
    const res = await fetch("/api/products");
    const data = await res.json();
    allAdminProducts = data.products || [];
    renderAdminProducts(allAdminProducts);
  } catch (err) {
    console.error(err);
  }
}

function renderAdminProducts(list) {
  const tbody = document.getElementById("admin-products-table-body");
  const countEl = document.getElementById("admin-prod-total-count");
  if (!tbody) return;
  if (countEl) countEl.textContent = list.length;

  tbody.innerHTML = list.map(p => `
    <tr>
      <td>#${p.id}</td>
      <td>
        <div style="display:flex; align-items:center; gap:10px;">
          <img src="${p.image_url}" alt="" style="width:36px; height:36px; border-radius:var(--radius-xs); object-fit:cover;">
          <div>
            <strong style="display:block; font-size:12.5px;">${p.title}</strong>
            <span style="font-size:10.5px; color:var(--color-text-muted); font-family:var(--font-mono);">${p.sku}</span>
          </div>
        </div>
      </td>
      <td><span style="font-size:11.5px; background:var(--color-bg-subtle); padding:2px 8px; border-radius:var(--radius-xs);">${p.category}</span></td>
      <td><strong>₹${p.price.toLocaleString('en-IN')}</strong></td>
      <td><span class="badge-status ${p.stock <= 5 ? 'badge-cancelled' : 'badge-confirmed'}">${p.stock} units</span></td>
      <td>${p.rating} ★</td>
      <td>
        <div style="display:flex; gap:6px;">
          <button class="btn-secondary" style="padding:4px 8px; font-size:11px;" onclick="openEditProductModal(${p.id})"><i class="fa-solid fa-pen"></i></button>
          <button class="btn-secondary" style="padding:4px 8px; font-size:11px; color:var(--color-danger);" onclick="deleteAdminProduct(${p.id})"><i class="fa-solid fa-trash-can"></i></button>
        </div>
      </td>
    </tr>
  `).join("");
}

function filterAdminProducts(query) {
  const q = query.toLowerCase().trim();
  const filtered = allAdminProducts.filter(p => 
    p.title.toLowerCase().includes(q) || p.sku.toLowerCase().includes(q) || p.brand.toLowerCase().includes(q)
  );
  renderAdminProducts(filtered);
}

function filterAdminProductsByCategory(cat) {
  if (!cat) {
    renderAdminProducts(allAdminProducts);
  } else {
    renderAdminProducts(allAdminProducts.filter(p => p.category === cat));
  }
}

function openAddProductModal() {
  document.getElementById("modal-product-id").value = "";
  document.getElementById("product-modal-title").textContent = "Add New Product";
  document.getElementById("modal-product-title").value = "";
  document.getElementById("modal-product-brand").value = "Rosier Foods";
  document.getElementById("modal-product-price").value = "";
  document.getElementById("modal-product-original-price").value = "";
  document.getElementById("modal-product-stock").value = "20";
  document.getElementById("modal-product-sku").value = "";
  document.getElementById("modal-product-desc").value = "";
  document.getElementById("product-modal-overlay").classList.add("open");
}

function openEditProductModal(productId) {
  const p = allAdminProducts.find(x => x.id === productId);
  if (!p) return;
  document.getElementById("modal-product-id").value = p.id;
  document.getElementById("product-modal-title").textContent = `Edit Product #${p.id}`;
  document.getElementById("modal-product-title").value = p.title;
  document.getElementById("modal-product-brand").value = p.brand;
  document.getElementById("modal-product-category").value = p.category;
  document.getElementById("modal-product-price").value = p.price;
  document.getElementById("modal-product-original-price").value = p.original_price || "";
  document.getElementById("modal-product-stock").value = p.stock;
  document.getElementById("modal-product-sku").value = p.sku;
  document.getElementById("modal-product-image").value = p.image_url;
  document.getElementById("modal-product-desc").value = p.description;
  document.getElementById("product-modal-overlay").classList.add("open");
}

function closeProductModal() {
  document.getElementById("product-modal-overlay").classList.remove("open");
}

async function handleProductFormSubmit(e) {
  e.preventDefault();
  const id = document.getElementById("modal-product-id").value;
  const payload = {
    title: document.getElementById("modal-product-title").value,
    brand: document.getElementById("modal-product-brand").value,
    category: document.getElementById("modal-product-category").value,
    price: parseFloat(document.getElementById("modal-product-price").value),
    original_price: parseFloat(document.getElementById("modal-product-original-price").value) || null,
    stock: parseInt(document.getElementById("modal-product-stock").value),
    sku: document.getElementById("modal-product-sku").value,
    image_url: document.getElementById("modal-product-image").value || "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=500&auto=format&fit=crop&q=80",
    description: document.getElementById("modal-product-desc").value
  };

  const url = id ? `/api/admin/products/${id}` : "/api/admin/products";
  const method = id ? "PUT" : "POST";

  const res = await fetch(url, {
    method: method,
    headers: {
      "Content-Type": "application/json",
      "X-Admin-Token": getAdminToken()
    },
    body: JSON.stringify(payload)
  });

  const data = await res.json();
  if (data.success) {
    showToast(id ? "Product updated successfully!" : "Product added to catalog!");
    closeProductModal();
    loadAdminProductsTable();
  } else {
    alert("Error: " + data.error);
  }
}

async function deleteAdminProduct(productId) {
  if (!confirm(`Are you sure you want to delete Product #${productId}?`)) return;
  const res = await fetch(`/api/admin/products/${productId}`, {
    method: "DELETE",
    headers: { "X-Admin-Token": getAdminToken() }
  });
  const data = await res.json();
  if (data.success) {
    showToast(`Product #${productId} deleted.`);
    loadAdminProductsTable();
  } else {
    alert("Error: " + data.error);
  }
}

// Admin Inventory Table
let allInventoryProducts = [];

async function loadAdminInventoryTable() {
  const tbody = document.getElementById("admin-inventory-table-body");
  if (!tbody) return;
  try {
    const res = await fetch("/api/products");
    const data = await res.json();
    allInventoryProducts = data.products || [];
    renderInventoryTable(allInventoryProducts);
  } catch (err) {
    console.error(err);
  }
}

function renderInventoryTable(list) {
  const tbody = document.getElementById("admin-inventory-table-body");
  if (!tbody) return;

  tbody.innerHTML = list.map(p => `
    <tr>
      <td>#${p.id}</td>
      <td>
        <strong style="display:block; font-size:13px;">${p.title}</strong>
        <span style="font-size:11px; color:var(--color-text-muted); font-family:var(--font-mono);">${p.sku}</span>
      </td>
      <td>${p.category}</td>
      <td><strong style="font-size:15px; color:var(--color-primary);">${p.stock} units</strong></td>
      <td>
        <span class="badge-status ${p.stock <= 0 ? 'badge-cancelled' : (p.stock <= 5 ? 'badge-pending' : 'badge-confirmed')}">
          ${p.stock <= 0 ? 'Out of Stock' : (p.stock <= 5 ? 'Low Stock' : 'Healthy')}
        </span>
      </td>
      <td>
        <div style="display:flex; align-items:center; gap:8px;">
          <input type="number" id="quick-stock-${p.id}" value="${p.stock}" style="width:70px; padding:4px 8px; border:1px solid var(--color-border); border-radius:var(--radius-xs); font-size:13px;">
          <button class="btn-primary" style="padding:6px 12px; font-size:12px;" onclick="saveQuickStock(${p.id})">Update</button>
        </div>
      </td>
    </tr>
  `).join("");
}

function filterInventoryTable(query) {
  const q = query.toLowerCase().trim();
  renderInventoryTable(allInventoryProducts.filter(p => p.title.toLowerCase().includes(q) || p.sku.toLowerCase().includes(q)));
}

function filterLowStockOnly() {
  renderInventoryTable(allInventoryProducts.filter(p => p.stock <= 5));
}

async function saveQuickStock(productId) {
  const input = document.getElementById(`quick-stock-${productId}`);
  const newStock = parseInt(input.value);
  if (isNaN(newStock) || newStock < 0) {
    alert("Please enter a valid stock quantity >= 0");
    return;
  }
  const res = await fetch("/api/admin/inventory/update", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Admin-Token": getAdminToken()
    },
    body: JSON.stringify({ product_id: productId, stock: newStock })
  });
  const data = await res.json();
  if (data.success) {
    showToast(`Stock for Product #${productId} updated to ${newStock} units`);
    loadAdminInventoryTable();
  }
}

// Admin Orders Table
let allAdminOrders = [];

async function loadAdminOrdersTable() {
  const tbody = document.getElementById("admin-orders-table-body");
  if (!tbody) return;
  try {
    const res = await fetch("/api/orders?limit=50");
    const data = await res.json();
    allAdminOrders = data.orders || [];
    renderAdminOrders(allAdminOrders);
  } catch (err) {
    console.error(err);
  }
}

function renderAdminOrders(list) {
  const tbody = document.getElementById("admin-orders-table-body");
  if (!tbody) return;

  tbody.innerHTML = list.map(o => `
    <tr>
      <td><a href="/order/${o.id}" style="color:var(--color-primary); font-weight:700;">#${o.order_number}</a></td>
      <td>${o.created_at}</td>
      <td>
        <strong>${o.customer_name}</strong>
        <div style="font-size:11px; color:var(--color-text-muted);">${o.customer_email}</div>
      </td>
      <td>${o.shipping_city} Hub</td>
      <td><strong>₹${Number(o.total_amount).toLocaleString('en-IN')}</strong></td>
      <td>
        <span class="badge-status ${o.status === 'CONFIRMED' ? 'badge-confirmed' : (o.status === 'CANCELLED' ? 'badge-cancelled' : 'badge-pending')}">
          ${o.status}
        </span>
      </td>
      <td>
        <select onchange="updateOrderStatusAjax(${o.id}, this.value)" style="padding:4px 8px; font-size:12px; border-radius:var(--radius-xs); border:1px solid var(--color-border); background:var(--color-bg-base); color:var(--color-text-main);">
          <option value="">Change Status...</option>
          <option value="CONFIRMED">CONFIRMED</option>
          <option value="SHIPPED">SHIPPED</option>
          <option value="DELIVERED">DELIVERED</option>
          <option value="CANCELLED">CANCELLED</option>
        </select>
      </td>
      <td>
        <a href="/order/${o.id}" class="btn-secondary" style="font-size:11px; padding:4px 10px;">
          View
        </a>
      </td>
    </tr>
  `).join("");
}

function filterAdminOrdersByStatus(status) {
  if (!status) {
    renderAdminOrders(allAdminOrders);
  } else {
    renderAdminOrders(allAdminOrders.filter(o => o.status === status));
  }
}

async function updateOrderStatusAjax(orderId, newStatus) {
  if (!newStatus) return;
  const res = await fetch(`/api/admin/orders/${orderId}/status`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Admin-Token": getAdminToken()
    },
    body: JSON.stringify({ status: newStatus })
  });
  const data = await res.json();
  if (data.success) {
    showToast(`Order #${orderId} status transitioned to ${newStatus}`);
    loadAdminOrdersTable();
  } else {
    alert("Status update error: " + data.error);
  }
}

// -----------------------------------------------------------------------------
// 14. Toast Notification Utility
// -----------------------------------------------------------------------------
function showToast(message, icon = "fa-solid fa-circle-check") {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = "toast";
  toast.innerHTML = `<i class="${icon}" style="color:var(--color-primary);"></i> <span>${message}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(20px)";
    toast.style.transition = "all 0.3s ease";
    setTimeout(() => toast.remove(), 300);
  }, 2800);
}

// -----------------------------------------------------------------------------
// 15. Product Details Page (/product/<id>) Interactive Operations
// -----------------------------------------------------------------------------
let detailProductQty = 1;

function switchDetailImage(newUrl, thumbElement) {
  const mainImg = document.getElementById("main-detail-img");
  if (mainImg) {
    mainImg.style.opacity = "0.4";
    mainImg.src = newUrl;
    setTimeout(() => { mainImg.style.opacity = "1"; }, 150);
  }
  document.querySelectorAll(".detail-thumb-item").forEach(item => item.classList.remove("active"));
  if (thumbElement) thumbElement.classList.add("active");
}

function openImageLightbox(imageUrl) {
  const modal = document.getElementById("image-lightbox-modal");
  const modalImg = document.getElementById("lightbox-expanded-img");
  if (modal && modalImg) {
    modalImg.src = imageUrl || document.getElementById("main-detail-img")?.src || "";
    modal.classList.add("open");
  }
}

function closeImageLightbox() {
  const modal = document.getElementById("image-lightbox-modal");
  if (modal) modal.classList.remove("open");
}

function incrementDetailQty(maxStock, unitPrice) {
  const maxAllowed = Math.min(maxStock, 10);
  if (detailProductQty < maxAllowed) {
    detailProductQty++;
    updateDetailQtyDOM(unitPrice);
  } else {
    showToast(`Maximum allowable quantity is ${maxAllowed}`);
  }
}

function decrementDetailQty(unitPrice) {
  if (detailProductQty > 1) {
    detailProductQty--;
    updateDetailQtyDOM(unitPrice);
  }
}

function updateDetailQtyDOM(unitPrice) {
  const qtyEl = document.getElementById("detail-qty-input");
  if (qtyEl) qtyEl.textContent = detailProductQty;

  const subtotalEl = document.getElementById("detail-dynamic-subtotal");
  if (subtotalEl && unitPrice) {
    const total = detailProductQty * unitPrice;
    subtotalEl.textContent = `₹${total.toLocaleString('en-IN')}`;
  }
}

async function addCurrentProductToCart(productId) {
  await addToCart(productId, detailProductQty);
}

async function buyNowProduct(productId) {
  await addToCart(productId, detailProductQty);
  window.location.href = "/checkout";
}

function openReviewModal() {
  const modal = document.getElementById("write-review-modal");
  if (modal) modal.classList.add("open");
}

function closeReviewModal(e) {
  if (e && e.target !== e.currentTarget) return;
  const modal = document.getElementById("write-review-modal");
  if (modal) modal.classList.remove("open");
}

async function submitProductReview(e, productId) {
  e.preventDefault();
  const rating = document.getElementById("review-rating-select")?.value;
  const title = document.getElementById("review-title-input")?.value;
  const comment = document.getElementById("review-comment-input")?.value;
  const customerId = document.getElementById("review-customer-select")?.value || 1;

  try {
    const res = await fetch(`/api/products/${productId}/reviews`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rating: parseInt(rating), title, comment, customer_id: parseInt(customerId) })
    });
    const data = await res.json();
    if (data.success) {
      showToast("Thank you! Your verified review has been published.");
      closeReviewModal();
      setTimeout(() => location.reload(), 900);
    } else {
      alert(data.error || "Failed to submit review.");
    }
  } catch (err) {
    console.error("Review submission error:", err);
    alert("Connection error while submitting review.");
  }
}

function initProductDetailPage(productId) {
  const wishlistBtn = document.querySelector(`.detail-wishlist-action-btn[data-product-id="${productId}"]`);
  if (wishlistBtn) {
    const isSaved = appState.wishlist.has(productId);
    wishlistBtn.classList.toggle("active", isSaved);
    wishlistBtn.innerHTML = isSaved
      ? '<i class="fa-solid fa-heart" style="color:#E03131;"></i> Saved in Wishlist'
      : '<i class="fa-regular fa-heart"></i> Add to Wishlist';
  }
}

