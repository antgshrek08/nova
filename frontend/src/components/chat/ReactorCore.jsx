import { useEffect, useRef, useState } from "react";

export const STATUS_LABEL = {
  idle: "Ready",
  listening: "Listening…",
  thinking: "Synthesizing…",
  speaking: "Speaking",
  disconnected: "Disconnected — check backend connection",
  approval: "Awaiting Confirmation",
};

/**
 * Nova Intellectual Harmonic Voice Sphere
 * An ethereal, luminous 3D celestial/neural sphere that breathes and deforms
 * with real voice audio levels, featuring orbital gyroscopic rings,
 * harmonic latitude/longitude meridians, and volumetric plasma illumination.
 */
/**
 * Nova Intellectual Optical Voice Sphere
 * A photorealistic optical glass acoustic sphere with physical Fresnel rim lighting,
 * studio softbox reflections, volumetric subsurface occlusion, and continuous fluid
 * acoustic wavebands that undulate dynamically to voice and speech audio.
 */
export default function ReactorCore({ state = "idle", levels, getMicLevels, getPlaybackLevels }) {
  const canvasRef = useRef(null);
  const [accentRgb, setAccentRgb] = useState("59, 130, 246");

  useEffect(() => {
    function updateAccent() {
      const computed = getComputedStyle(document.documentElement).getPropertyValue("--accent-rgb").trim();
      if (computed) setAccentRgb(computed);
    }
    updateAccent();
    window.addEventListener("nova:theme-changed", updateAccent);
    return () => window.removeEventListener("nova:theme-changed", updateAccent);
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animId;
    let time = 0;
    let smoothedLevel = 0.05;
    let rotY = 0;
    let rotX = 0.18;

    // Fluid acoustic harmonics configuration
    const fluidLayers = [
      { baseRadiusRatio: 0.72, speed: 0.85, freq1: 2, freq2: 3, amp: 0.14, colorOffset: 25, alpha: 0.32 },
      { baseRadiusRatio: 0.62, speed: -1.05, freq1: 3, freq2: 4, amp: 0.18, colorOffset: -15, alpha: 0.4 },
      { baseRadiusRatio: 0.52, speed: 1.25, freq1: 2, freq2: 5, amp: 0.22, colorOffset: 40, alpha: 0.45 },
      { baseRadiusRatio: 0.40, speed: -0.7, freq1: 4, freq2: 3, amp: 0.16, colorOffset: -5, alpha: 0.5 }
    ];

    // Suspended luminous micro-particles within the fluid
    const particleCount = 22;
    const particles = [];
    for (let i = 0; i < particleCount; i++) {
      particles.push({
        radiusRatio: 0.2 + (i % 5) * 0.12,
        angle: (i / particleCount) * Math.PI * 2,
        speed: (0.4 + ((i * 3) % 4) * 0.2) * (i % 2 === 0 ? 1 : -1),
        size: 0.8 + (i % 3) * 0.4,
        phase: (i * 1.618) % (Math.PI * 2)
      });
    }

    function render() {
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      const width = rect.width;
      const height = rect.height;

      if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
        canvas.width = Math.round(width * dpr);
        canvas.height = Math.round(height * dpr);
      }

      ctx.save();
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, width, height);

      // Simulation timing based on state
      const baseSpeed = state === "thinking" ? 0.038 : state === "speaking" ? 0.024 : 0.012;
      time += baseSpeed;

      // Audio level calculation
      let rawAudio = 0;
      if (typeof levels === "function") {
        const l = levels();
        if (l && l.length) rawAudio = l.reduce((a, b) => a + b, 0) / (l.length * 80);
      } else if (Array.isArray(levels) && levels.length) {
        rawAudio = levels.reduce((a, b) => a + b, 0) / (levels.length * 80);
      } else if (state === "listening" && getMicLevels) {
        const l = getMicLevels();
        if (l && l.length) rawAudio = l.reduce((a, b) => a + b, 0) / (l.length * 80);
      } else if (state === "speaking" && getPlaybackLevels) {
        const l = getPlaybackLevels();
        if (l && l.length) rawAudio = l.reduce((a, b) => a + b, 0) / (l.length * 80);
      }

      rawAudio = Math.min(1.2, Math.max(0, rawAudio));
      if (state === "thinking") {
        rawAudio = 0.35 + 0.25 * Math.sin(time * 2.8);
      } else if (state === "idle") {
        rawAudio = 0.04 + 0.03 * Math.sin(time * 1.3);
      }

      // Smooth envelope follower
      const attackCoeff = rawAudio > smoothedLevel ? 0.32 : 0.1;
      smoothedLevel += (rawAudio - smoothedLevel) * attackCoeff;

      const cx = width / 2;
      const cy = height / 2;
      const R = Math.min(width, height) * 0.35; // Sphere physical radius

      // Colors
      let rgb = accentRgb;
      if (state === "approval") rgb = "251, 191, 36";
      else if (state === "disconnected") rgb = "251, 113, 133";
      else if (state === "listening") rgb = "52, 211, 153";

      const [rC, gC, bC] = rgb.split(",").map((s) => parseInt(s.trim(), 10) || 128);

      // =========================================================================
      // 1. EXTERIOR ATMOSPHERIC AURA (Soft optical diffusion)
      // =========================================================================
      const auraPulse = 1 + smoothedLevel * 0.2;
      const auraGrad = ctx.createRadialGradient(cx, cy, R * 0.3, cx, cy, R * 1.5 * auraPulse);
      const auraAlpha = state === "speaking" ? 0.24 : state === "listening" ? 0.18 : 0.1;
      auraGrad.addColorStop(0, `rgba(${rgb}, ${auraAlpha * (1 + smoothedLevel * 0.7)})`);
      auraGrad.addColorStop(0.55, `rgba(${rgb}, ${auraAlpha * 0.2})`);
      auraGrad.addColorStop(1, "rgba(0, 0, 0, 0)");

      ctx.fillStyle = auraGrad;
      ctx.beginPath();
      ctx.arc(cx, cy, R * 1.5 * auraPulse, 0, Math.PI * 2);
      ctx.fill();

      // =========================================================================
      // 2. PHYSICAL SPHERE VOLUMETRIC BODY (Clipped Interior)
      // =========================================================================
      ctx.save();
      ctx.beginPath();
      ctx.arc(cx, cy, R, 0, Math.PI * 2);
      ctx.clip(); // Optical sphere interior

      // 2A. Deep Smoked Optical Crystal Base
      const glassGrad = ctx.createRadialGradient(
        cx - R * 0.35,
        cy - R * 0.35,
        R * 0.05,
        cx + R * 0.1,
        cy + R * 0.15,
        R * 1.15
      );
      glassGrad.addColorStop(0, `rgba(${Math.min(255, rC + 50)}, ${Math.min(255, gC + 50)}, ${Math.min(255, bC + 50)}, 0.15)`);
      glassGrad.addColorStop(0.35, "rgba(8, 12, 22, 0.95)");
      glassGrad.addColorStop(0.75, "rgba(3, 6, 12, 0.98)");
      glassGrad.addColorStop(1, "rgba(1, 2, 5, 1)");

      ctx.fillStyle = glassGrad;
      ctx.fillRect(cx - R, cy - R, R * 2, R * 2);

      // 2B. Fluid Harmonic Wave Contours (Organic Sound Resonance)
      ctx.save();
      ctx.globalCompositeOperation = "screen";

      fluidLayers.forEach((layer) => {
        const layerTime = time * layer.speed;
        const currentAmp = layer.amp * (1 + smoothedLevel * 1.8);
        const baseR = R * layer.baseRadiusRatio * (1 + smoothedLevel * 0.15);

        // Center slightly drifts with fluid currents
        const lX = cx + Math.sin(layerTime * 0.6) * (R * 0.08);
        const lY = cy + Math.cos(layerTime * 0.5) * (R * 0.08);

        const rL = Math.max(0, Math.min(255, rC + layer.colorOffset));
        const gL = Math.max(0, Math.min(255, gC + layer.colorOffset * 0.6));
        const bL = Math.max(0, Math.min(255, bC));

        // Draw organic undulating contour
        ctx.beginPath();
        const steps = 96;
        for (let s = 0; s <= steps; s++) {
          const theta = (s / steps) * Math.PI * 2;
          const wave1 = Math.sin(theta * layer.freq1 + layerTime * 1.8) * currentAmp;
          const wave2 = Math.cos(theta * layer.freq2 - layerTime * 1.4) * (currentAmp * 0.5);
          const rad = baseR * (1 + wave1 + wave2);
          const px = lX + Math.cos(theta) * rad;
          const py = lY + Math.sin(theta) * rad;

          if (s === 0) ctx.moveTo(px, py);
          else ctx.lineTo(px, py);
        }
        ctx.closePath();

        // Soft volumetric fluid fill
        const fluidGrad = ctx.createRadialGradient(lX, lY, 0, lX, lY, baseR * 1.25);
        fluidGrad.addColorStop(0, `rgba(${rL}, ${gL}, ${bL}, ${layer.alpha * 0.85})`);
        fluidGrad.addColorStop(0.65, `rgba(${rL}, ${gL}, ${bL}, ${layer.alpha * 0.35})`);
        fluidGrad.addColorStop(1, "rgba(0, 0, 0, 0)");

        ctx.fillStyle = fluidGrad;
        ctx.fill();

        // Silky fluid boundary thread
        ctx.strokeStyle = `rgba(${Math.min(255, rL + 40)}, ${Math.min(255, gL + 40)}, ${Math.min(255, bL + 40)}, ${layer.alpha * 0.75})`;
        ctx.lineWidth = 1.1;
        ctx.stroke();
      });

      ctx.restore();

      // 2C. Suspended Micro-Acoustic Photons (Drifting in the fluid)
      particles.forEach((pt) => {
        const currentAngle = pt.angle + time * pt.speed * 0.4;
        const radialDeform = pt.radiusRatio * (1 + smoothedLevel * 0.25);
        const px = cx + Math.cos(currentAngle) * R * radialDeform;
        const py = cy + Math.sin(currentAngle) * R * radialDeform * 0.85;

        const pulse = 0.5 + 0.5 * Math.sin(time * 3 + pt.phase);
        const alpha = 0.35 + 0.45 * pulse + smoothedLevel * 0.2;
        const rad = pt.size * (0.8 + smoothedLevel * 0.4);

        ctx.beginPath();
        ctx.arc(px, py, rad, 0, Math.PI * 2);
        ctx.fillStyle = pulse > 0.6
          ? `rgba(255, 255, 255, ${alpha})`
          : `rgba(${rgb}, ${alpha * 0.85})`;
        ctx.fill();
      });

      // 2D. Internal Volumetric Core Glow (Luminous Intellectual Nucleus)
      const corePulse = 1 + smoothedLevel * 0.4 + 0.04 * Math.sin(time * 3);
      const coreRadius = R * (0.32 + smoothedLevel * 0.25);
      const coreX = cx + Math.sin(time * 0.4) * (R * 0.05);
      const coreY = cy + Math.cos(time * 0.5) * (R * 0.04);

      const nucleusGrad = ctx.createRadialGradient(
        coreX - coreRadius * 0.15,
        coreY - coreRadius * 0.15,
        1,
        coreX,
        coreY,
        coreRadius * corePulse
      );
      nucleusGrad.addColorStop(0, "rgba(255, 255, 255, 0.96)");
      nucleusGrad.addColorStop(0.2, `rgba(${Math.min(255, rC + 80)}, ${Math.min(255, gC + 80)}, ${Math.min(255, bC + 80)}, 0.88)`);
      nucleusGrad.addColorStop(0.58, `rgba(${rgb}, ${0.38 + smoothedLevel * 0.35})`);
      nucleusGrad.addColorStop(1, "rgba(0, 0, 0, 0)");

      ctx.fillStyle = nucleusGrad;
      ctx.beginPath();
      ctx.arc(coreX, coreY, coreRadius * corePulse, 0, Math.PI * 2);
      ctx.fill();

      ctx.restore(); // Exit sphere clipping

      // =========================================================================
      // 3. PHOTOREALISTIC OPTICAL GLASS SURFACE & PHYSICAL LIGHTING
      // =========================================================================

      // 3A. Physical Fresnel Grazing Rim Reflection
      const fresnelGrad = ctx.createRadialGradient(
        cx,
        cy,
        R * 0.86,
        cx,
        cy,
        R
      );
      fresnelGrad.addColorStop(0, "rgba(255, 255, 255, 0)");
      fresnelGrad.addColorStop(0.65, `rgba(${rgb}, 0.05)`);
      fresnelGrad.addColorStop(0.88, `rgba(${rgb}, 0.32)`);
      fresnelGrad.addColorStop(0.97, "rgba(255, 255, 255, 0.72)");
      fresnelGrad.addColorStop(1, `rgba(${rgb}, 0.22)`);

      ctx.beginPath();
      ctx.arc(cx, cy, R, 0, Math.PI * 2);
      ctx.fillStyle = fresnelGrad;
      ctx.fill();

      // Precision razor-thin perimeter glass boundary
      ctx.beginPath();
      ctx.arc(cx, cy, R, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(255, 255, 255, ${0.32 + smoothedLevel * 0.22})`;
      ctx.lineWidth = 1;
      ctx.stroke();

      // 3B. Primary Studio Specular Reflection (Photographic curved softbox highlight)
      // Real optical glass reflects ambient studio softbox light along the spherical curve
      // with silky smooth falloff towards both ends
      ctx.save();
      const specStartAngle = -Math.PI * 0.88;
      const specEndAngle = -Math.PI * 0.54;
      const specRadius = R * 0.82;
      const specSteps = 24;

      // Diffuse soft specular glow layer
      for (let s = 0; s < specSteps; s++) {
        const t1 = s / specSteps;
        const t2 = (s + 1) / specSteps;
        const a1 = specStartAngle + t1 * (specEndAngle - specStartAngle);
        const a2 = specStartAngle + t2 * (specEndAngle - specStartAngle);
        const midT = (t1 + t2) / 2;
        const fade = Math.pow(Math.sin(midT * Math.PI), 1.6);

        ctx.beginPath();
        ctx.arc(cx, cy, specRadius, a1, a2);
        ctx.strokeStyle = `rgba(${Math.min(255, rC + 100)}, ${Math.min(255, gC + 100)}, ${Math.min(255, bC + 100)}, ${0.16 * fade})`;
        ctx.lineWidth = R * 0.09;
        ctx.stroke();
      }

      // Crisp center specular reflection glint with smooth end falloff
      for (let s = 0; s < specSteps; s++) {
        const t1 = s / specSteps;
        const t2 = (s + 1) / specSteps;
        const a1 = specStartAngle + t1 * (specEndAngle - specStartAngle);
        const a2 = specStartAngle + t2 * (specEndAngle - specStartAngle);
        const midT = (t1 + t2) / 2;
        const fade = Math.pow(Math.sin(midT * Math.PI), 2.2);

        ctx.beginPath();
        ctx.arc(cx, cy, specRadius, a1, a2);
        ctx.strokeStyle = `rgba(255, 255, 255, ${0.72 * fade})`;
        ctx.lineWidth = R * 0.024;
        ctx.stroke();
      }
      ctx.restore();

      // 3C. Secondary Bottom-Right Ambient Bounce Reflection
      ctx.save();
      const bounceStartAngle = Math.PI * 0.22;
      const bounceEndAngle = Math.PI * 0.46;
      const bounceRadius = R * 0.86;
      const bounceSteps = 16;

      for (let s = 0; s < bounceSteps; s++) {
        const t1 = s / bounceSteps;
        const t2 = (s + 1) / bounceSteps;
        const a1 = bounceStartAngle + t1 * (bounceEndAngle - bounceStartAngle);
        const a2 = bounceStartAngle + t2 * (bounceEndAngle - bounceStartAngle);
        const midT = (t1 + t2) / 2;
        const fade = Math.pow(Math.sin(midT * Math.PI), 1.8);

        ctx.beginPath();
        ctx.arc(cx, cy, bounceRadius, a1, a2);
        ctx.strokeStyle = `rgba(${rgb}, ${0.28 * fade})`;
        ctx.lineWidth = R * 0.035;
        ctx.stroke();
      }
      ctx.restore();

      // 3D. Active Voice Equator Pulse Wave (Subtle acoustic ripple when speaking)
      if (smoothedLevel > 0.14) {
        ctx.beginPath();
        const pulseR = R * (1.02 + smoothedLevel * 0.22);
        ctx.arc(cx, cy, pulseR, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(${rgb}, ${Math.min(0.32, smoothedLevel * 0.38)})`;
        ctx.lineWidth = 1.2;
        ctx.stroke();
      }

      ctx.restore();
      animId = requestAnimationFrame(render);
    }

    render();
    return () => cancelAnimationFrame(animId);
  }, [state, levels, getMicLevels, getPlaybackLevels, accentRgb]);

  return (
    <div className="relative flex items-center justify-center w-full h-full max-w-[340px] max-h-[340px] mx-auto select-none pointer-events-none">
      <canvas
        ref={canvasRef}
        className="w-full h-full block"
        style={{ width: "100%", height: "100%" }}
      />
    </div>
  );
}
