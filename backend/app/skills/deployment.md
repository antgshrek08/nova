---
name: deployment
description: Ship a project to a host — build, environment, domains, rollback — and verify the deployed thing actually works.
keywords: [deploy, deployment, ship it, publish, vercel, netlify, render, railway, fly.io, hosting, production, staging, preview, rollback, domain, dns, environment variables, build failed, ci]
---

A deploy is not finished when the command exits zero. It is finished when the
deployed URL has been fetched and behaves.

Before the first deploy, establish four things, and say which are missing rather
than guessing: the build command and output directory, the runtime and its
version, every environment variable the app reads (names only — never print
values), and whether anything expects a persistent filesystem, which most hosts
do not provide.

Prefer a preview deploy to pushing straight at production. A preview URL is the
cheapest way there is to discover a missing environment variable.

After deploying, check the real URL rather than the build log: the page renders,
API routes answer, nothing fatal in the console, and anything that should
require auth still does. A green build serving a blank page is the ordinary
failure, not an exotic one.

When a build fails, read the actual error before changing anything. The causes
are dull and specific — a dependency installed locally but missing from the
manifest, a case-sensitive import that worked on Windows and fails on Linux, a
runtime version mismatch, a variable needed at build time that was only set for
run time.

Know the rollback before it is needed. Most hosts keep previous deployments one
click away, and during an incident that is the fix — not a hot patch written
under pressure.

Never print secret values into logs, commit them, or paste them into chat. Set
them through the host's own environment settings and refer to them by name.
