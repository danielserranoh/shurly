---
title: Connect Claude to Shurly
description: Let Claude create links and read their stats for you, through Shurly’s MCP server.
order: 1
---

Shurly has an MCP server. Connect Claude to it and ask for things like “shorten this link and tag it for the Q4 campaign” or “how many clicks did the Acme proposal get this week?”. Claude acts as you, so it sees and changes what your account can.

The server’s address:

```
{{MCP_URL}}
```

Use it exactly as it is, trailing slash included.

## Sign in with Google

Claude signs you in with your work Google account, so there’s nothing to copy but the address. If Claude doesn’t offer to sign in with Google, it isn’t switched on for your organization yet: [use an API key](#with-an-api-key) instead.

### Claude Code

1. In a terminal, add Shurly for all your projects:

   ```
   claude mcp add --transport http --scope user shurly {{MCP_URL}}
   ```

2. In Claude Code, run `/mcp`, choose shurly, then Authenticate. Your browser opens Shurly’s consent page, which names the app asking and where it sends you back, then Google. Sign in with your work account.

### claude.ai and Claude Desktop

1. In claude.ai, go to Settings → Customize → Connectors and choose Add custom connector. Name it Shurly and paste the address.
   On a Team or Enterprise plan, an owner adds it first, in Organization settings → Connectors, and then each person connects it from Customize → Connectors.
2. Connect it: Shurly’s consent page, then Google. Sign in with your work account.

Claude Desktop uses the connectors of your claude.ai account, so there’s nothing to add there.

## With an API key

An API key works in Claude Code whether or not sign-in with Google is on. Generate one in [Settings → API & MCP](/dashboard/settings/#api). It’s shown only once, when you generate it, so copy it right away. Then add Shurly with it:

```
claude mcp add --transport http --scope user shurly {{MCP_URL}} --header "Authorization: Bearer <your API key>"
```

<div data-mcp-key-copy hidden></div>

Anyone with the key can manage your links, so treat it like a password. claude.ai connectors sign in with Google: most organizations can’t give them a key.

## If something goes wrong

- **Your Google account isn’t accepted.** Only accounts of your organization’s Google Workspace get in. Sign in with your work account.
- **Shurly refuses your account.** Your Shurly account was closed, for example when someone removed you from the organization. Ask an owner of your organization.
- **Sign-in with Google doesn’t start.** Check the address: it has to end with a slash, exactly as above.
- **Claude says Shurly answered 401 (unauthorized) with your API key.** The key doesn’t work any more: it stops working when it’s regenerated or revoked, when you’re removed from the organization, and the first time an account made before Google signs in with Google. Generate a new one in [Settings → API & MCP](/dashboard/settings/#api) and copy it, then remove Shurly from Claude Code (`claude mcp remove shurly`) and add it again with the new key.
- **You’ve lost your key.** Shurly can’t show it again. Regenerate it in [Settings → API & MCP](/dashboard/settings/#api): the old one stops working, so add Shurly again with the new one.
