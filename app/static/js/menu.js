// Daily menu (counter orders): quantity buttons and the running total.
function changeQty(btn, delta) {
  const input = btn.parentElement.querySelector(".qty-input");
  let val = parseInt(input.value || "0", 10) + delta;
  if (val < 0) val = 0;
  input.value = val;
  updateTotal();
}

function updateTotal() {
  let total = 0;
  document.querySelectorAll("#regular-menu-section .qty-input").forEach((input) => {
    const qty = parseInt(input.value || "0", 10);
    const price = parseFloat(input.dataset.price || "0");
    total += qty * price;
  });
  const display = document.getElementById("total-display");
  if (display) display.textContent = "RM " + total.toFixed(2);
}

document.addEventListener("DOMContentLoaded", updateTotal);
