import React from "react";

/**
 * Handcrafted celestial starburst emblem for N.O.V.A.
 * Neural Operator for Versatile Autonomy
 * Designed with precision geometric curves and subtle ambient depth.
 */
export default function NovaLogo({ size = 32, showText = false, className = "" }) {
  return (
    <div className={`inline-flex items-center gap-2.5 select-none ${className}`}>
      <div
        className="relative flex items-center justify-center rounded-xl bg-gradient-to-b from-charcoal-800 to-charcoal-900 border border-charcoal-700/80 shadow-sm"
        style={{ width: size, height: size }}
      >
        <svg
          viewBox="0 0 48 48"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className="w-3/4 h-3/4"
        >
          {/* Subtle ambient core glow */}
          <circle cx="24" cy="24" r="14" fill="url(#nova-core-glow)" opacity="0.45" />

          {/* Precision 4-point celestial starburst */}
          <path
            d="M24 4 C24 16, 16 24, 4 24 C16 24, 24 32, 24 44 C24 32, 32 24, 44 24 C32 24, 24 16, 24 4 Z"
            fill="url(#nova-starburst-grad)"
          />

          {/* Secondary diagonal diamond facets */}
          <path
            d="M24 14 C24 19, 19 24, 14 24 C19 24, 24 29, 24 34 C24 29, 29 24, 34 24 C29 24, 24 19, 24 14 Z"
            fill="#ffffff"
            opacity="0.35"
          />

          {/* Central pulsar spark */}
          <circle cx="24" cy="24" r="2.8" fill="#ffffff" />

          <defs>
            <radialGradient id="nova-core-glow" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="#34d399" stopOpacity="0.8" />
              <stop offset="60%" stopColor="#06b6d4" stopOpacity="0.3" />
              <stop offset="100%" stopColor="#06b6d4" stopOpacity="0" />
            </radialGradient>
            <linearGradient id="nova-starburst-grad" x1="4" y1="4" x2="44" y2="44" gradientUnits="userSpaceOnUse">
              <stop offset="0%" stopColor="#6ee7b7" />
              <stop offset="50%" stopColor="#34d399" />
              <stop offset="100%" stopColor="#0ea5e9" />
            </linearGradient>
          </defs>
        </svg>
      </div>

      {showText && (
        <div className="flex flex-col">
          <span className="text-sm font-semibold tracking-wider text-charcoal-100 font-sans">
            N.O.V.A.
          </span>
          <span className="text-[10px] uppercase tracking-widest text-charcoal-400 font-medium -mt-0.5">
            Neural Operator
          </span>
        </div>
      )}
    </div>
  );
}
