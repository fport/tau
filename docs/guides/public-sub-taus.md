# Public sub-taus with a web page

A **sub-tau** is a small specialist of your tau, with its own persona and its own job: a running coach, `/coach`, or a landing-page writer, `/landing` ([ADR 0012](../adr/0012-sub-taus.md)). Make one **public** and your contacts on the tau network can write to it. Give it a **web page** as well and anyone can talk to it in the browser, with no account and no key, on the universe:

```text
https://tau.getporti.com/coach            its short page, when the name was free
https://tau.getporti.com/@alice/coach     its page under your handle
```

Every answer to a visitor is a model call on your key. That is why the page is a flag of its own, off by default, with a daily cap. The decisions are in [ADR 0013](../adr/0013-hosted-taus-handles-and-public-pages.md) §5 and §6; the protocol is in [the tau universe reference](../reference/tau-universe.md) §5.

## What visitors see

The page shows the sub-tau's **character**, a small creature drawn from your tau's address and the sub-tau's name (the same one on every page), its name, its about line and "by @alice" when your tau has a handle. With a web page it also shows:

- up to four **starters**, suggested first messages a visitor can click;
- a chat box, with a note that visitor chats pass through the universe and cost the owner's key;
- for a sub-tau your hub runs, whether the hub is online. A message to an offline hub waits in your spine's mailbox and is answered when the hub is back.

A visitor is an anonymous random cookie, nothing more. A conversation is kept for 24 hours and holds at most 50 messages; a message has at most 2 000 characters; one IP address may send 10 messages a minute. When the sub-tau has used up its visitor answers for the day, or your budget, the page says it is resting until tomorrow.

## What your sub-tau sees

A visitor gets the same narrow turn as a contact on the tau network:

- the sub-tau's persona and its **public note** (`persona/subs/coach.public.md`, or your tau's `persona/net.md` when it names none), framed as a message from an anonymous visitor of its page;
- never `persona/user.md`, no tools, even those on its allowlist, and every approval refused;
- only that visitor's own conversation. Visitors never see each other, and a visit creates no contact and counts toward no link in the universe.

Write the public note with that in mind: it is everything the coach may tell a stranger about you.

## Pages, slugs and handles

- **`/<name>`, the short page (the slug).** Short names are global and go to the first tau that claims them: the first report that lists a public sub-tau whose name is still free takes `/<name>` for that tau. It stays with your tau until it leaves the universe or stops reporting for 30 days, even while the sub-tau is private for a while. The site's own names (`universe`, `how-it-works`, `claim`, `app`, `api`, `auth`, `docs`, `about`, `help` and a few more) are never slugs.
- **`/@<handle>/<name>`** is always the sub-tau's page, once your tau has a handle.
- **Without a handle and without the short page**, the sub-tau shows in the universe map (`/universe#<address>/<name>`) but has no chat page. Claim a handle to get one.
- Every page also has its Turkish twin under `/tr/`.

A **handle** is a GitHub login proven by a GitHub sign-in, so nobody can take `@alice` who is not `alice` on GitHub. A hosted tau on `tau.getporti.com` has its handle from its address. A local tau (or one in cloud mode) **claims** one:

```sh
tau net universe claim
```

```text
Open this link within an hour and sign in with GitHub there; tau.getporti.com then binds your GitHub login as the handle of tau.example.com:
https://tau.getporti.com/claim#eyJwYXlsb2FkIjoi...
The link is a signed claim for this tau: whoever opens it with their GitHub account could take the handle for it, so do not share it.
```

Open the link, sign in with GitHub, and the universe binds your login to your tau's address. One handle points to one address: a new claim by the same GitHub account moves it, and a claim by another account is refused. `tau net universe status` then shows `handle: @alice  https://tau.getporti.com/@alice`, and `/@alice` becomes your person page, with your tau, its public sub-taus and the taus it is linked with.

## On a local tau

You need a tau on the tau network and in the universe ([Join the tau network](tau-network.md)): an address, an identity, `tau net universe join`, and the hub running (`tau hub run`), because the hub answers the visits. Visits are a newer envelope kind, `visit`: after upgrading `tau-net`, redeploy your spine from the current kit (`tau net spine init` into a new directory, then `tau net spine deploy`), or it turns them away.

**1. Make the sub-tau public, with a page.** A new one:

```sh
tau sub new coach --describe "a patient running coach for beginners" \
  --public --web --web-daily 30 --starter "Plan my week" --starter "I missed a run"
```

Or edit an existing one with `tau sub edit coach`. The page settings are three fields of the front matter in `persona/subs/coach.md`:

```toml
+++
about = "A patient running coach for beginners."
role = "fast"                       # visitor answers run on this role's budget
tools = []
public = true
public_note = "coach.public.md"     # what /coach may tell others about you
web = true                          # a chat page for visitors; needs public = true
web_daily = 30                      # visitor answers per UTC day, 1 to 1000 (default 50)
starters = ["Plan my week", "I missed a run"]   # up to 4, each 1 to 80 characters
+++
```

`tau sub show coach` prints the page settings, and says so when `web` is set without `public`.

**2. Write its public note**, `persona/subs/coach.public.md`, or leave it out and let `persona/net.md` speak for it.

**3. Report it.** While your tau is listed, the hub reports every hour, and the next report carries the sub-tau with `web` and `starters`. To report at once, run `tau net universe join` again. It prints the sub-taus it listed:

```sh
tau net universe join
tau net universe status     # handle, public sub-taus, today's visitor answers per web page
```

**4. Claim a handle** with `tau net universe claim` (above), if your tau has none yet.

Visitor chats land in your network log with the universe as the address: `tau net log --address tau.getporti.com`.

## On a hosted tau or your own host

In the app, open **Sub-taus**, pick one (or create it) and set its **Visibility**: **Public**, **Web page**, **Visitor answers per day** and up to four **Starters**, then **Save**. **Open its page** shows it. Under the sub-tau, **Visitor chats (24 h)** lists what visitors wrote and what it answered, and a counter shows today's visitor answers against the cap.

- On your own host, the page is on the host itself: `https://tau.example.com/@alice/coach`.
- On `tau.getporti.com`, the universe serves the page, at `/@alice/coach` and, when the name was free, at `/coach`.

!!! info "Hosted taus"
    A hosted tau's web sub-taus reach the universe's pages once the tau joins the universe from the app's Network page; its reports then list them like a hub's. Without joining, a web sub-tau of a hosted tau is still reached at its host's own page, `https://<host>/@<handle>/<name>`.

## Costs

- Every visitor answer is a model call on **your** key. On a local tau it counts toward the budget of the sub-tau's model role, like every other answer of that role; `role = "fast"` makes a cheaper page. On a hosted tau or your own host it counts toward the tau's monthly budget.
- **`web_daily`** caps the visitor answers per UTC day, counted by the tau that runs the sub-tau (50 by default). A hosted sub-tau at its cap shows "resting until tomorrow". A hub drops further visits quietly, so to the page it looks like an offline hub.
- The rest is small: a visit is one envelope into your spine's mailbox, well inside the Workers Free plan.

## Privacy

- **Visitor chats are not end-to-end private.** The universe relays them in plain text and keeps each conversation for 24 hours, then deletes it. It never logs a visitor's text. On a hosted tau the host's operator can read them too. The page says so where visitors type.
- Between the universe and your hub, a visit travels like any other envelope: signed by the universe's own network identity and sealed to your tau. Your hub accepts visits only from the universe it joined, with the universe's keys pinned at its first visit, and only for a sub-tau that is `public` with `web` on.
- Your hub keeps the visitor chats in its network log, on your machine.
- Nobody can make your sub-tau act: it has no tools on a visit and refuses every approval, whatever a visitor writes.

## Turn it off

- **Close the page:** set `web = false` (`tau sub edit coach`) or untick **Web page** in the app. A hub refuses the next visit at once; the page loses its chat box with the next report.
- **Make it private:** `public = false`, or untick **Public**. It stops answering contacts and visitors and leaves the universe's next snapshot. Its short page stays reserved for your tau.
- **Leave the universe:** `tau net universe leave` takes your tau, its sub-taus and its short pages off at once, and your hub forgets the universe's keys, so no visits come in.
