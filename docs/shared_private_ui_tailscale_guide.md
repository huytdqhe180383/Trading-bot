# Shared Private UI Guide For You And Friends

This is the high-level guide for sharing the trading-bot UI with a small group
of friends while keeping it private and tied to the existing OKX bot.

## What This Setup Is

This deployment gives you:

- one server
- one running trading bot
- one OKX-connected bot instance on that server
- one private UI that multiple people can open

Recommended roles:

- **you**: admin
- **friends**: viewer

Viewer access is enough for:

- checking whether the bot is running
- reading logs
- viewing reports
- checking recent performance

Admin access adds:

- start bot
- stop bot
- restart bot
- refresh service state

## Important Scope Note

This setup does **not** create separate bots or separate OKX accounts per
friend.

It is one shared operator console for one server-side bot.

If each friend wants:

- their own OKX API keys
- their own portfolio
- their own bot process
- their own private reports

that is a different project: a multi-user or multi-tenant bot platform.

## Recommended Access Model

Use:

- Tailscale for network access
- UI allowlists for user-level access
- admin/viewer split for control rights

Do **not**:

- expose this UI to the public internet
- use Tailscale Funnel
- share one admin password with the whole group

## Two Ways To Share With Friends

### Option 1: Same tailnet

Use this if you control the Tailscale tailnet and want the cleanest setup.

Flow:

1. your friends create Tailscale accounts
2. you invite them into your tailnet
3. you add their Tailscale login emails into `UI_ALLOWED_TAILSCALE_USERS`
4. you keep only your own login in `UI_ADMIN_TAILSCALE_USERS`

### Option 2: Share the machine/service to external Tailscale users

Use this if you do **not** want to add them to your main tailnet.

Flow:

1. your friends create Tailscale accounts
2. you share the Droplet/service to them through Tailscale sharing
3. they accept the share
4. you still add their login emails into `UI_ALLOWED_TAILSCALE_USERS`

## The Three Lists You Maintain

### Allowed users

These people can open the UI:

```dotenv
UI_ALLOWED_TAILSCALE_USERS=you@example.com,friend1@example.com,friend2@example.com
```

### Admin users

These people can control the bot:

```dotenv
UI_ADMIN_TAILSCALE_USERS=you@example.com
```

### Everyone else

Everyone not in `UI_ALLOWED_TAILSCALE_USERS` is denied.

## Practical Recommendation For Your Paper-Trading Week

For the first week:

- keep **you** as the only admin
- give friends viewer access only
- let them watch reports, history, and logs
- do not let them start/stop the service yet

## Day-To-Day Usage

### You

Use the UI for:

- checking if the bot is healthy
- reviewing PnL
- restarting after maintenance
- reading recent logs from your phone

### Friends

Use the UI for:

- checking whether the bot is still running
- viewing session history
- reading the daily compact reports
- checking recent behavior during the paper-trading week

## What To Do When Someone New Needs Access

1. confirm they have a Tailscale account
2. add them to your tailnet or share the service with them
3. add their Tailscale login to `UI_ALLOWED_TAILSCALE_USERS`
4. restart `trading-bot-ui`
5. have them open the Tailscale-served URL

If you are doing the first install on a fresh Droplet and have root:

```bash
sudo bash /home/deploy/trading-bot/scripts/server/install_private_ui_root.sh
sudo bash /home/deploy/trading-bot/scripts/server/install_tailscale_ui_root.sh
```

If you do **not** have root on the server, use the rootless fallback:

```bash
bash /home/deploy/trading-bot/scripts/server/start_rootless_tailscale_ui.sh
bash /home/deploy/trading-bot/scripts/server/enable_rootless_tailscale_serve.sh
```

The first script writes the Tailscale login URL to:

```text
/home/deploy/trading-bot/.tailscale/auth_url.txt
```

Open that URL, finish authentication, then run the second script.

## What To Do When Someone Should Lose Access

1. remove them from `UI_ALLOWED_TAILSCALE_USERS`
2. if needed, remove their machine share / tailnet membership in Tailscale
3. restart `trading-bot-ui`

## When To Give Someone Admin Rights

Only do this if you trust them to control the server-side bot.

To promote someone:

1. add their Tailscale login to `UI_ADMIN_TAILSCALE_USERS`
2. restart `trading-bot-ui`

Do not give admin rights casually. Admin can stop or restart the live bot.
