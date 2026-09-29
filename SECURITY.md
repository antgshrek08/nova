# Security

Nova runs on people's own computers with access to their files, accounts and
API keys, so security problems matter a lot here. Thank you for reporting them
privately.

## Reporting a problem

**Please don't open a public issue.** Instead, open the repository's
**Security** tab and choose **Report a vulnerability**. Only the maintainer can
see the report.

Include what you can:

- what the problem is and what someone could do with it
- steps to reproduce it, or a proof of concept
- the Nova version or commit, and your operating system

## What happens next

- You'll get a reply within 7 days.
- Once the problem is confirmed, a fix is worked on privately and released
  as soon as it's ready.
- You'll be credited in the release notes unless you'd rather not be.

## Supported versions

Security fixes go into the latest release only. Please update before
reporting.

## In scope

For example: Nova's local server answering requests from other devices or
websites without the access token, API keys or passwords leaking into logs,
chats or the memory index, web pages or documents getting Nova to take
actions the user didn't ask for (prompt injection that gets past Nova's
rules), and anything that lets one app or user read another's data.

Out of scope: problems in third-party services Nova connects to (report those
to the service), and attacks that require someone to already control the
user's computer.
