# Getting this project onto a colleague's ACC terminal

**Read this before trying `git clone` from GitHub - that will give you stale code.**

## The situation

The GitHub remote is **16 commits behind** the local repo. Pushing from this
machine fails at the corporate proxy:

```
fatal: unable to access 'https://github.com/adithyad-cs/swarmos-member4-coordination.git/':
Received HTTP code 407 from proxy after CONNECT
```

So a plain clone of `origin/main` lands on `69cfd1a`, which predates **all** of
this work:

```
f9c6c59  docs: transfer instructions for a colleague's ACC terminal   <- current HEAD
4d49a43  docs: complete session handoff and kickoff prompt
69709c7  docs: session summary for UI round 3 and the verifier
3c02051  UI round 3: fix defects I-M, add headless UI contract verifier
94af5f0  docs: session summary for UI defect round 2 (F, G, H)
6ee6abc  ui: fix three defects from the second screenshot round (F, G, H)
f47c04c  docs: demo run order, judge Q&A sheet, UI-defect session summary
09074bc  UI: fix five defects found in live browser screenshots; robot artwork
aa8c7f4  C1: fix two step-authority defects; publish honest C1/C2 measurement
dae9118  Add master specification deck; re-establish regression gate
d300e44  Verify SIH26123 success criteria; add X-23/24/25 test receipts
667cabc  measure(x05): forecaster loses to persistence by 4-8x - fenced
904bfd4  feat(x01): sovereign agent mode - radio blackout, tightened envelope
4cd2c05  feat(cosim): ghost-fleet overlay and delta strip in the Compare tab
8deb942  feat(cosim): counterfactual co-simulation over HTTP and /ws/cosim
7fd5f52  test(cosim): 17 tests green - lockstep, arm independence, delta honesty
b896537  fix(ui): banner never covers content, honest cold start, one-click demo
69cfd1a  <- what GitHub currently has. DO NOT START HERE.
```

Use one of the routes below instead.

---

## Route A - clone straight off the shared filesystem (best, if it works)

On the colleague's terminal:

```bash
git clone /home/fdipglob_ai_tools/nxp60742/acc_id_work/chin_20260920 swarmos
cd swarmos
git config core.fileMode false     # see the note at the bottom
git log --oneline -1               # note the tip; compare with the source repo
```

This gives the full history with nothing to transfer manually.

**Caveat:** `/home/fdipglob_ai_tools` is `drwxr-s---`, owned by `fdipglob` with
group `fdip`. Only members of group **`fdip`** can traverse it. Check with
`id -nG | tr ' ' '\n' | grep -x fdip`. If that prints nothing, use Route B.

---

## Route B - the bundle file (works regardless of group membership)

A single-file, self-contained copy of the entire repository and its full history
has been produced and verified ("The bundle records a complete history"):

```
/home/fdipglob_ai_tools/nxp60742/acc_id_work/swarmos_latest.bundle   (about 1.6 MB)
```

Check what tip it carries before you trust it - the bundle is a snapshot and
may predate the newest commit:

```bash
git bundle list-heads /home/fdipglob_ai_tools/nxp60742/acc_id_work/swarmos_latest.bundle
```

If it is behind, ask for it to be regenerated with
`git bundle create <path>/swarmos_latest.bundle --all`.

Copy that one file to the colleague's machine by whatever means works - shared
scratch, `scp`, email, a USB stick - then:

```bash
git clone swarmos_latest.bundle swarmos
cd swarmos
git config core.fileMode false
git log --oneline -1               # note the tip; compare with the source repo
```

A bundle is an ordinary git remote, so this is a real clone: full history, all
branches, nothing lost. To point it at GitHub afterwards:

```bash
git remote set-url origin https://github.com/adithyad-cs/swarmos-member4-coordination.git
```

---

## Route C - fix the push, then clone from GitHub normally

Worth doing anyway so the remote stops being a trap. On a machine or shell that
can reach github.com:

```bash
# if a proxy is needed and you have credentials for it
git -c http.proxy="http://USER:PASS@proxy.host:port" push origin main

# or over SSH, which often bypasses the HTTP proxy entirely
git remote set-url origin git@github.com:adithyad-cs/swarmos-member4-coordination.git
git push origin main
```

`407` specifically means the proxy demanded authentication, so supplying proxy
credentials - or switching to SSH - is the likely fix. Once `origin/main` shows
`f9c6c59`, a plain `git clone` is safe again and Routes A and B become
unnecessary.

---

## After cloning, on the new terminal

```bash
cd swarmos

# 1. Confirm the interpreter - the default python3 may be 3.4.1 and unusable
/pkg/OSS-python-/3.12.0/x86_64-linux4.18-glibc2.28/bin/python3 -V

# 2. Baseline the test gate
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. \
  /pkg/OSS-python-/3.12.0/x86_64-linux4.18-glibc2.28/bin/python3 -m pytest tests/ -q
# expect: 575 passed

# 3. Baseline the UI contract verifier
PYTHONPATH=. /pkg/OSS-python-/3.12.0/x86_64-linux4.18-glibc2.28/bin/python3 \
  tools/verify_ui_contract.py
# expect: 22 pass, 1 warn, 0 FAIL

# 4. Launch
./run.sh --demo        # then open http://127.0.0.1:8770
```

Then hand the new ACC session the prompt in
`KICKOFF_PROMPT_FOR_NEW_ACC_SESSION.md`, and have it read
`HANDOFF_20260922_1124_complete_session_state.md` in full.

---

## The permission-bit gotcha

If `git status` reports ~250 modified files, check the diff:

```bash
git diff --shortstat        # "250 files changed, 0 insertions(+), 0 deletions(-)"
```

Zero insertions and zero deletions means it is only the executable bit flipping
between 644 and 755, not real work - something ran a recursive `chmod`. Silence
it per clone with:

```bash
git config core.fileMode false
```

That setting is local to each clone and is **not** carried by the repository, so
expect to set it again on the colleague's machine.
