// Electron owns the lease so separate windows cannot record concurrently.
export async function openMicrophone({ background = false } = {}) {
  // crypto.randomUUID exists only in a secure context, so over plain HTTP to
  // a Tailscale address it is undefined and this threw before the app could
  // finish loading. The value is a lease id used to tell two microphone
  // claims apart within one page -- it needs to be unique here, not
  // cryptographic -- so a fallback is honest rather than a weakening.
  const token = globalThis.crypto?.randomUUID?.()
    ?? `lease-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  const api = window.electronAPI;
  if (api?.claimMicrophone && !await api.claimMicrophone(token, background)) {
    throw new Error("The microphone is already listening in another Nova window.");
  }
  let released = false;
  const release = () => {
    if (released) return;
    released = true;
    api?.releaseMicrophone?.(token);
  };
  try {
    // navigator.mediaDevices only exists in a secure context. Reached over
    // plain HTTP -- which is how a phone gets here before Tailscale serves
    // HTTPS -- it is undefined, and the bare property access surfaced as
    // "Cannot read properties of undefined (reading 'getUserMedia')" in the
    // header, which tells the user nothing they can act on.
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error(
        window.isSecureContext
          ? "This browser will not give Nova a microphone."
          : "Voice needs a secure connection. Open Nova over HTTPS to talk to it from here."
      );
    }
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    for (const track of stream.getTracks()) {
      const stop = track.stop.bind(track);
      track.stop = () => { stop(); if (stream.getTracks().every(t => t.readyState === "ended")) release(); };
      track.addEventListener("ended", () => { if (stream.getTracks().every(t => t.readyState === "ended")) release(); });
    }
    return stream;
  } catch (error) {
    release();
    throw error;
  }
}
