# Deploy your own host

**tau-host** is the Cloudflare Worker behind hosted taus: GitHub sign-in, the owner's app in the browser, and a chat page for every public web sub-tau. Deploy it into your own Cloudflare account and you have the hosted app for yourself: the same browser chat as on [tau.getporti.com](https://tau.getporti.com), with nobody but you able to read it. This is the third way of [Three ways to start](../getting-started/three-ways.md); the decision is [ADR 0013](../adr/0013-hosted-taus-handles-and-public-pages.md).

This page uses example values: the host `tau.example.com` and the GitHub login `alice`. Put your own in their place.

## What you get

| At | What it is |
|---|---|
| `https://tau.example.com/` | The landing page: what a hosted tau is, who can read what, **Sign in with GitHub** |
| `https://tau.example.com/app` | Your tau: chat, sessions, sub-taus, approvals, settings, export and account deletion |
| `https://tau.example.com/@alice/coach` | A chat page for anyone, for each sub-tau you make public with a web page |
| `tau.example.com/@alice` | Your tau's address on the tau network (see [The universe](#8-the-universe-optional)) |

tau-host has no hub and no container. Each tau is one SQLite-backed Durable Object that sleeps when nobody talks to it, and the brain is a small agent loop that calls your provider's HTTP API directly. That is why it has no device tools, nodes, voice, memory or routines: those stay with the [local hub](../getting-started/install.md).

## 1. Prerequisites

| You need | Why |
|---|---|
| A **Cloudflare account** | tau-host runs there, on the Workers Free plan for a handful of taus ([Costs](#costs-and-limits)). |
| **[bun](https://bun.sh)** 1.3 and **Node.js 24** | bun installs the packages and runs the scripts; Wrangler, Cloudflare's CLI, runs on Node.js. |
| A clone of the repository | tau-host is deployed from `cloud/host`. |
| A **GitHub account** | Sign-in goes through a GitHub OAuth App you create. |
| A domain on Cloudflare (optional) | For a host such as `tau.example.com`. Without one the host is `tau-host.<your-subdomain>.workers.dev`. |
| A model key | From Anthropic, OpenAI or Google Gemini. You paste it into the app, not into a file. |

=== "macOS"

    ```sh
    brew install oven-sh/bun/bun
    # Node.js 24 from https://nodejs.org, nvm or Homebrew
    ```

=== "Linux"

    ```sh
    curl -fsSL https://bun.sh/install | bash
    # Node.js 24 from https://nodejs.org, nvm or your distribution
    ```

```sh
git clone https://github.com/fport/tau.git
cd tau/cloud/host
bun install
```

## 2. Pick the host name

The name goes into the GitHub OAuth App, so pick it first.

- **With a domain on Cloudflare:** a name in that zone, `tau.example.com`. The deploy attaches it to the Worker as a custom domain and Cloudflare creates the DNS record and the certificate. The name must not have a DNS record yet.
- **Without one:** `tau-host.<your-subdomain>.workers.dev`. Your `workers.dev` subdomain is shown in the Cloudflare dashboard under **Workers & Pages**.

## 3. Create a GitHub OAuth App

On GitHub, open **Settings → Developer settings → OAuth Apps → New OAuth App** and fill in:

| Field | Value |
|---|---|
| Application name | anything, such as `tau (tau.example.com)` |
| Homepage URL | `https://tau.example.com` |
| Authorization callback URL | `https://tau.example.com/auth/callback` |

Register it. Keep the **Client ID** for the next step, then choose **Generate a new client secret** and leave the page open: GitHub shows the secret only once, and you paste it in [step 6](#6-set-the-secrets). Do not save it in a file or type it into a command line.

With a `workers.dev` host, both URLs use that name: `https://tau-host.<your-subdomain>.workers.dev` and `https://tau-host.<your-subdomain>.workers.dev/auth/callback`.

## 4. Configure

```sh
bun run configure --route tau.example.com --client-id <client id> --signup alice
```

`configure` writes `wrangler.jsonc` (gitignored) from `wrangler.example.jsonc`, and `.dev.vars` for local development. No secret goes into either file for a deployment.

| Option | Effect |
|---|---|
| `--route HOST` | Serves tau-host on the custom domain `HOST` and sets `PUBLIC_HOST` to it. Leave it out for `workers.dev`; the host is then the request's host. |
| `--client-id ID` | The OAuth App's client id, `GITHUB_CLIENT_ID`. Without it, GitHub sign-in stays off. |
| `--signup VALUE` | Who may create an account, `SIGNUP`: your own GitHub login (`alice`) for an own host; a comma list (`alice,bob`) for a few people; `open` for anyone with a GitHub account. |
| `--force` | Replaces an existing `wrangler.jsonc`, carries its routes and vars over unless you give them again, and keeps the old one as `wrangler.jsonc.bak`. |

Keep `SIGNUP` to your own login unless you mean to host others: on an `open` host, you are the operator who can read everyone's tau.

## 5. Deploy

```sh
bunx wrangler login     # once, in a browser
bun run deploy          # builds the app and deploys the Worker with its two Durable Objects
```

The deploy prints the Worker's URL. Until the secrets are set, the landing page loads but sign-in says it is not set up yet.

## 6. Set the secrets

tau-host needs two secrets. Neither is ever written into `wrangler.jsonc`, and neither should end up in your shell history.

**`GITHUB_CLIENT_SECRET`**, the OAuth App's client secret. Wrangler asks for it with a hidden prompt; paste the secret from the GitHub page:

```sh
bunx wrangler secret put GITHUB_CLIENT_SECRET
```

**`VAULT_KEY`**, 32 random bytes in base64url. It seals every provider key at rest (AES-256-GCM, with a key derived per handle). Generate it into a file only you can read, hand the file to Wrangler on stdin, then move the value into your password manager and delete the file:

```sh
(umask 077 && node -e "process.stdout.write(require('node:crypto').randomBytes(32).toString('base64url'))" > vault-key.txt)
bunx wrangler secret put VAULT_KEY < vault-key.txt
# copy vault-key.txt into your password manager, then:
rm vault-key.txt
```

Keep that copy. Without the same `VAULT_KEY`, the stored provider keys cannot be opened and every owner has to paste theirs again; changing it has the same effect. `bunx wrangler secret list` shows the names of the secrets that are set, never their values.

Check the deployment:

```sh
curl -s https://tau.example.com/api/host/whoami   # {"error":"unauthorized"}: no session yet, as expected
```

## 7. Sign in and set up your tau

1. Open `https://tau.example.com` and choose **Sign in with GitHub**. GitHub asks once whether to authorize your OAuth App.
2. You come back as `@alice` and the set-up opens. Pick the provider (Anthropic, OpenAI or Gemini) and paste your key. tau-host checks it with one free request, the provider's list of models, then seals it. It is never shown again; Settings shows only the provider and the key's last four characters.
3. Choose the language (English or Turkish) and whether to list your tau in the universe. Nothing is preselected.
4. **Start** opens the app at `/app`.

In the app:

- **Chat** with your tau and switch sessions. Replies stream as they are written.
- **Sub-taus**: create one from a description (your `brain` model drafts it and you read the draft before saving) or from a template, edit it, chat with it and set its visibility: public, a web page, the visitor answers per day and up to four starters. [Public sub-taus with a web page](public-sub-taus.md) explains them.
- **Approvals**: creating a sub-tau is tier 2. The turn stops with an approval card and goes on only when you choose **Approve**; **Deny**, or ten minutes without an answer, refuses it.
- **Settings**: the key, the model ids per role (`brain` and `fast`), a monthly budget in USD (5 by default; a turn that would start over it is refused), the persona, your profile (the `user.md` of a hosted tau, never shown to others), the language, the universe listing, export and account deletion.

## 8. The universe (optional)

Listing your tau in the [universe](https://tau.getporti.com/universe) is opt-in: you choose it in the set-up and change it under **Settings → Universe listing**. A listed tau shows its handle, its public sub-taus and how many messages it exchanges with its listed contacts, never what is said.

!!! info "On the network and in the universe"
    Your taus are nodes of the tau network: a card at `https://tau.example.com/@alice/.well-known/tau.json`, an inbox, contacts on the app's Network page and `net_send` as a tier-2 tool. The Network page also joins the universe you set with `configure --universe`. A handle on a universe other than your host's own needs a claim, and a claim button in the app is not built yet; until then the universe lists your tau by its address.

## Costs and limits

tau-host is built for the **Workers Free plan**. At the time of writing, Cloudflare's daily limits are:

| Free plan, per day | Limit | What uses it |
|---|---|---|
| Worker requests | 100 000 | every page load, API call and chat message |
| CPU time per request | 10 ms | the Worker's own work; waiting for the provider does not count |
| Durable Object requests | 100 000 | every call into your tau's object |
| Durable Object duration | 13 000 GB-s | wall-clock time while an object is awake: a streaming answer keeps it awake for as long as it takes; 13 000 GB-s is about 28 hours of one awake object a day |
| Durable Object storage | 5 GB in total | settings, sessions, sub-taus and the spend ledger (tokens and dollars, never text) |

Past a limit, that kind of request fails until 00:00 UTC. For yourself, or a handful of people, the Free plan is enough: a tau's object sleeps between messages and costs nothing then. **Workers Paid** (from $5 a month) is for more: many taus, or many long turns and busy visitor pages every day that keep objects awake. Check [Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/) and [Durable Objects pricing](https://developers.cloudflare.com/durable-objects/platform/pricing/) for the current numbers.

The model calls are paid by each owner's own key, never by the host. Each tau's monthly budget caps them, visitor answers included, and the provider console's own spend limit stays the last line of defence ([ADR 0011](../adr/0011-budgets-in-tau-no-litellm.md)).

## Who may sign in

- **Add people:** `bun run configure --force --signup alice,bob`, then `bun run deploy`.
- **Close sign-ups:** `bun run configure --force --signup closed`, then `bun run deploy`.
- Existing accounts can always sign in; `SIGNUP` only decides who may create a new one. Removing a login from it does not remove that account.
- A handle stays with its GitHub account: a renamed login keeps its handle, and another account whose login matches an existing handle is refused.

## Update

```sh
cd tau
git pull
cd cloud/host
bun install
bun run deploy
```

When `wrangler.example.jsonc` changed (a new binding or migration), run `bun run configure --force` before the deploy; it carries your routes and vars over. Secrets and the Durable Objects' data stay across deploys.

## Back up and export

- **Your tau:** **Settings → Export → Download JSON** saves everything of your tau as one file, without the provider key. There is no automatic backup, so export now and then.
- **`VAULT_KEY`:** keep the copy from step 6 in your password manager. With it, the sealed provider keys stay usable after any redeploy.
- **The client secret** can be regenerated on GitHub at any time; set it again with `bunx wrangler secret put GITHUB_CLIENT_SECRET`.

## Delete

1. In the app, **Settings → Delete account** deletes your tau, its sub-taus, sessions and visitor chats and your account on the host. Type your handle to confirm. It cannot be undone.
2. To remove the host itself, run `bunx wrangler delete` in `cloud/host`, and delete the OAuth App on GitHub.

## Troubleshooting

| You see | Why, and what to do |
|---|---|
| "GitHub sign-in is not set up on this host yet" | `GITHUB_CLIENT_ID` is empty (`bun run configure --force --client-id …`, then deploy) or `GITHUB_CLIENT_SECRET` is not set. |
| GitHub says the `redirect_uri` is not associated with the application | The OAuth App's callback URL must be exactly `https://<your host>/auth/callback`, with the same host you configured. |
| "This host does not take new accounts for your GitHub login" | `SIGNUP` does not list your login. |
| "The key cannot be opened on this host (VAULT_KEY)" | `VAULT_KEY` changed or is missing. Set the saved one again, or paste your provider key again in Settings. |
| "This month's budget is used up" | Raise the budget in Settings, or wait for the first of the month (UTC). |

## Run it locally first

After `bun run configure`, `bun run dev` serves tau-host at `http://127.0.0.1:8791` with a development sign-in (any login, no GitHub) and a scripted fake provider that needs no key, so you can try the app and a web sub-tau without an account. [`cloud/host/README.md`](https://github.com/fport/tau/blob/main/cloud/host/README.md) shows it, with every route, the storage and the tests.
