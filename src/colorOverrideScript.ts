/**
 * Self-contained vanilla JS script that can be injected into any document
 * (iframes, child webviews) to provide the right-click color override feature.
 * Each document stores its own overrides in its own localStorage.
 */
export const COLOR_OVERRIDE_SCRIPT = `
(function() {
  if (window.__cadenColorOverride) return;
  window.__cadenColorOverride = true;

  var STORAGE_KEY = "caden-color-overrides";

  function loadOverrides() {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}"); }
    catch(e) { return {}; }
  }
  function saveOverrides(o) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(o));
  }

  function selectorFor(el) {
    var parts = [];
    var cur = el;
    while (cur && cur !== document.documentElement && cur !== document.body) {
      var sel = cur.tagName.toLowerCase();
      if (cur.id) {
        parts.unshift("#" + CSS.escape(cur.id));
        break;
      }
      var cls = Array.from(cur.classList).filter(function(c) { return !/[\\[\\]:\\/]/.test(c); }).slice(0, 3);
      if (cls.length) sel += "." + cls.map(CSS.escape).join(".");
      var parent = cur.parentElement;
      if (parent) {
        var sibs = Array.from(parent.children).filter(function(s) { return s.tagName === cur.tagName; });
        if (sibs.length > 1) sel += ":nth-of-type(" + (sibs.indexOf(cur) + 1) + ")";
      }
      parts.unshift(sel);
      cur = cur.parentElement;
    }
    return parts.join(" > ");
  }

  function applyStyles(overrides) {
    var tag = document.getElementById("caden-color-overrides-style");
    if (!tag) {
      tag = document.createElement("style");
      tag.id = "caden-color-overrides-style";
      document.head.appendChild(tag);
    }
    var rules = Object.keys(overrides).map(function(sel) {
      var o = overrides[sel];
      var props = [];
      if (o.text) props.push("color: " + o.text + " !important");
      if (o.bg) props.push("background-color: " + o.bg + " !important");
      return props.length ? sel + " { " + props.join("; ") + "; }" : "";
    }).filter(Boolean).join("\\n");
    tag.textContent = rules;
  }

  // Apply on load
  applyStyles(loadOverrides());

  var menu = null;
  var currentSelector = null;

  function removeMenu() {
    if (menu) { menu.remove(); menu = null; }
    currentSelector = null;
  }

  function makeMenu(x, y, sel) {
    removeMenu();
    currentSelector = sel;
    var overrides = loadOverrides();
    var existing = overrides[sel];

    var div = document.createElement("div");
    div.id = "caden-color-ctx";
    div.style.cssText = "position:fixed;z-index:99999;min-width:160px;padding:4px 0;background:#1a3a4a;border:1px solid #305972;border-radius:4px;box-shadow:0 4px 12px rgba(0,0,0,0.3);font:12px monospace;color:#a0c4d4;";
    if (x + 180 > window.innerWidth) x -= 180;
    if (y + 120 > window.innerHeight) y -= 120;
    div.style.left = x + "px";
    div.style.top = y + "px";

    function btn(label, onClick) {
      var b = document.createElement("button");
      b.textContent = label;
      b.style.cssText = "display:block;width:100%;text-align:left;padding:6px 12px;background:none;border:none;color:#a0c4d4;font:12px monospace;cursor:pointer;";
      b.onmouseenter = function() { b.style.background = "#305972"; b.style.color = "#e8f4fa"; };
      b.onmouseleave = function() { b.style.background = "none"; b.style.color = "#a0c4d4"; };
      b.onclick = onClick;
      div.appendChild(b);
      return b;
    }

    function pickColor(prop) {
      var input = document.createElement("input");
      input.type = "color";
      input.value = (existing && existing[prop]) || (prop === "text" ? "#ffffff" : "#244b5f");
      input.style.cssText = "position:absolute;visibility:hidden;";
      document.body.appendChild(input);
      input.addEventListener("input", function() {
        var o = loadOverrides();
        if (!o[sel]) o[sel] = {};
        o[sel][prop] = input.value;
        saveOverrides(o);
        applyStyles(o);
      });
      input.addEventListener("change", function() {
        input.remove();
      });
      input.click();
      removeMenu();
    }

    btn("Change text color", function() { pickColor("text"); });
    btn("Change background color", function() { pickColor("bg"); });

    if (existing) {
      var hr = document.createElement("div");
      hr.style.cssText = "border-top:1px solid #305972;margin:4px 0;";
      div.appendChild(hr);
      var rb = btn("Reset colors", function() {
        var o = loadOverrides();
        delete o[sel];
        saveOverrides(o);
        applyStyles(o);
        removeMenu();
      });
      rb.style.color = "#e05050";
      rb.onmouseenter = function() { rb.style.background = "#305972"; };
      rb.onmouseleave = function() { rb.style.background = "none"; };
    }

    document.body.appendChild(div);
    menu = div;
  }

  document.addEventListener("contextmenu", function(e) {
    if (e.target.closest && e.target.closest("#caden-color-ctx")) return;
    e.preventDefault();
    var sel = selectorFor(e.target);
    if (sel) makeMenu(e.clientX, e.clientY, sel);
  });

  document.addEventListener("mousedown", function(e) {
    if (menu && e.target.closest && !e.target.closest("#caden-color-ctx")) removeMenu();
  });

  document.addEventListener("keydown", function(e) {
    if (e.key === "Escape") removeMenu();
  });

  // Apply CADEN theme colors/scale/contrast broadcast from the parent window
  window.addEventListener("message", function(e) {
    if (!e.data) return;
    if (e.data.type === "caden-theme-colors") {
      var colors = e.data.colors;
      for (var key in colors) {
        if (Object.prototype.hasOwnProperty.call(colors, key)) {
          document.documentElement.style.setProperty(key, colors[key]);
        }
      }
    } else if (e.data.type === "caden-font-scale") {
      document.documentElement.style.setProperty("--font-scale", String(e.data.scale));
    } else if (e.data.type === "caden-contrast") {
      document.documentElement.style.setProperty("--contrast", String(e.data.contrast));
    }
  });
})();
`;
