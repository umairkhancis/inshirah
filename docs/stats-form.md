# The usage form

`inshirah --stats` shows a user the numbers their copy has counted and offers to
open a Google Form with those numbers already filled in. This is how that form
gets created, and how the two constants in `inshirah/core/share.py` get their
values.

Until they have values, `--stats` still works — it prints the counts and says
there is nowhere to send them. That is the correct behaviour for a fork, and it
is why nothing here is required to ship.

The form lives in the Google account that creates it, and so does the
spreadsheet. Create it signed in as whoever should own the responses.

---

## 1. Create the form

1. [forms.google.com](https://forms.google.com) → **Blank form**.
2. Call it something a stranger would understand if they saw the tab —
   *Inshirah usage* — because they will see it.
3. **Settings** → turn **Collect email addresses** **off**, and leave
   **Limit to 1 response** **off**. Both of them require a Google sign-in, and
   a sign-in wall in front of a voluntary count is how you collect nothing.

## 2. Add one question per number

Each is a **Short answer**. The title of the question is what a person reads, so
write it for them, not for the schema — but keep a note of which payload key
each one is, because step 4 needs it.

The keys are exactly the ones `usage.summary()` returns:

| key | the question |
|---|---|
| `inshirah` | Version |
| `os` | Operating system |
| `days` | Days since first use |
| `sessions` | Sessions |
| `conversations` | Conversations |
| `turns` | Turns |
| `edits` | Messages edited |
| `edits_user` | …of which your own questions |
| `edits_assistant` | …of which the model's replies |
| `resends` | Questions edited and re-asked |
| `threads` | Threads branched |
| `shell_holds` | `!command` outputs held |
| `exports` | Exports written |
| `sessions_2plus_edits` | Sessions with 2+ edits |

A form with fewer questions is fine: keys the form has no question for are
dropped, so you can start with `edits`, `sessions` and `sessions_2plus_edits`
and add the rest later without shipping a release.

Worth adding one more, which is not a number and is not sent by the program:

> **If you would be up for a 20-minute conversation, leave a GitHub handle or an
> email.** *(Optional.)*

It stays empty unless the person types into it, which is what makes it the one
field here that can start a conversation rather than end one.

## 3. Point the responses at a sheet

**Responses** tab → the Sheets icon → **Create a new spreadsheet**. It lands in
the Drive of the account that made the form. Every submission is a row.

**Publish it read-only** — Share → *Anyone with the link* → **Viewer**. The
reason this collection is trustworthy is that anyone can look at all of it; a
private sheet turns a checkable claim back into a promise.

Then add the link to the README, in *The one number this project would like*,
and only then — the sentence is a claim, and it is not true until the sheet is
actually readable:

> Every response ever submitted is [public](<the sheet link>); you can read the
> whole thing before you add to it.

## 4. Read the field ids

Google names each question `entry.<digits>` and does not show you the number
anywhere in the editor. The way to get them is to ask for a pre-filled link:

1. ⋮ (top right) → **Get pre-filled link**.
2. In **every** box, type **the payload key** from the table above — literally
   `edits` in the Messages edited box, `sessions` in the Sessions box.
3. **Get link** → **Copy link**.

Then:

```sh
python scripts/stats_form.py '<the link you copied>'
```

It prints `FORM_ID` and `FIELDS`, ready to paste into
`inshirah/core/share.py`. It also tells you which keys have no question yet and
which boxes were filled in with something that is not a key — which is what a
typo in step 2 looks like.

## 5. Check it end to end

```sh
INSHIRAH_FORM_ID=<the id> inshirah --stats
```

Answer `y`. Your browser opens the form with the numbers in it. Press Submit,
then look at the sheet. The env var exists so this can be done, and so the form
can be replaced later, without a release.

---

## What must stay true

The thing being protected is not the data, it is the reason anyone runs this
program over their own source code.

- **Never add a field that is not a count.** `tests/test_privacy.py` asserts the
  payload is exactly the fourteen keys above and that all but two are integers.
  That test failing is not an inconvenience to route around; it is the test
  doing its job.
- **Never submit for the user.** Google will accept a `formResponse` URL that
  submits on page load, which would save one click and cost the property that
  the person sees the payload at the moment it is sent. The consent is not the
  `y` in the terminal alone — it is the `y` *and* the form they can still close.
- **Never make it the default, and never nag.** It runs when someone types
  `--stats`. There is no prompt on exit, no counter of how many times they have
  declined, and nothing that treats silence as yes.
- **If a real backend ever becomes worth it**, the thing to preserve is not this
  mechanism but its property: that what leaves is readable by the person it
  leaves. See `docs/commercialization.md` §8.
