const letterFragment = `
  precision highp float;
  uniform sampler2D letters;
  uniform vec2 size;
  uniform vec2 pointer;
  uniform vec3 pigment;
  uniform float spread;

  float grain(vec2 point) {
    return fract(sin(dot(point, vec2(127.1, 311.7))) * 10931.81);
  }

  float noise(vec2 point) {
    vec2 cell = floor(point);
    vec2 blend = fract(point);
    blend = blend * blend * (3.0 - 2.0 * blend);
    return mix(
      mix(grain(cell), grain(cell + vec2(1.0, 0.0)), blend.x),
      mix(grain(cell + vec2(0.0, 1.0)), grain(cell + vec2(1.0, 1.0)), blend.x),
      blend.y
    );
  }

  void main() {
    vec2 point = vec2(gl_FragCoord.x, size.y - gl_FragCoord.y) / size;
    float aspect = size.x / size.y;
    vec2 delta = (point - pointer) * vec2(aspect, 1.0);
    float local = exp(-dot(delta, delta) * 8.0) * spread;
    vec2 swash = vec2(noise(point * vec2(22.0, 13.0)), noise(point.yx * vec2(11.0, 19.0)));
    vec2 offset = (swash - 0.5) * vec2(0.22 / aspect, 0.22);
    vec2 push = delta / (0.20 + length(delta)) * vec2(0.12 / aspect, 0.12);
    vec2 samplePoint = point - (push + offset) * local;
    vec2 bleed = (swash - 0.5) * vec2(0.15 / aspect, 0.15) * local;
    float ink = texture2D(letters, samplePoint).a;
    float wash = texture2D(letters, samplePoint + bleed).a * local * 0.35;
    gl_FragColor = vec4(pigment, max(ink, wash));
  }
`;

function linkInkProgram(gl, vertexSource, fragmentSource) {
  const program = gl.createProgram();
  for (const [type, source] of [[gl.VERTEX_SHADER, vertexSource], [gl.FRAGMENT_SHADER, fragmentSource]]) {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) return null;
    gl.attachShader(program, shader);
    gl.deleteShader(shader);
  }
  gl.linkProgram(program);
  return gl.getProgramParameter(program, gl.LINK_STATUS) ? program : null;
}

async function paintLettering(canvas, event, reduced) {
  const art = canvas.parentElement;
  const image = art.querySelector(".ink-word.light");
  try {
    await image.decode();
  } catch {
    return;
  }
  const gl = canvas.getContext("webgl", { premultipliedAlpha: false, antialias: false });
  if (!gl) return;
  const program = linkInkProgram(gl, "attribute vec2 vertex; void main() { gl_Position = vec4(vertex, 0.0, 1.0); }", letterFragment);
  if (!program) return;
  gl.useProgram(program);
  const geometry = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, geometry);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const vertex = gl.getAttribLocation(program, "vertex");
  gl.enableVertexAttribArray(vertex);
  gl.vertexAttribPointer(vertex, 2, gl.FLOAT, false, 0, 0);
  gl.bindTexture(gl.TEXTURE_2D, gl.createTexture());
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);

  const uniforms = Object.fromEntries(["size", "pointer", "pigment", "spread"].map(
    (name) => [name, gl.getUniformLocation(program, name)],
  ));
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
  let x = .5;
  let y = .5;
  let targetX = x;
  let targetY = y;
  let spread = 0;
  let touched = -Infinity;
  let frame = 0;
  let ready = false;

  function paint(time) {
    frame = 0;
    const strength = reduced.matches ? 0 : Math.exp(-Math.max(0, time - touched - 75) / 320);
    spread += (strength - spread) * .18;
    x += (targetX - x) * .21;
    y += (targetY - y) * .21;
    if (strength < .001 && spread < .003) spread = 0;
    gl.uniform2f(uniforms.pointer, x, y);
    gl.uniform1f(uniforms.spread, spread);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    art.toggleAttribute("data-letter-flow", spread > .003);
    if (spread > 0 || strength > .001) schedule();
  }

  function schedule() {
    if (!frame && ready) frame = requestAnimationFrame(paint);
  }

  function applyPigment(theme) {
    const color = getComputedStyle(art).getPropertyValue(theme === "dark" ? "--brush-word-dark" : "--brush-word-light").trim();
    const values = color.slice(1).match(/../g).map((channel) => parseInt(channel, 16) / 255);
    gl.uniform3f(uniforms.pigment, ...values);
  }

  function updatePigment() {
    applyPigment(document.documentElement.dataset.theme);
    schedule();
  }

  function setStencil() {
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!width || !height) return;
    const scale = Math.min(devicePixelRatio || 1, 2);
    canvas.width = Math.ceil(width * scale);
    canvas.height = Math.ceil(height * scale);
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.uniform2f(uniforms.size, canvas.width, canvas.height);
    applyPigment(document.documentElement.dataset.theme);
    ready = true;
    schedule();
  }

  function track(event) {
    if (reduced.matches) return;
    const bounds = canvas.getBoundingClientRect();
    targetX = (event.clientX - bounds.left) / bounds.width;
    targetY = (event.clientY - bounds.top) / bounds.height;
    touched = performance.now();
    schedule();
  }
  canvas.addEventListener("pointermove", track);
  canvas.addEventListener("pointerleave", () => {
    touched = -Infinity;
    schedule();
  });
  canvas.addEventListener("webglcontextlost", () => {
    ready = false;
    delete art.dataset.letterFlow;
    cancelAnimationFrame(frame);
  }, { once: true });
  new ResizeObserver(setStencil).observe(canvas);
  new MutationObserver(updatePigment).observe(document.documentElement, { attributeFilter: ["data-theme"] });
  setStencil();
  if (canvas.matches(":hover")) track(event);
}

const lettering = document.querySelector("[data-ink-field]");
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
function startLettering(event) {
  if (reducedMotion.matches) return;
  lettering.removeEventListener("pointermove", startLettering);
  paintLettering(lettering, event, reducedMotion);
}
lettering?.addEventListener("pointermove", startLettering);
