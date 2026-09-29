/**
 * Shared line icons.
 *
 * The app draws its navigation with 24x24 stroked SVG (see shell/NavRail.jsx),
 * but several surfaces still used emoji as icons -- folder/file glyphs in the
 * Code explorer, a speaker on the voice reactor, a paperclip on attachments.
 * Emoji render as full-colour bitmaps from the OS font: bright yellow folders
 * and blue-grey documents sitting next to thin monochrome strokes, at a size
 * and baseline the surrounding layout cannot control, and looking different on
 * every platform. These are the same stroke weight and viewBox as the rail's
 * icons so every icon in the app reads as one set.
 *
 * Each takes a className so callers set colour via currentColor and size via
 * the parent, rather than each icon hardcoding its own.
 */

const base = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round",
  strokeLinejoin: "round",
};

export function FolderIcon({ className = "h-3.5 w-3.5" }) {
  return (
    <svg {...base} className={className} aria-hidden="true">
      <path d="M3 7a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.6.8l.9 1.2H19a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    </svg>
  );
}

export function FolderOpenIcon({ className = "h-3.5 w-3.5" }) {
  return (
    <svg {...base} className={className} aria-hidden="true">
      <path d="M3 7a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.6.8l.9 1.2H19a2 2 0 0 1 2 2v1H6.5a2 2 0 0 0-1.9 1.4L3 18z" />
      <path d="m3 18 1.6-6.6A2 2 0 0 1 6.5 10H22l-1.7 6.6a2 2 0 0 1-1.9 1.4z" />
    </svg>
  );
}

export function FileIcon({ className = "h-3.5 w-3.5" }) {
  return (
    <svg {...base} className={className} aria-hidden="true">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
      <path d="M14 3v5h5" />
    </svg>
  );
}

export function ChevronRightIcon({ className = "h-3 w-3" }) {
  return (
    <svg {...base} className={className} aria-hidden="true">
      <path d="m9 6 6 6-6 6" />
    </svg>
  );
}

export function SpeakerOnIcon({ className = "h-[18px] w-[18px]" }) {
  return (
    <svg {...base} className={className} aria-hidden="true">
      <path d="M11 5 6.5 9H3v6h3.5L11 19z" />
      <path d="M15.5 8.5a5 5 0 0 1 0 7" />
      <path d="M18.5 5.5a9 9 0 0 1 0 13" />
    </svg>
  );
}

export function SpeakerMutedIcon({ className = "h-[18px] w-[18px]" }) {
  return (
    <svg {...base} className={className} aria-hidden="true">
      <path d="M11 5 6.5 9H3v6h3.5L11 19z" />
      <path d="m16 9.5 5 5M21 9.5l-5 5" />
    </svg>
  );
}

export function PaperclipIcon({ className = "h-3.5 w-3.5" }) {
  return (
    <svg {...base} className={className} aria-hidden="true">
      <path d="M21 11.5 12.5 20a5 5 0 0 1-7-7l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7L10 17.9a1.7 1.7 0 0 1-2.4-2.4l7.9-7.9" />
    </svg>
  );
}

export function PuzzleIcon({ className = "h-3 w-3" }) {
  return (
    <svg {...base} className={className} aria-hidden="true">
      <path d="M10 3.5a1.8 1.8 0 0 1 3.6 0V5h2.9a1 1 0 0 1 1 1v2.9h1.5a1.8 1.8 0 0 1 0 3.6H17.5V16a1 1 0 0 1-1 1h-2.9v-1.5a1.8 1.8 0 0 0-3.6 0V17H7a1 1 0 0 1-1-1v-2.9H4.5a1.8 1.8 0 0 1 0-3.6H6V6a1 1 0 0 1 1-1h3z" />
    </svg>
  );
}

export function WarningIcon({ className = "h-3.5 w-3.5" }) {
  return (
    <svg {...base} className={className} aria-hidden="true">
      <path d="M10.3 3.8 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.8a2 2 0 0 0-3.4 0z" />
      <path d="M12 9v4M12 17h.01" />
    </svg>
  );
}

export function MicIcon({ className = "h-4 w-4" }) {
  return (
    <svg {...base} className={className} aria-hidden="true">
      <rect x="9" y="2" width="6" height="11" rx="3" />
      <path d="M5 10v1a7 7 0 0 0 14 0v-1M12 18v4M8 22h8" />
    </svg>
  );
}

// Shown while a recording is being transcribed. Three static dots rather
// than a spinner: the wait is short and unpredictable, and a spinner at this
// size next to a text field reads as "the app is stuck".
export function DotsIcon({ className = "h-4 w-4" }) {
  return (
    <svg {...base} className={className} aria-hidden="true">
      <circle cx="5" cy="12" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="19" cy="12" r="1.5" fill="currentColor" stroke="none" />
    </svg>
  );
}
