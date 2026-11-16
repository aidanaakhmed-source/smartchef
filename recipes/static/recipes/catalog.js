
"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const dataElement = document.getElementById("product-catalog-data");
  const searchInput = document.getElementById("catalog-search");
  const selectedContainer = document.getElementById("catalog-selected");
  const countElement = document.getElementById("catalog-count");
  const clearButton = document.getElementById("catalog-clear");
  const emptySelection = document.getElementById("catalog-empty-selection");
  const noResults = document.getElementById("catalog-no-results");

  if (
    !dataElement ||
    !searchInput ||
    !selectedContainer ||
    !countElement ||
    !clearButton
  ) {
    return;
  }

  let catalog;

  try {
    catalog = JSON.parse(
      document.getElementById(
        "product-catalog-data"
      ).textContent
    );
  } catch (error) {
    console.error("Catalog data could not be read:", error);
    return;
  }

  const products = Array.isArray(catalog.products)
    ? catalog.products
    : [];

  const language = catalog.language === "ru" ? "ru" : "kk";

  const productLookup = new Map(
    products.map((product) => [product.id, product])
  );

  const productCards = Array.from(
    document.querySelectorAll(
      ".product-card[data-product-id][data-category]"
    )
  );

  const categoryButtons = Array.from(
    document.querySelectorAll(
      ".category-btn[data-category]"
    )
  );

  const checkboxLookup = new Map();

  for (const card of productCards) {
    const productId = card.dataset.productId;

    const checkbox = card.querySelector(
      'input[type="checkbox"][name="selected_products"]'
    );

    if (!checkbox || !productLookup.has(productId)) {
      continue;
    }

    checkboxLookup.set(productId, checkbox);
  }

  let activeCategory = "all";

  const normalize = (value) => {
    return String(value || "")
      .trim()
      .toLocaleLowerCase();
  };

  function getSelectedProducts() {
    return products.filter((product) => {
      const checkbox = checkboxLookup.get(product.id);
      return Boolean(checkbox && checkbox.checked);
    });
  }

  function updateSelection() {
    const selected = getSelectedProducts();

    selectedContainer.replaceChildren();

    for (const product of selected) {
      const tag = document.createElement("span");
      tag.className = "selected-tag";

      const name = document.createElement("span");
      name.textContent = product[language];

      const removeButton = document.createElement("button");
      removeButton.type = "button";
      removeButton.className = "tag-remove";
      removeButton.textContent = "×";

      const removeText = language === "ru"
        ? "Убрать"
        : "Алып тастау";

      removeButton.setAttribute(
        "aria-label",
        `${removeText}: ${product[language]}`
      );

      removeButton.addEventListener("click", () => {
        const checkbox = checkboxLookup.get(product.id);

        if (!checkbox) {
          return;
        }

        checkbox.checked = false;

        checkbox.dispatchEvent(
          new Event("change", { bubbles: true })
        );
      });

      tag.appendChild(name);
      tag.appendChild(removeButton);
      selectedContainer.appendChild(tag);
    }

    countElement.textContent = String(selected.length);

    const countLabel = language === "ru"
      ? `Выбрано продуктов: ${selected.length}`
      : `Таңдалған өнім саны: ${selected.length}`;

    countElement.setAttribute("aria-label", countLabel);

    if (emptySelection) {
      emptySelection.hidden = selected.length > 0;
    }

    clearButton.disabled = selected.length === 0;
  }

  function filterProducts() {
    const query = normalize(searchInput.value);
    let visibleCount = 0;

    for (const card of productCards) {
      const productId = card.dataset.productId;
      const product = productLookup.get(productId);

      if (!product) {
        card.hidden = true;
        continue;
      }

      const categoryMatches =
        activeCategory === "all" ||
        product.category === activeCategory;

      const kazakhName = normalize(product.kk);
      const russianName = normalize(product.ru);

      const searchMatches =
        query === "" ||
        kazakhName.includes(query) ||
        russianName.includes(query);

      const isVisible = categoryMatches && searchMatches;

      card.hidden = !isVisible;

      if (isVisible) {
        visibleCount += 1;
      }

      // Hidden checkboxes remain enabled and selected.
      // Filtering never changes checkbox.checked.
    }

    if (noResults) {
      noResults.hidden = visibleCount !== 0;
    }
  }

  function setCategory(category) {
    const knownCategories = new Set([
      "all",
      ...(Array.isArray(catalog.categories)
        ? catalog.categories.map((item) => item.id)
        : []),
    ]);

    activeCategory = knownCategories.has(category)
      ? category
      : "all";

    for (const button of categoryButtons) {
      const isActive =
        button.dataset.category === activeCategory;

      button.classList.toggle("is-active", isActive);

      button.setAttribute(
        "aria-pressed",
        String(isActive)
      );
    }

    filterProducts();
  }

  for (const checkbox of checkboxLookup.values()) {
    checkbox.addEventListener("change", updateSelection);
  }

  for (const button of categoryButtons) {
    button.addEventListener("click", () => {
      setCategory(button.dataset.category);
    });
  }

  searchInput.addEventListener("input", filterProducts);

  clearButton.addEventListener("click", () => {
    for (const checkbox of checkboxLookup.values()) {
      checkbox.checked = false;
    }

    updateSelection();
  });

  updateSelection();
  setCategory("all");
});
