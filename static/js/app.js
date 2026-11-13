/**
 * BharatStore — Complete Frontend Application Logic
 * Integrates Rosier Foods design system with Amazon/Flipkart marketplace discovery
 * Features: Light/Dark theme, Cart & Wishlist persistence, Hub selection,
 * OpenSearch typo-tolerant search & suggestions, ACID row locking checkout, and Admin portal.
 */

// Global State
const appState = {
  products: [],
  cart: JSON.parse(localStorage.getItem("bharatstore_cart") || "{}"),
  wishlist: new Set(JSON.parse(localStorage.getItem("bharatstore_wishlist") || "[]")),
  currentCity: localStorage.getItem("bharatstore_selected_city") || "Mumbai",
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
document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  updateHeaderBadges();
  updateHubUI();
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

function updateHubUI() {
  const display = document.getElementById("current-hub-display");
  if (display) display.textContent = `${appState.currentCity} Hub`;
  const label = document.getElementById("recommended-hub-label");
  if (label) label.textContent = `${appState.currentCity} Hub`;
}

function openHubSwitchModal() {
  const modal = document.getElementById("hub-modal-overlay");
  if (modal) modal.classList.add("open");
}

function closeHubSwitchModal() {
  const modal = document.getElementById("hub-modal-overlay");
  if (modal) modal.classList.remove("open");
}

function selectDeliveryHub(hubName) {
  appState.currentCity = hubName;
  localStorage.setItem("bharatstore_selected_city", hubName);
  updateHubUI();
  closeHubSwitchModal();
  showToast(`Switched physical fulfillment hub to ${hubName}`);
  if (document.getElementById("catalog-products-grid")) {
    applyFilters();
  }
}

// -----------------------------------------------------------------------------
// 2. Cart Management (LocalStorage + Live Drawer Sync)
// -----------------------------------------------------------------------------
function saveCart() {
  localStorage.setItem("bharatstore_cart", JSON.stringify(appState.cart));
  updateHeaderBadges();
  renderCartDrawer();
}

function updateHeaderBadges() {
  const totalItems = Object.values(appState.cart).reduce((sum, item) => sum + item.qty, 0);
  const totalAmount = Object.values(appState.cart).reduce((sum, item) => sum + (item.product.price * item.qty), 0);

  const cartBadge = document.getElementById("cart-badge-count");
  if (cartBadge) cartBadge.textContent = totalItems;
  const drawerCount = document.getElementById("drawer-cart-count");
  if (drawerCount) drawerCount.textContent = totalItems;
  const subtotalEl = document.getElementById("header-cart-subtotal");
  if (subtotalEl) subtotalEl.textContent = `₹${totalAmount.toLocaleString('en-IN')}`;
  const wishlistBadge = document.getElementById("wishlist-badge-count");
  if (wishlistBadge) wishlistBadge.textContent = appState.wishlist.size;
}

async function addToCart(productId, qty = 1) {
  let product = appState.products.find(p => p.id === productId);
  if (!product) {
    try {
      const res = await fetch(`/api/products/${productId}`);
      const data = await res.json();
      if (data.product) product = data.product;
    } catch (e) {
      console.error(e);
    }
  }
  if (!product) return;

  if (!appState.cart[productId]) {
    appState.cart[productId] = { product, qty: 0 };
  }
  appState.cart[productId].qty += qty;
  if (appState.cart[productId].qty > product.stock) {
    appState.cart[productId].qty = product.stock;
    showToast(`Maximum stock reached for ${product.title}`);
  }
  saveCart();
  showToast(`Added ${product.title} to cart`);
}

function updateCartItemQty(productId, delta) {
  if (appState.cart[productId]) {
    appState.cart[productId].qty += delta;
    if (appState.cart[productId].qty <= 0) {
      delete appState.cart[productId];
    } else if (appState.cart[productId].qty > appState.cart[productId].product.stock) {
      appState.cart[productId].qty = appState.cart[productId].product.stock;
      showToast("Cannot exceed available physical store hub stock");
    }
    saveCart();
    if (document.getElementById("cart-page-items-list")) {
      renderCartPage();
    }
  }
}

function removeCartItem(productId) {
  if (appState.cart[productId]) {
    delete appState.cart[productId];
    saveCart();
    if (document.getElementById("cart-page-items-list")) {
      renderCartPage();
    }
    showToast("Item removed from basket");
  }
}

function clearCart() {
  appState.cart = {};
  saveCart();
  if (document.getElementById("cart-page-items-list")) {
    renderCartPage();
  }
  showToast("Basket cleared.");
}

function toggleCartDrawer() {
  const drawer = document.getElementById("cart-drawer-overlay");
  if (drawer) {
    drawer.classList.toggle("open");
    if (drawer.classList.contains("open")) {
      renderCartDrawer();
    }
  }
}

function closeCartDrawer(e) {
  const drawer = document.getElementById("cart-drawer-overlay");
  if (drawer) drawer.classList.remove("open");
}

function renderCartDrawer() {
  const container = document.getElementById("cart-drawer-items-container");
  const totalEl = document.getElementById("drawer-cart-total");
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
    return;
  }

  let subtotal = 0;
  container.innerHTML = items.map(item => {
    const p = item.product;
    const itemTotal = p.price * item.qty;
    subtotal += itemTotal;
    return `
      <div class="drawer-item">
        <img src="${p.image_url}" alt="${p.title}">
        <div>
          <div class="drawer-item-title">${p.title}</div>
          <div class="drawer-item-price">₹${p.price.toLocaleString('en-IN')}</div>
          <div class="drawer-qty-control">
            <button onclick="updateCartItemQty(${p.id}, -1)">-</button>
            <span>${item.qty}</span>
            <button onclick="updateCartItemQty(${p.id}, 1)">+</button>
          </div>
        </div>
        <button onclick="removeCartItem(${p.id})" style="background:transparent; border:none; color:var(--color-danger); cursor:pointer;" title="Remove">
          <i class="fa-solid fa-trash-can"></i>
        </button>
      </div>
    `;
  }).join("");

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

  // Update button visual if present on screen
  document.querySelectorAll(`.wishlist-float-btn[data-product-id="${productId}"]`).forEach(btn => {
    btn.classList.toggle("active", appState.wishlist.has(productId));
    btn.innerHTML = appState.wishlist.has(productId) ? '<i class="fa-solid fa-heart" style="color:#E03131;"></i>' : '<i class="fa-regular fa-heart"></i>';
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
    const res = await fetch("/api/products");
    if (!res.ok) throw new Error(`HTTP ${res.status}: Failed to fetch products catalog`);
    const data = await res.json();
    appState.products = data.products || [];

    // Check URL parameters
    const urlParams = new URLSearchParams(window.location.search);
    const catParam = urlParams.get("category") || window.ACTIVE_CATEGORY_PARAM || "";
    const qParam = urlParams.get("q") || window.SEARCH_QUERY_PARAM || "";

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
      if (title) title.innerHTML = `Search Results for "${qParam}"`;
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

  catalogFilteredProducts = appState.products.filter(p => {
    // 1. Category
    if (selectedCategory && p.category !== selectedCategory) return false;

    // 2. Search Query (typo-tolerant matching fallback)
    if (qParam) {
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

function resetCatalogFilters() {
  const allCat = document.querySelector('input[name="cat_filter"][value=""]');
  if (allCat) allCat.checked = true;
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
      const res = await fetch(`/api/search/suggestions?q=${encodeURIComponent(query.trim())}`);
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
            <span>${s.title}</span>
          </div>
          <span class="suggestion-cat">${s.category}</span>
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
  window.location.href = `/products?q=${encodeURIComponent(title)}`;
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
// 9. Detailed Cart Page (/cart)
// -----------------------------------------------------------------------------
function renderCartPage() {
  const container = document.getElementById("cart-page-items-list");
  const countEl = document.getElementById("page-cart-item-count");
  const emptyView = document.getElementById("cart-empty-view");
  const contentWrapper = document.getElementById("cart-content-wrapper");
  if (!container) return;

  const items = Object.values(appState.cart);
  if (countEl) countEl.textContent = items.reduce((s, i) => s + i.qty, 0);

  if (items.length === 0) {
    if (contentWrapper) contentWrapper.style.display = "none";
    if (emptyView) emptyView.style.display = "block";
    return;
  }

  if (contentWrapper) contentWrapper.style.display = "grid";
  if (emptyView) emptyView.style.display = "none";

  let subtotal = 0;
  container.innerHTML = items.map(item => {
    const p = item.product;
    const itemTotal = p.price * item.qty;
    subtotal += itemTotal;
    return `
      <div style="display:grid; grid-template-columns:80px 1fr auto auto; gap:20px; align-items:center; padding-bottom:18px; margin-bottom:18px; border-bottom:1px solid var(--color-border-subtle);">
        <img src="${p.image_url}" alt="${p.title}" style="width:80px; height:80px; object-fit:cover; border-radius:var(--radius-md); border:1px solid var(--color-border);">
        <div>
          <span style="font-size:11px; text-transform:uppercase; font-weight:700; color:var(--color-primary);">${p.brand}</span>
          <h4 style="font-size:14.5px; font-weight:600; margin-bottom:4px;"><a href="/product/${p.id}">${p.title}</a></h4>
          <span style="font-size:11.5px; color:var(--color-sage);"><i class="fa-solid fa-check"></i> Physical Hub Stock: ${p.stock} units</span>
        </div>
        <div style="display:flex; align-items:center; border:1px solid var(--color-border); border-radius:var(--radius-sm); overflow:hidden;">
          <button onclick="updateCartItemQty(${p.id}, -1)" style="padding:6px 12px; background:var(--color-bg-subtle); border:none; cursor:pointer; font-weight:700;">-</button>
          <span style="padding:6px 14px; font-weight:700; font-size:13px;">${item.qty}</span>
          <button onclick="updateCartItemQty(${p.id}, 1)" style="padding:6px 12px; background:var(--color-bg-subtle); border:none; cursor:pointer; font-weight:700;">+</button>
        </div>
        <div style="text-align:right;">
          <div style="font-size:16px; font-weight:800; color:var(--color-text-main);">₹${itemTotal.toLocaleString('en-IN')}</div>
          <button onclick="removeCartItem(${p.id})" style="background:transparent; border:none; color:var(--color-danger); font-size:12px; cursor:pointer; margin-top:4px;">
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
      meterText.innerHTML = `<i class="fa-solid fa-circle-check" style="color:var(--color-sage);"></i> Congratulations! You've unlocked FREE 2-Hour Physical Hub Delivery!`;
    } else {
      const pct = Math.round((subtotal / 499) * 100);
      const remaining = 499 - subtotal;
      meterBar.style.width = `${pct}%`;
      meterVal.textContent = `${pct}%`;
      meterText.innerHTML = `<i class="fa-solid fa-truck-fast"></i> Add ₹${remaining.toLocaleString('en-IN')} more to unlock FREE Hub Delivery!`;
    }
  }

  // Update summary fields
  let discount = 0;
  if (appState.activeCoupon === "BHARAT10") {
    discount = Math.round(subtotal * 0.1);
  }

  document.getElementById("summary-subtotal").textContent = `₹${subtotal.toLocaleString('en-IN')}`;
  document.getElementById("summary-discount").textContent = `-₹${discount.toLocaleString('en-IN')}`;
  document.getElementById("summary-grand-total").textContent = `₹${(subtotal - discount).toLocaleString('en-IN')}`;
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
// 11. Checkout & Transactional ACID Execution (/checkout)
// -----------------------------------------------------------------------------
function initCheckoutPage() {
  const container = document.getElementById("checkout-items-preview");
  const subtotalEl = document.getElementById("checkout-subtotal");
  const totalEl = document.getElementById("checkout-grand-total");
  if (!container) return;

  const items = Object.values(appState.cart);
  if (items.length === 0) {
    container.innerHTML = `<p style="font-size:13px; color:var(--color-text-muted);">No items in cart. <a href="/products" style="color:var(--color-primary); font-weight:700;">Browse catalog</a></p>`;
    document.getElementById("btn-submit-order").disabled = true;
    return;
  }

  let subtotal = 0;
  container.innerHTML = items.map(item => {
    const p = item.product;
    const itemTotal = p.price * item.qty;
    subtotal += itemTotal;
    return `
      <div style="display:flex; justify-content:space-between; align-items:center; font-size:13px;">
        <span style="max-width:240px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${item.qty}x ${p.title}</span>
        <strong style="color:var(--color-text-main);">₹${itemTotal.toLocaleString('en-IN')}</strong>
      </div>
    `;
  }).join("");

  if (subtotalEl) subtotalEl.textContent = `₹${subtotal.toLocaleString('en-IN')}`;
  if (totalEl) totalEl.textContent = `₹${subtotal.toLocaleString('en-IN')}`;
}

function updateCheckoutCity(cityName) {
  appState.currentCity = cityName;
  localStorage.setItem("bharatstore_selected_city", cityName);
}

let placedOrderRef = null;

async function placeOrderFromCheckout() {
  const items = Object.values(appState.cart).map(i => ({
    product_id: i.product.id,
    quantity: i.qty
  }));

  if (items.length === 0) {
    alert("Your basket is empty!");
    return;
  }

  const customerName = document.getElementById("checkout-customer-name")?.value || "Priya Sharma";
  const customerEmail = document.getElementById("checkout-customer-email")?.value || "priya.sharma@example.in";
  const customerPhone = document.getElementById("checkout-customer-phone")?.value || "+91 98201 12345";
  const shippingAddress = document.getElementById("checkout-shipping-address")?.value || "Worli Sea Face";
  const shippingCity = document.getElementById("checkout-shipping-city")?.value || "Mumbai";
  const paymentMethod = document.querySelector('input[name="checkout_payment_method"]:checked')?.value || "UPI";

  // Open Transaction Monitor Modal
  const modal = document.getElementById("tx-modal-overlay");
  if (modal) modal.classList.add("open");

  // Step 1: PostgreSQL BEGIN transaction
  setTxStep("step-db", "PostgreSQL: Acquiring Row Lock (SELECT ... FOR UPDATE)...");

  // Payload: Compliance with Rule 9 (Payment status set to PENDING)
  const payload = {
    customer: {
      name: customerName,
      email: customerEmail,
      phone: customerPhone
    },
    items: items,
    shipping_city: shippingCity,
    shipping_address: shippingAddress,
    payment: {
      method: paymentMethod,
      status: paymentMethod === "COD" ? "PENDING" : "PENDING"
    }
  };

  try {
    const res = await fetch("/api/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const data = await res.json();
    if (!data.success) {
      setTxStep("step-db", `ROLLBACK: ${data.error}`, true);
      alert(`Checkout failed: ${data.error}`);
      return;
    }

    placedOrderRef = data.order;

    // Step 1 Success
    setTxStep("step-db", `COMMITTED: Order #${data.order.order_number} (${data.tx_duration_ms}ms, 0 Overselling)`);

    // Step 2: Lifecycle
    setTimeout(() => {
      setTxStep("step-state", `Order registered in '${data.order.status}' status with stock reserved.`);
    }, 400);

    // Step 3: Kafka
    setTimeout(() => {
      setTxStep("step-kafka", `Published event '${data.kafka_event.event_id}' to topic 'order-events'`);
      document.getElementById("btn-tx-finish").style.display = "inline-flex";

      // Clear cart
      appState.cart = {};
      saveCart();
    }, 800);

  } catch (err) {
    setTxStep("step-db", `Network error: ${err.message}`, true);
  }
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

  container.innerHTML = list.map(o => {
    let statusClass = "badge-pending";
    if (o.status === "CONFIRMED") statusClass = "badge-confirmed";
    if (o.status === "CANCELLED") statusClass = "badge-cancelled";

    return `
      <div style="background:var(--color-bg-surface); border:1px solid var(--color-border); border-radius:var(--radius-xl); overflow:hidden; box-shadow:var(--shadow-sm);">
        <div style="background:var(--color-bg-subtle); padding:16px 24px; display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--color-border); font-size:12.5px;">
          <div style="display:flex; gap:24px;">
            <div>
              <span style="color:var(--color-text-muted); display:block; font-size:11px; text-transform:uppercase;">ORDER PLACED</span>
              <strong>${o.created_at}</strong>
            </div>
            <div>
              <span style="color:var(--color-text-muted); display:block; font-size:11px; text-transform:uppercase;">TOTAL AMOUNT</span>
              <strong style="color:var(--color-primary);">₹${Number(o.total_amount).toLocaleString('en-IN')}</strong>
            </div>
            <div>
              <span style="color:var(--color-text-muted); display:block; font-size:11px; text-transform:uppercase;">DISPATCH HUB</span>
              <strong>${o.shipping_city} Hub</strong>
            </div>
          </div>
          <div>
            <span style="color:var(--color-text-muted); font-size:11px;">ORDER # ${o.order_number}</span>
          </div>
        </div>

        <div style="padding:20px 24px; display:flex; justify-content:space-between; align-items:center;">
          <div>
            <div style="display:flex; align-items:center; gap:10px; margin-bottom:8px;">
              <span class="badge-status ${statusClass}">${o.status}</span>
              <span style="font-size:12px; color:var(--color-text-muted);">Payment: <strong>${o.payment_status} (${o.payment_method})</strong></span>
            </div>
            <p style="font-size:13px; color:var(--color-text-body);">
              Shipping to <strong>${o.customer_name}</strong> &bull; BlueDart 2-Hour Metro Delivery
            </p>
          </div>
          <div style="display:flex; gap:10px;">
            <a href="/order/${o.id}" class="btn-primary" style="font-size:13px; padding:8px 16px;">
              <i class="fa-solid fa-truck-fast"></i> Track Package
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
    });
    btnElement.style.backgroundColor = "var(--color-primary-light)";
    btnElement.style.color = "var(--color-primary)";
  }

  if (status === "all") {
    renderOrdersList(allLoadedOrders);
  } else {
    renderOrdersList(allLoadedOrders.filter(o => o.status === status));
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
