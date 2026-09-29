---
title: Read your analytics
description: What a link’s page and a campaign’s page count, and how to read each number.
order: 3
---

Every link and every campaign has a page with its numbers. Open a link from [Links](/dashboard/), or a campaign from [Campaigns](/dashboard/campaigns/).

## What counts

- **A click** is someone opening the short link. Bots, and the previews that social networks and chat apps fetch, are kept apart: they never count as clicks.
- **An email open** is a link’s tracking image loading in an email ([how to add it](/manual/make-a-campaign/#send-the-links)). Apple Mail loads the images of every email it receives, read or not, so opens run high.
- **Nobody’s full address is kept.** Shurly shortens visitors’ IP addresses before storing them, and the pages show countries, never addresses.

## A link’s page

At the top, its numbers since it was made: **Clicks**, **Email opens**, **Countries** and the **Last click**.

**Analytics** covers a period: the last 7, 30 or 90 days, or **Custom** for any dates up to two years apart. The line under its title gives the dates, with the period’s clicks and email opens.

- **By time**: clicks per day, week or month, and when they come, by time of day and day of the week. When the link has email opens, **Show** switches between clicks and opens.
- **By context**: operating systems, browsers and devices, and where people came from. **Direct** means no referrer: the link was typed in, or opened from an email app or a document.
- **By location**: countries. **Unknown** is a visit Shurly couldn’t place.
- **Visits**: one at a time, newest first, 20 a page: when, what it was (a click, an email open or a bot), and the country, browser, operating system, device and referrer. Choose **Clicks**, **Email opens**, **Bots** or **All**.

**Export CSV** downloads every visit of the period, bots included, with its browser’s full description (the user agent).

Each chart has a **Table** button, for the same numbers as a table. Days and hours are in your time zone: until you set one in [Settings → Account](/dashboard/settings/#account), they’re in UTC, and the page says so.

## A campaign’s page

At the top, its numbers since it was made, about people:

- **Clicked**: the recipients who clicked their link at least once, as a share of them all.
- **Opened**: the recipients who opened your email at least once. Apple Mail’s automatic opens count too, so it runs high.
- **Recipients**: one per link.
- **Clicks**: every click on the campaign’s links.

**Analytics** works as on a link’s page, over all the campaign’s links, but without **Visits**: nobody’s visits are listed one by one.

**Recipients** lists the people, 50 at a time:

- **Search** for any value in their row, or their link’s code.
- **All**, **Clicked**, **Opened** and **Not yet** each show how many people match your search.
- Sort by **Short link**, **Clicks**, **Opens** or **Last click**: select a column’s name, and again to reverse the order. On a phone, use **Sort by**.
- Tick people to copy their links, one per line.
- **Export CSV** downloads everyone who matches your search and filter, in the list’s order: their columns, their link, their clicks and opens, and when they first clicked, last clicked and last opened.
