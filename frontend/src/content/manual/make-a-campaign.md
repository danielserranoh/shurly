---
title: Make a campaign from a CSV
description: One personal link for each person on a list, so you know who clicked and who opened your email.
order: 2
---

A campaign turns a list of people into personal links: one per row of a CSV, all going to the same page. Send each person their own link, and the campaign’s page shows who clicked, who opened your email, and who hasn’t yet.

## What the CSV needs

- **A header row**, with a name for every column and no name used twice.
- **One row per person**, with a value in every column. Each row becomes one link.

Each person’s row travels with their link. When they open it, the page they land on gets the row’s values as parameters in its address, like `?firstName=Ana&company=Acme`, so it can greet them by name. That also puts those values in their address bar and in that site’s analytics: keep to what you’re happy to share that way, a first name and a company rather than a phone number. Shurly warns you when a column’s name looks like an email address, a phone number or an ID.

When someone shares their link on a social network or in a chat app, the preview it shows never carries their row.

## Make it

1. In [Campaigns](/dashboard/campaigns/), choose **New campaign**.
2. **Details.** Name the campaign and paste the page everyone should land on. It’s your organization’s, so your team sees it; switch on **Personal campaign** to keep it to yourself.
3. **Recipients.** Drop your CSV in or choose the file, or paste its text. If something needs fixing, Shurly says what before you go on.
4. **Review.** Check the name, the destination, how many links it makes and the columns it adds. Then create the links.

## Send the links

On the campaign’s page, **Export links** downloads a CSV with every person’s row and their link: `short_code`, `short_url` and `original_url`, then your columns. Use it in your mail merge, with each person’s `short_url` where their link goes.

To know who opened your email, add each person’s tracking image to it: their `short_url` with `/track` at the end, as a one-pixel image. In the email’s HTML, with your mail merge’s field for `short_url` in place of `SHORT_URL`:

```
<img src="SHORT_URL/track" width="1" height="1" alt="">
```

Opens only count in email apps that load images, and Apple Mail loads them for every email it receives, read or not, so opens run high. [What the numbers mean](/manual/read-your-analytics/#a-campaigns-page).

## If something goes wrong

- **“Rows … don’t have N columns like the header.”** Those rows have more or fewer values than the header has names. A comma inside a value splits it in two: put that value in double quotes.
- **“Column names must be unique.”** Two columns share a name. Rename one.
- **The page opens without the person’s details.** Check that the destination keeps the parameters in its address: some sites drop what they don’t recognize when they redirect.
