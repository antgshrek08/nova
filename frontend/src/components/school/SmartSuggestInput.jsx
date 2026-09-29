import { useState, useRef, useEffect } from "react";

// Curated dictionary of schools, colleges, and platforms with common acronyms
export const SCHOOL_SUGGESTIONS = [
  { value: "Tallahassee State College (TSC)", aliases: ["tsc", "tallahassee state", "tallahassee community college", "tcc"], domain: "tscfl.instructure.com", platform: "Canvas LMS" },
  { value: "Florida State University (FSU)", aliases: ["fsu", "florida state", "seminoles"], domain: "canvas.fsu.edu", platform: "Canvas LMS" },
  { value: "University of Florida (UF)", aliases: ["uf", "gators", "university of florida"], domain: "ufl.instructure.com", platform: "Canvas LMS" },
  { value: "Florida Virtual School (FLVS)", aliases: ["flvs", "florida virtual", "flex", "flvs full time"], domain: "flvs.net", platform: "FLVS" },
  { value: "University of Central Florida (UCF)", aliases: ["ucf", "central florida", "knights"], domain: "webcourses.ucf.edu", platform: "Canvas LMS" },
  { value: "University of South Florida (USF)", aliases: ["usf", "south florida", "bulls"], domain: "usflearn.instructure.com", platform: "Canvas LMS" },
  { value: "Miami Dade College (MDC)", aliases: ["mdc", "miami dade"], domain: "mdc.instructure.com", platform: "Canvas LMS" },
  { value: "Valencia College", aliases: ["valencia", "valencia college"], domain: "valenciacollege.instructure.com", platform: "Canvas LMS" },
  { value: "Florida International University (FIU)", aliases: ["fiu"], domain: "canvas.fiu.edu", platform: "Canvas LMS" },
  { value: "Florida Atlantic University (FAU)", aliases: ["fau"], domain: "canvas.fau.edu", platform: "Canvas LMS" },
  { value: "Massachusetts Institute of Technology (MIT)", aliases: ["mit"], domain: "canvas.mit.edu", platform: "Canvas LMS" },
  { value: "Harvard University", aliases: ["harvard"], domain: "canvas.harvard.edu", platform: "Canvas LMS" },
  { value: "Stanford University", aliases: ["stanford"], domain: "canvas.stanford.edu", platform: "Canvas LMS" },
  { value: "UC Berkeley", aliases: ["berkeley", "cal"], domain: "bcourses.berkeley.edu", platform: "Canvas LMS" },
  { value: "University of Texas at Austin", aliases: ["ut", "utaustin", "longhorns"], domain: "utexas.instructure.com", platform: "Canvas LMS" },
  { value: "Other / Unlisted School", aliases: ["other", "unlisted", "custom", "different", "none"], platform: "Other" },
];

export const MAJOR_SUGGESTIONS = [
  { value: "Computer Science", aliases: ["cs", "comp sci", "coding", "software"] },
  { value: "General Engineering", aliases: ["engineering", "engineer", "general engineering", "stem"] },
  { value: "Software Engineering", aliases: ["se", "software dev"] },
  { value: "Undecided / Exploring", aliases: ["undecided", "undeclared", "exploring", "general"] },
  { value: "Economics", aliases: ["econ", "economics", "micro", "macro"] },
  { value: "Art History", aliases: ["art", "art history", "arthistory"] },
  { value: "Calculus & Mathematics", aliases: ["math", "calc", "calculus", "applied math"] },
  { value: "Biology", aliases: ["bio", "biology", "pre-med", "premed"] },
  { value: "Business Administration", aliases: ["business", "biz", "management"] },
  { value: "Finance & Accounting", aliases: ["finance", "accounting", "fin"] },
  { value: "Psychology", aliases: ["psych", "psychology"] },
  { value: "Mechanical Engineering", aliases: ["mech e", "meche", "mechanical"] },
  { value: "Electrical Engineering", aliases: ["ee", "electrical"] },
  { value: "General Sciences & STEM", aliases: ["general science", "stem", "natural sciences"] },
  { value: "Humanities & Social Sciences", aliases: ["humanities", "arts and letters", "social sciences"] },
  { value: "Nursing", aliases: ["nurse", "nursing", "bfa"] },
  { value: "Political Science", aliases: ["poly sci", "poli sci", "politics"] },
  { value: "Chemistry & Biochemistry", aliases: ["chem", "biochem"] },
  { value: "Physics", aliases: ["phys", "astrophysics"] },
  { value: "Other / Not Listed", aliases: ["other", "unlisted", "custom", "none"] },
];

export default function SmartSuggestInput({
  value,
  onChange,
  onSelectOption,
  placeholder,
  type = "school", // 'school' | 'major'
  className = "",
}) {
  const [open, setOpen] = useState(false);
  const [suggestions, setSuggestions] = useState([]);
  const containerRef = useRef(null);

  const dataset = type === "school" ? SCHOOL_SUGGESTIONS : MAJOR_SUGGESTIONS;

  useEffect(() => {
    const q = (value || "").trim().toLowerCase();
    if (!q) {
      setSuggestions(dataset.slice(0, 5));
      return;
    }

    const matches = dataset.filter((item) => {
      if (item.value.toLowerCase().includes(q)) return true;
      if (item.aliases?.some((a) => a.toLowerCase().includes(q) || q.includes(a.toLowerCase()))) return true;
      return false;
    });

    setSuggestions(matches.slice(0, 6));
  }, [value, dataset]);

  useEffect(() => {
    function handleClickOutside(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div ref={containerRef} className="relative w-full">
      <input
        type="text"
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        placeholder={placeholder}
        className={className}
      />

      {open && suggestions.length > 0 && (
        <div className="absolute left-0 right-0 top-full z-50 mt-1 max-h-56 overflow-y-auto rounded-lg border border-charcoal-700 bg-charcoal-900/95 py-1 shadow-xl backdrop-blur-md">
          <div className="px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-charcoal-500">
            Suggested {type === "school" ? "Institutions" : "Majors"}
          </div>
          {suggestions.map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => {
                onChange(item.value);
                onSelectOption?.(item);
                setOpen(false);
              }}
              className="flex w-full items-center justify-between px-3 py-1.5 text-left text-xs text-charcoal-200 transition-colors hover:bg-cyan-500/20 hover:text-cyan-200"
            >
              <span className="font-medium truncate">{item.value}</span>
              {item.platform && (
                <span className="ml-2 shrink-0 rounded bg-charcoal-800 px-1.5 py-0.5 text-[10px] text-cyan-400 border border-cyan-500/30">
                  {item.platform}
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
