// Client-side clipboard + accumulative-copy ("cart") for prompter.
// The cart is kept in localStorage so it survives navigation between pages.

const CART_KEY = "prompter-cart-v1";

function loadCart() {
  try {
    return JSON.parse(localStorage.getItem(CART_KEY)) || [];
  } catch {
    return [];
  }
}
function saveCart(items) {
  localStorage.setItem(CART_KEY, JSON.stringify(items));
}

function toast(msg) {
  const el = document.getElementById("toast");
  if (!el) return;
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove("show"), 1500);
}

async function copyText(text, label) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // Fallback for non-secure contexts.
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
  }
  toast(label || "복사했습니다");
}

// Mirror of placeholder.render_block on the server.
function renderBlock(name, body) {
  return `<!-- prompter:${name} -->\n${body.trim()}\n<!-- /prompter:${name} -->`;
}

function copyBody(btn) {
  copyText(btn.dataset.body, "본문을 복사했습니다");
}

function copyBlock(btn) {
  copyText(renderBlock(btn.dataset.name, btn.dataset.body), "블록을 복사했습니다");
}

function addToCart(btn) {
  const items = loadCart();
  const entry = {
    name: btn.dataset.name,
    title: btn.dataset.title || btn.dataset.name,
    body: btn.dataset.body,
  };
  if (items.some((i) => i.name === entry.name)) {
    toast("이미 담겨 있습니다");
    return;
  }
  items.push(entry);
  saveCart(items);
  renderCart();
  toast(`담음: ${entry.title}`);
}

function removeFromCart(name) {
  saveCart(loadCart().filter((i) => i.name !== name));
  renderCart();
}

function clearCart() {
  saveCart([]);
  renderCart();
  toast("비웠습니다");
}

function copyCart() {
  const items = loadCart();
  if (!items.length) {
    toast("담긴 항목이 없습니다");
    return;
  }
  const text = items.map((i) => i.body.trim()).join("\n\n");
  copyText(text, `${items.length}개 항목을 누적 복사했습니다`);
}

function renderCart() {
  const items = loadCart();
  const list = document.getElementById("cart-list");
  const count = document.getElementById("cart-count");
  const empty = document.getElementById("cart-empty");
  if (!list) return;
  count.textContent = items.length;
  empty.style.display = items.length ? "none" : "block";
  list.innerHTML = "";
  for (const it of items) {
    const li = document.createElement("li");
    const label = document.createElement("span");
    label.innerHTML = `${it.title} <code>${it.name}</code>`;
    const rm = document.createElement("button");
    rm.textContent = "✕";
    rm.title = "제거";
    rm.onclick = () => removeFromCart(it.name);
    li.append(label, rm);
    list.appendChild(li);
  }
}

document.addEventListener("DOMContentLoaded", renderCart);
