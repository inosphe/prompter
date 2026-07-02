// Client-side clipboard + accumulative-copy ("cart") + templates for prompter.
// The cart is kept in localStorage so it survives navigation between pages.

const CART_KEY = "prompter-cart-v2"; // v2: entries carry {kind, id}
const CART_MARKERS_KEY = "prompter-cart-markers-v1";

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

function cartKey(item) {
  return `${item.kind || "context"}:${item.name}`;
}

function loadCartMarkers() {
  return localStorage.getItem(CART_MARKERS_KEY) === "1";
}
function saveCartMarkers(on) {
  localStorage.setItem(CART_MARKERS_KEY, on ? "1" : "0");
}
function onCartMarkersToggle(input) {
  saveCartMarkers(input.checked);
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

// "복사": respects the card's "블록 마커 포함" toggle when present.
function copyBody(btn) {
  const markers = btn.closest(".card-actions")?.querySelector(".card-markers");
  if (markers && markers.checked) {
    copyText(renderBlock(btn.dataset.name, btn.dataset.body), "블록을 복사했습니다");
  } else {
    copyText(btn.dataset.body, "본문을 복사했습니다");
  }
}

function addToCart(btn) {
  const entry = {
    name: btn.dataset.name,
    title: btn.dataset.title || btn.dataset.name,
    body: btn.dataset.body,
    kind: btn.dataset.kind || "context",
    id: btn.dataset.id ? Number(btn.dataset.id) : null,
  };
  const items = loadCart();
  if (items.some((i) => cartKey(i) === cartKey(entry))) {
    toast("이미 담겨 있습니다");
    return;
  }
  items.push(entry);
  saveCart(items);
  renderCart();
  toast(`담음: ${entry.title}`);
}

function removeFromCart(key) {
  saveCart(loadCart().filter((i) => cartKey(i) !== key));
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
  const withMarkers = loadCartMarkers();
  const text = items
    .map((i) =>
      withMarkers && (i.kind || "context") === "context"
        ? renderBlock(i.name, i.body)
        : i.body.trim(),
    )
    .join("\n\n");
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
    const kindTag = it.kind === "prompt" ? '<span class="mini-tag">P</span>' : "";
    label.innerHTML = `${kindTag}${it.title} <code>${it.name}</code>`;
    const rm = document.createElement("button");
    rm.textContent = "✕";
    rm.title = "제거";
    rm.onclick = () => removeFromCart(cartKey(it));
    li.append(label, rm);
    list.appendChild(li);
  }
}

// -- templates --------------------------------------------------------------

// Save the current cart's items (of the active kind) as a named template.
async function saveTemplate() {
  const box = document.querySelector(".cart-save");
  const kind = box?.dataset.kind || "context";
  const nameInput = document.getElementById("tpl-name");
  const name = (nameInput?.value || "").trim();
  if (!name) {
    toast("템플릿 이름을 입력하세요");
    nameInput?.focus();
    return;
  }
  const items = loadCart().filter((i) => (i.kind || "context") === kind);
  if (!items.length) {
    toast(`담긴 ${kind === "context" ? "Context" : "Prompt"} 항목이 없습니다`);
    return;
  }
  try {
    const res = await fetch("/api/templates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        kind,
        name,
        title: name,
        members: items.map((i) => i.name),
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      toast(`템플릿 저장: ${data.name} (${data.count}개)`);
      nameInput.value = "";
    } else {
      toast(data.error || "저장 실패");
    }
  } catch {
    toast("서버에 저장하지 못했습니다");
  }
}

// Copy a template composed from the *current* member bodies (live).
async function copyTemplate(el) {
  const card = el.closest(".card");
  const id = card?.dataset.id;
  const markers = card?.querySelector(".tpl-markers");
  const on = markers && markers.checked ? 1 : 0;
  try {
    const res = await fetch(`/api/templates/${id}/compose?markers=${on}`);
    if (!res.ok) {
      toast("복사 실패");
      return;
    }
    const data = await res.json();
    copyText(data.text, `템플릿 복사 (${data.count}개)`);
  } catch {
    toast("서버에서 불러오지 못했습니다");
  }
}

// Load a template's members into the cart.
function loadTemplateToCart(el) {
  const card = el.closest(".card");
  const kind = card?.dataset.kind || "context";
  let members = [];
  try {
    members = JSON.parse(card?.dataset.members || "[]");
  } catch {
    members = [];
  }
  const items = loadCart();
  let added = 0;
  for (const m of members) {
    const entry = { name: m.name, title: m.title || m.name, body: m.body, kind, id: m.id ?? null };
    if (items.some((i) => cartKey(i) === cartKey(entry))) continue;
    items.push(entry);
    added++;
  }
  saveCart(items);
  renderCart();
  toast(added ? `담기에 ${added}개 불러옴` : "이미 모두 담겨 있습니다");
}

document.addEventListener("DOMContentLoaded", () => {
  const markers = document.getElementById("cart-markers");
  if (markers) markers.checked = loadCartMarkers();
  renderCart();
});
