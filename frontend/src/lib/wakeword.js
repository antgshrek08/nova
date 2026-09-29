import { openMicrophone } from "./microphone.js";
let session = null;
let generation = 0;
export function isWakeWordConfigured() { return Boolean(navigator.mediaDevices?.getUserMedia); }
export async function stopWakeWordDetection() {
  generation++;
  const old = session;
  session = null;
  if (!old) return;
  old.node?.disconnect();
  old.stream?.getTracks().forEach(t => t.stop());
  old.socket?.close();
  await old.context?.close().catch(() => {});
}
window.electronAPI?.onYieldMicrophone?.(() => stopWakeWordDetection());
export async function startWakeWordDetection(onWake, onError = () => {}) {
  if (session) return Boolean(session.ready);
  const epoch = ++generation;
  const current = {};
  session = current;
  try {
    current.stream = await openMicrophone({ background: true });
    if (epoch !== generation) { current.stream.getTracks().forEach(t => t.stop()); return; }
    current.context = new AudioContext({ sampleRate: 16000 });
    const source = current.context.createMediaStreamSource(current.stream);
    current.socket = new WebSocket("ws://127.0.0.1:8000/ws/wakeword");
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error("Wake listener connection timed out")), 5000);
      current.socket.onopen = () => { clearTimeout(timeout); resolve(); };
      current.socket.onerror = () => { clearTimeout(timeout); reject(new Error("Wake listener is unavailable")); };
      current.socket.onclose = () => { clearTimeout(timeout); reject(new Error("Wake listener disconnected")); };
    });
    if (epoch !== generation) return;
    current.socket.onmessage = event => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "wake") onWake(data);
        if (data.type === "error") { onError(new Error(data.message)); stopWakeWordDetection(); }
      } catch (error) { onError(error); }
    };
    current.socket.onclose = () => { if (session === current) { onError(new Error("Wake listener disconnected")); stopWakeWordDetection(); } };
    let pending = new Int16Array(0);
    current.node = current.context.createScriptProcessor(4096, 1, 1);
    current.node.onaudioprocess = event => {
      const input = event.inputBuffer.getChannelData(0);
      const next = new Int16Array(pending.length + input.length);
      next.set(pending);
      for (let i = 0; i < input.length; i++) next[pending.length + i] = Math.max(-1, Math.min(1, input[i])) * 32767;
      pending = next;
      while (pending.length >= 1280) {
        if (current.socket.readyState === WebSocket.OPEN && current.socket.bufferedAmount < 32000) current.socket.send(pending.slice(0, 1280).buffer);
        pending = pending.slice(1280);
      }
    };
    source.connect(current.node);
    current.node.connect(current.context.destination);
    await current.context.resume();
    current.ready = true;
    return session === current;
  } catch (error) {
    if (session === current) await stopWakeWordDetection();
    throw error;
  }
}
