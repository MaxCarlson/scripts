"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "../llm_monitor/web_static");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const script = fs.readFileSync(path.join(root, "assets/app.js"), "utf8");
const stylesheet = fs.readFileSync(path.join(root, "assets/app.css"), "utf8");

assert.match(html, /id="login-form"/);
assert.match(html, /\/assets\/app\.js/);
assert.doesNotMatch(html, /<script[^>]*>\s*[^<]/i);
assert.doesNotMatch(html, /<style\b/i);
assert.match(script, /\/auth\/login/);
assert.match(script, /\/api\/inference\/v1\/status/);
assert.match(script, /\/api\/inference\/v1\/models/);
assert.match(script, /\/api\/inference\/v1\/requests/);
assert.match(script, /textContent/);
assert.doesNotMatch(script, /\.innerHTML\s*=/);
assert.match(html, /Individual requests are not captured/);
assert.match(stylesheet, /prefers-reduced-motion/);
assert.match(stylesheet, /@media/);

console.log("Standalone web UI contract checks passed.");
