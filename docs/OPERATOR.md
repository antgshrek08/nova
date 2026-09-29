# Nova operator and coursework

This branch adds durable desktop workflows, Canvas drafts and submission receipts, account preparation, downloads and a budget ledger to the existing agent. The School screen contains operator controls, draft review, assignment authorization, screenshot evidence and activity.

## Using it

1. Open the updated Nova app. These changes are integrated into the main checkout and the packaged app; future source edits still require a rebuild/restart.
2. Open Canvas in Nova's browser and sign in. Coursework reads use that browser's cookies; a calendar feed alone is insufficient. Personal Canvas API tokens are not required.
3. Choose an assignment in School → Operator or paste its Canvas URL. Read its instructions and authorize submission for 24 hours if automatic submission is wanted. The grant is bound to the signed-in Canvas account and exact assignment.
4. Ask Nova in chat to do that assignment. It can read instructions, rubric and linked resources, prepare text/files/a URL, then submit supported forms. Essay instructions require topic selection before writing and source verification.
5. Review the draft and Canvas receipt. An uncertain outcome blocks another attempt until its receipt is reconciled. Stop latches across model tools; only the user-facing Resume control clears it.

Read-only mode refuses modifications. Guarded mode retains normal approval cards. Operator commits, purchases and ledger changes require confirmation even in Full mode. These are workflow controls within Nova; Full mode still provides broad filesystem/shell access and is not a security sandbox.

## Desktop, accounts and downloads

Desktop steps use the existing smooth cursor and multi-monitor mapping, capture before/after screenshots, and ask the configured vision model to verify the expected outcome. Ambiguous evidence is not success. Windows typing now supports Unicode and checks Stop and the corner fail-safe between characters. Completed workflows retain site landmarks, steps, attempt history and timing; failures preserve the last successful playbook.

Visible screen grounding/verification currently uses Nova's existing OpenRouter vision integration and its spending limit. It requires a configured working model/key, an unlocked Windows desktop and a visible browser. This is not an entirely local DolphinCoder-only operator. Native mouse grounding against the user's real Canvas installation has not been exercised by this development pass.

Account preparation generates a password directly into the existing vault. Filling requires an exact HTTPS origin and one password field; the model receives no password. Signup completion still needs the appropriate website workflow, confirmation and email verification. CAPTCHA/MFA require user intervention.

Downloads are capped at 50 MB and record source, final URL, path, size and SHA256. They are never automatically executed. Public-address validation is a best-effort network check, not a network sandbox. Installer execution remains subject to the normal approval workflow.

## Budgets

Money is recorded in integer cents with an explicit end time. `operator_purchase` reserves the full checkout total, including tax/shipping, before acting. Executing and uncertain purchases count against the cap. A receipt settles a reservation; evidence of cancellation/no charge is required to release one. Revenue requires a real transaction reference and net results subtract expenses. These checks enforce the dedicated purchase workflow; they cannot restrict an arbitrary shell command or manually operated browser.

## Supported Canvas forms and limits

Text entry, file upload and website URL forms are supported. The external-homework adapter adds embedded-frame reading and visible input for Knewton Alta; it uses the same signed-in Canvas browser instead of switching to the general Onyx session. Quizzes, media recordings and other custom institutional forms may still need separate adapters. Selectors can require updates if the institution changes its interface.

External homework uses `coursework_external` for inspection, screenshot, filling, appending text, cursor navigation, selection and visible clicks. Snapshot refs expire after actions or question changes. Math sources include MathML, LaTeX and MathJax source; screenshots are passed back to image-capable models. Math editors receive keystrokes rather than textarea value assignments. `coursework_external_submit` separately shows the answer and reasoning for approval, persists the attempt before clicking, and captures feedback/evidence. An uncertain or duplicate question state cannot be replayed. The standard Canvas draft/24-hour grant workflow is separate from this per-answer review.

Live Knewton verification on Calculus 3.3b: Nova read the first question, derived `-12x^(-5/2)`, and submitted the verified expression through the reviewed tool. Knewton returned “Great work! That's correct.” and displayed 2% mastery. This verifies one real question, not completion of the assignment or universal external-provider support.

Live SmartBook verification on Microeconomics Ch 6: Connect's popup and redirects reached the assignment. The local Qwen model filled `price` and `elasticity`, submitted through the reviewed High Confidence control, and McGraw Hill returned “Your Answer correct.” This was an assisted one-question test: Qwen initially mistyped a session ID, guessed links, and needed an exact link and checked answer. The page still showed 0 of 26 concepts completed; Qwen incorrectly summarized this as 1, so the adapter now returns the literal concept counts separately from answer correctness. The whole assignment was not completed and unattended reliability is not established. The answer and before/after screenshots are recorded in the external-attempt store.

SmartBook support follows assignment popups, prioritizes Question/Answer Mode over textbook frames, exposes entered values and selected options, and routes confidence buttons through the submission review tool. Password and OTP values are excluded. The current source-launched Nova is the runtime used for this verification.

The final external-workflow build passed 439 unittest tests and 30 Onyx pytest tests. Installed Python files match the source checkout. After restart, Knewton still showed 2% mastery, one recorded activity, and Keep Going; no additional assignment answers were submitted during this update's verification.

Submission receipts check account, assignment and content. Uploads use verified byte buffers and downloaded receipt attachment hashes, so an old file with the same name and size is insufficient. Interrupted or unverified attempts remain blocked, including attempts made with a newly prepared draft for the same assignment. Preparation errors are conservatively treated as uncertain once the submission workflow begins; receipt reconciliation may require manual inspection of Canvas.

State and screenshots live in an `operator` directory beside `DB_PATH`. Screenshots can contain private on-screen content and have no automatic retention cleanup in this version. Successful grading or assignment correctness cannot be inferred from a submission receipt.

## Verification

Installed verification on 2026-09-24: 430 backend tests and four frontend tests passed; the production frontend built successfully. The packaged backend matched the source files, `/app/` returned 200, and the running app rendered at 390px without JavaScript errors or horizontal overflow. This is Chromium verification, not a physical iPhone Safari test.

Live checks confirmed retained Canvas sign-in, extraction of the comparative-analysis Word document, and opening its submission form without filling or submitting. A synthetic screenshot was read correctly by local Qwen 3.5 while retaining file-reading tools. Its subsequent answer correctly explained assignment authorization, written-draft review and automatic final clicking. Real submissions and purchases were not performed. Canvas controls now use unique named visible browser controls with authorization rechecked before final clicking; model-generated desktop coordinates are not needed for this adapter.

One economics attachment remains an unresolved Canvas `file_ref` even on the rendered assignment page. Nova reports that its contents were not read instead of presenting the same unresolved link as resolved. Assignment-specific source and AI-use instructions take precedence over generic essay guidance.

From `backend`, run the project's Python environment with `-m unittest discover -s tests -v`. Browser fixtures cover text, file and URL forms, named-control clicks, authorization revocation and opening a form without submitting. All school fixture URLs are intercepted; no live coursework is submitted by these tests.

From `frontend`, run `node --test src/lib/backendOrigin.test.js src/lib/spokenText.test.js` and `npm run build`. Four JS tests and the production build pass; the existing bundle-size warning remains.

For the isolated mobile UI smoke check, start `npm run dev:vite -- --host 127.0.0.1 --port 5177 --strictPort`, then run `tests/operator_smoke.py` using Python with Playwright installed. It mocks the operator API, checks authenticated requests and controls at 390px, and writes `nova-operator-phone.png` to the temporary directory. It tests layout and interaction in Chromium, not Safari on a physical iPhone. Vite's development-only hot-reload websocket may be blocked by Chromium's local-network checks; the app controls use HTTP and are checked independently.
