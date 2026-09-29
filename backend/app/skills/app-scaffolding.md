---
name: app-scaffolding
description: Start a new app or site — stack choice, project structure, and the first running thing — without over-building.
keywords: [new app, new project, start a project, scaffold, boilerplate, create app, build an app, stack, next.js, react, vite, fastapi, template, from scratch, mvp]
---

The first goal is a running thing, not a complete one. Something that renders in
a browser after one command is worth more than a well-planned tree of empty
folders, because it converts every later question from speculation into a test.

Choose the stack from the project, not from habit. What has to be true — does it
need a server, a database, auth, a background job, or is it a page with some
interactivity? Say the choice and the reason in one line each, and prefer what
the user already runs: a stack they can debug beats a marginally better one they
cannot.

Do not install what is not yet needed. A state management library before there
is state, an ORM before there is a schema, a component library before there is a
design — each is a dependency to maintain and a decision that gets harder to
reverse. Add them when the need appears, which is usually later and sometimes
never.

Set up four things early, because retrofitting them is worse: a single place
config and secrets are read from, one way of reporting errors, a script that
runs the thing locally with one command, and a `.gitignore` that already covers
the environment file and build output.

Commit the moment it runs, before adding features. That commit is the known-good
state to return to, and it costs nothing to make.

State plainly what has been stubbed. A scaffold with a fake auth check or
hard-coded data is fine and normal, and becomes a problem exactly when someone
forgets which parts were real.
