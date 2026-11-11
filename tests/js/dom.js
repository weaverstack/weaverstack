// A DOM stand-in for renderer event/state tests, not browser layout or painting.
"use strict";
class Element {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.attrs = {}; this.listeners = {};
    this.style = {}; this._text = ""; this.isConnected = true;
    this.classList = {
      contains: (c) => (this.attrs.class || "").split(" ").includes(c),
      toggle: (c, on) => { const list = new Set((this.attrs.class || "").split(" ").filter(Boolean));
        if (on === undefined ? !list.has(c) : on) list.add(c); else list.delete(c);
        this.attrs.class = [...list].join(" "); },
      add: (c) => this.classList.toggle(c, true), remove: (c) => this.classList.toggle(c, false)
    };
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
  set className(value) { this.attrs.class = value; }
  get className() { return this.attrs.class || ""; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  removeAttribute(k) { delete this.attrs[k]; }
  appendChild(child) { child.parentElement = this; this.children.push(child); return child; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  removeEventListener() {}
  setPointerCapture() {}
  focus() {}
  getBoundingClientRect() { return { x: 0, y: 0, left: 0, top: 0, width: 1000, height: 600 }; }
  matches(selector) { return selector.startsWith(".") ? this.classList.contains(selector.slice(1)) : this.tagName === selector; }
  closest(selector) { return this.matches(selector) ? this : this.parentElement?.closest(selector) || null; }
  querySelectorAll(selector) { return this.children.flatMap((c) => [...(c.matches(selector) ? [c] : []), ...c.querySelectorAll(selector)]); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  fire(type, values = {}) {
    const event = { type, target: this, button: 0, pointerId: 1, pointerType: "mouse", clientX: 0, clientY: 0,
      preventDefault() {}, stopPropagation() {}, ...values };
    for (const fn of this.listeners[type] || []) fn.call(this, event);
    this["on" + type]?.call(this, event);
  }
}
function document() {
  return { createElement: (tag) => new Element(tag), createElementNS: (_, tag) => new Element(tag),
    createTextNode: (text) => { const node = new Element("#text"); node.textContent = text; return node; },
    addEventListener() {}, documentElement: new Element("html"), body: new Element("body") };
}
module.exports = { Element, document };
