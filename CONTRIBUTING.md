# Contributing to Nova

Thanks for helping. Bug reports, ideas and pull requests are all welcome.

## Before you start

- **Found a bug?** [Open an issue](../../issues/new/choose) with the steps to
  make it happen, what you expected, and what happened instead.
- **Have an idea?** Open a feature request first, so we can agree on it before
  you spend time on code.
- **Found a security problem?** Don't open an issue. See [SECURITY.md](SECURITY.md).

Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## Setting up

Follow the install steps in the [README](README.md) for your system. Then:

```bash
# engine tests (use .venv\Scripts\python on Windows)
cd backend && .venv/bin/python -m pytest tests -q

# the app with live reload
cd frontend && npm run dev
```

## Sending a pull request

1. Fork the repository and create a branch from `main`.
2. Keep each pull request to one change. Small ones get reviewed faster.
3. Add or update tests for what you changed, and make sure the tests pass.
4. Match the style of the code around your change.
5. Nova is for everyone: nothing personal (names, paths, accounts, keys) in
   code, tests or examples.
6. Describe what changed and why, and how you checked it. For anything
   visible, add a screenshot.

Every pull request is tested on Windows, macOS and Linux automatically.

## Contributor terms

Nova is owned by Anthony Grant and published under the
[PolyForm Strict License 1.0.0](LICENSE), with separate commercial licenses
available from the owner. So that Nova can keep being offered both ways, every
contribution comes with these terms. By submitting a pull request, patch or
other material ("your contribution"), you agree that:

1. **It's yours to give.** You wrote it, or you have the right to submit it
   under these terms, and it doesn't include anyone else's code unless that
   code's license allows this and you've said so in the pull request.
2. **License to the owner.** You grant Anthony Grant, and anyone Nova's
   ownership is later transferred to, a perpetual, worldwide, non-exclusive, royalty-free, irrevocable
   license to use, copy, modify, distribute, sublicense and sell your
   contribution, as part of Nova or otherwise, under any license terms,
   including commercial and closed-source ones.
3. **Patents.** You grant the same parties a perpetual, worldwide,
   royalty-free, irrevocable patent license for any of your patent claims
   that your contribution would otherwise infringe, when used in Nova.
4. **You keep your copyright.** You can still use your own contribution
   however you like elsewhere.
5. **No payment or credit is owed.** Your contribution stays credited in the
   project's history, but using it creates no obligation to pay you or to
   list you anywhere else.

If your employer has rights to what you create, make sure they're fine with
these terms before you contribute.
