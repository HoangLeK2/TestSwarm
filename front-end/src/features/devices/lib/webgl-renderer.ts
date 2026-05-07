export class WebGLRenderer {
  private canvas: HTMLCanvasElement;
  private gl: WebGLRenderingContext | null = null;
  private program: WebGLProgram | null = null;
  private positionBuffer: WebGLBuffer | null = null;
  private texCoordBuffer: WebGLBuffer | null = null;
  private texture: WebGLTexture | null = null;
  private positionLoc = -1;
  private texCoordLoc = -1;
  private samplerLoc: WebGLUniformLocation | null = null;
  private width = 0;
  private height = 0;
  private contextLost = false;
  private readonly onContextLostBound: (e: Event) => void;
  private readonly onContextRestoredBound: () => void;

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    this.onContextLostBound = (e: Event) => {
      e.preventDefault();
      this.contextLost = true;
      this.destroyResources();
    };
    this.onContextRestoredBound = () => {
      this.contextLost = false;
      this.init();
    };
    this.canvas.addEventListener('webglcontextlost', this.onContextLostBound as EventListener, false);
    this.canvas.addEventListener('webglcontextrestored', this.onContextRestoredBound, false);
    this.init();
  }

  render(source: TexImageSource, width: number, height: number): void {
    if (this.contextLost || !this.gl) return;
    if (width > 0 && height > 0 && (width !== this.width || height !== this.height)) {
      this.width = width;
      this.height = height;
      this.canvas.width = width;
      this.canvas.height = height;
      this.gl.viewport(0, 0, width, height);
    }

    if (!this.program || !this.texture) return;
    const gl = this.gl;
    gl.useProgram(this.program);
    gl.bindTexture(gl.TEXTURE_2D, this.texture);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, 1);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, source);

    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }

  isMostlyBlack(): boolean {
    if (this.contextLost || !this.gl || this.width <= 0 || this.height <= 0) {
      return false;
    }
    const gl = this.gl;
    const sampleW = Math.min(32, this.width);
    const sampleH = Math.min(32, this.height);
    const x = Math.max(0, Math.floor((this.width - sampleW) / 2));
    const y = Math.max(0, Math.floor((this.height - sampleH) / 2));
    const pixels = new Uint8Array(sampleW * sampleH * 4);
    try {
      gl.readPixels(x, y, sampleW, sampleH, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    } catch {
      return false;
    }

    let dark = 0;
    let lit = 0;
    const total = sampleW * sampleH;
    for (let i = 0; i < pixels.length; i += 4) {
      const luma = (pixels[i] * 0.2126) + (pixels[i + 1] * 0.7152) + (pixels[i + 2] * 0.0722);
      if (luma < 8) dark += 1;
      if (luma > 24) lit += 1;
    }
    return dark / total > 0.985 && lit / total < 0.01;
  }

  dispose(): void {
    this.canvas.removeEventListener('webglcontextlost', this.onContextLostBound as EventListener, false);
    this.canvas.removeEventListener('webglcontextrestored', this.onContextRestoredBound, false);
    this.destroyResources();
    this.gl = null;
  }

  private init(): void {
    const gl =
      (this.canvas.getContext('webgl', {
        antialias: false,
        depth: false,
        stencil: false,
        alpha: false,
        // Idle screen on device → encoder emits no new frames → RAF tick has
        // no frame to draw → with preserveDrawingBuffer:false the compositor
        // resets the framebuffer to clearColor (black) every vsync, causing
        // intermittent black frames during stillness. Preserving the buffer
        // keeps the last decoded frame visible until a new one arrives.
        preserveDrawingBuffer: true,
        premultipliedAlpha: false,
      }) as WebGLRenderingContext | null) || null;
    if (!gl) return;
    this.gl = gl;

    const vertexSrc = `
      attribute vec2 aPosition;
      attribute vec2 aTexCoord;
      varying vec2 vTexCoord;
      void main() {
        gl_Position = vec4(aPosition, 0.0, 1.0);
        vTexCoord = aTexCoord;
      }
    `;
    const fragmentSrc = `
      precision mediump float;
      varying vec2 vTexCoord;
      uniform sampler2D uTexture;
      void main() {
        gl_FragColor = texture2D(uTexture, vTexCoord);
      }
    `;

    const vs = this.compileShader(gl.VERTEX_SHADER, vertexSrc);
    const fs = this.compileShader(gl.FRAGMENT_SHADER, fragmentSrc);
    if (!vs || !fs) return;

    const program = gl.createProgram();
    if (!program) return;
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);
    gl.deleteShader(vs);
    gl.deleteShader(fs);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      gl.deleteProgram(program);
      return;
    }
    this.program = program;

    this.positionLoc = gl.getAttribLocation(program, 'aPosition');
    this.texCoordLoc = gl.getAttribLocation(program, 'aTexCoord');
    this.samplerLoc = gl.getUniformLocation(program, 'uTexture');

    const positions = new Float32Array([
      -1, -1,
      1, -1,
      -1, 1,
      1, 1,
    ]);
    const texCoords = new Float32Array([
      0, 0,
      1, 0,
      0, 1,
      1, 1,
    ]);

    this.positionBuffer = gl.createBuffer();
    this.texCoordBuffer = gl.createBuffer();
    if (!this.positionBuffer || !this.texCoordBuffer) return;

    gl.bindBuffer(gl.ARRAY_BUFFER, this.positionBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, positions, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(this.positionLoc);
    gl.vertexAttribPointer(this.positionLoc, 2, gl.FLOAT, false, 0, 0);

    gl.bindBuffer(gl.ARRAY_BUFFER, this.texCoordBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, texCoords, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(this.texCoordLoc);
    gl.vertexAttribPointer(this.texCoordLoc, 2, gl.FLOAT, false, 0, 0);

    this.texture = gl.createTexture();
    if (!this.texture) return;
    gl.bindTexture(gl.TEXTURE_2D, this.texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.useProgram(program);
    if (this.samplerLoc) gl.uniform1i(this.samplerLoc, 0);
    gl.clearColor(0, 0, 0, 1);
    gl.viewport(0, 0, this.canvas.width || 1, this.canvas.height || 1);
  }

  private compileShader(type: number, source: string): WebGLShader | null {
    if (!this.gl) return null;
    const shader = this.gl.createShader(type);
    if (!shader) return null;
    this.gl.shaderSource(shader, source);
    this.gl.compileShader(shader);
    if (!this.gl.getShaderParameter(shader, this.gl.COMPILE_STATUS)) {
      this.gl.deleteShader(shader);
      return null;
    }
    return shader;
  }

  private destroyResources(): void {
    if (!this.gl) return;
    const gl = this.gl;
    if (this.texture) {
      gl.deleteTexture(this.texture);
      this.texture = null;
    }
    if (this.positionBuffer) {
      gl.deleteBuffer(this.positionBuffer);
      this.positionBuffer = null;
    }
    if (this.texCoordBuffer) {
      gl.deleteBuffer(this.texCoordBuffer);
      this.texCoordBuffer = null;
    }
    if (this.program) {
      gl.deleteProgram(this.program);
      this.program = null;
    }
  }
}
