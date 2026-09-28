import React, {useLayoutEffect, useRef} from 'react';
import {useCurrentFrame, useVideoConfig} from 'remotion';
import {blackholeFragment} from '../shaders/blackhole';

const vertex = `attribute vec2 position; void main(){gl_Position=vec4(position,0.,1.);}`;

function compile(gl: WebGLRenderingContext, kind: number, source: string): WebGLShader {
  const shader = gl.createShader(kind)!;
  gl.shaderSource(shader, source); gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader) ?? 'Shader compilation failed');
  return shader;
}

export const SpaceShader: React.FC<{mode: 'disk'|'fly'|'warp'; params: Record<string, number>; duration: number; renderScale?: number}> = ({mode, params, duration, renderScale=1}) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  // Optional lower internal canvas resolution for CPU-only preview rendering.
  const pixelWidth=Math.max(1,Math.round(width*renderScale));
  const pixelHeight=Math.max(1,Math.round(height*renderScale));
  const canvas = useRef<HTMLCanvasElement>(null);
  // Keep the WebGL context/program stable across frames. Chromium captures after
  // layout effects; preserveDrawingBuffer avoids black screenshots in headless mode.
  const state = useRef<{gl: WebGLRenderingContext; program: WebGLProgram} | null>(null);
  useLayoutEffect(() => {
    const node = canvas.current!;
    const gl = node.getContext('webgl', {preserveDrawingBuffer: true, antialias: false});
    if (!gl) throw new Error('WebGL unavailable: render on a Chromium GPU/SwiftShader host');
    const program = gl.createProgram()!;
    const vs = compile(gl, gl.VERTEX_SHADER, vertex), fs = compile(gl, gl.FRAGMENT_SHADER, blackholeFragment);
    gl.attachShader(program, vs); gl.attachShader(program, fs); gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program) ?? 'Shader link failed');
    gl.deleteShader(vs); gl.deleteShader(fs);
    gl.useProgram(program);
    const buffer = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1,1,-1,-1,1,1,1]), gl.STATIC_DRAW);
    const position = gl.getAttribLocation(program, 'position');
    gl.enableVertexAttribArray(position); gl.vertexAttribPointer(position,2,gl.FLOAT,false,0,0);
    state.current = {gl,program};
    return () => {gl.deleteBuffer(buffer); gl.deleteProgram(program); state.current = null;};
  }, []);
  useLayoutEffect(() => {
    const s = state.current; if (!s) return;
    const {gl, program} = s;
    const scalar = (key: string, value: number) => gl.uniform1f(gl.getUniformLocation(program,key),value);
    gl.viewport(0,0,pixelWidth,pixelHeight);
    gl.uniform2f(gl.getUniformLocation(program,'resolution'),pixelWidth,pixelHeight);
    gl.uniform1i(gl.getUniformLocation(program,'mode'),mode === 'disk' ? 0 : mode === 'fly' ? 1 : 2);
    scalar('time',frame/fps); scalar('progress',frame/Math.max(fps*duration,1)); scalar('orbit',params.camera_orbit_speed ?? .15);
    scalar('tilt',params.disk_tilt_deg ?? 18); scalar('spin',params.hole_spin ?? .6);
    scalar('lens',params.lens_strength ?? 1.8); scalar('fly',params.camera_speed ?? .4);
    gl.drawArrays(gl.TRIANGLE_STRIP,0,4); gl.finish();
  }, [frame, fps, duration, pixelWidth, pixelHeight, mode, params]);
  return <canvas ref={canvas} width={pixelWidth} height={pixelHeight} style={{width:'100%',height:'100%',display:'block'}}/>;
};
