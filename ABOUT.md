# Bibliocapsa

**Your whole library, digital *and* physical, in one private, self-hosted home, with the deepest KOReader integration anywhere.**

## What it is

Bibliocapsa is a self-hosted personal library manager that brings your entire book collection together in one beautiful place: the ebooks in your Calibre library *and* the physical books on your shelves, side by side. It runs on your own hardware in Docker, so your reading life stays private, ad-free, subscription-free, and entirely yours.

It sits gracefully on top of an existing Calibre library, reading it safely without ever modifying it, unless you deliberately choose to push a change back. Around that core it adds a modern web experience, multi-user access for the whole household, the most complete KOReader integration available, and tracking for the paper books that most software ignores completely.

## Why it's different

Most tools make you choose a lane. Cataloging sites and reading trackers live in someone else's cloud and only know about titles you type in. Calibre's built-in web interface is powerful but utilitarian and single-user. Commercial reading apps lock you into one device ecosystem and quietly own your data. OPDS servers hand books to your e-reader but stop there, and getting KOReader fully set up usually means stitching together a pile of separate, half-maintained services.

Bibliocapsa refuses the trade-offs:

- **One library for everything you own.** Digital editions, physical copies, and books you own in *both* formats, unified, filterable, and searchable together. Read/Unread status and "Date Read" span both formats as a single concept, not two disconnected systems.
- **The complete KOReader experience, built in.** Catalog, position sync, *and* reading-statistics sync, all native, all behind one account and one URL (more on this below).
- **Built for a household, not just one reader.** Individual accounts for every family member, with optional per-member content restrictions: younger readers only see the genres you allow, while everyone keeps their own reading history, ratings, private shelves, and statistics.
- **You own your reading data.** Reading positions, reading-time statistics, ratings, and history all live on *your* server. Nothing is mined, sold, or held hostage behind a login you don't control.
- **Respects your existing setup.** Your Calibre library is opened read-only by default. Edits you make in Bibliocapsa are staged and only written back through a deliberate, confirmed sync, so the tool can never quietly corrupt years of careful curation.
- **Genuinely pleasant to use.** A clean, modern interface with multiple color themes and font schemes that follow your account across devices, not a spreadsheet with a web skin.

## ⭐ First-class KOReader integration, all built in

KOReader is the favorite reading app of serious e-ink users, and most setups force you to cobble together a stack of separate servers and plugins to make it sing: one thing for the catalog, a flaky third-party server for sync, something else again for statistics. **Bibliocapsa is all of that, natively, behind a single account and a single URL.**

- **📚 OPDS catalog.** Browse and download your whole library straight onto the device. No cables, no sideloading.
- **🔄 Reading-position sync (KOSync).** A complete sync server built right in, so you always resume exactly where you left off, across every device. No more broken, abandoned sync containers; this one is maintained, fast, and tied to your own account.
- **📊 Reading-statistics sync (WebDAV).** KOReader's detailed reading stats flow back to *your* server and power a built-in statistics dashboard: time read, pages turned, and per-book reading sessions, **per user**. Your reading analytics live with you, not in a company's cloud.

Set it up once with your Bibliocapsa username and password, point KOReader at one address, and the catalog, your place in every book, and your reading stats all just work, privately, and without a single external service.

## Feature highlights

**A library that looks the part**
- Cover-forward grid with adjustable density, responsive from phone to desktop
- Browse by series, author, or genre
- Six color themes and three typography schemes, with theme-aware icons and favicons
- Fast, virtualized scrolling even across thousands of titles

**Find anything**
- Title/author search *and* true full-text search **inside** your books' content
- Read EPUBs and PDFs right in the browser, with search inside the reader
- Sort by title, author, date added, or date read; filter by format and read status; collapse series to a single cover

**Physical books, finally first-class**
- Add paper books by hand, or import your reading history from a CSV export, choosing which shelves mean "I own this physically"
- Automatically generates clean, Calibre-style covers for physical books that lack artwork (regenerate the look or upload your own)
- Track shelf/room location and who you've lent each book to

**Reading life, tracked and yours**
- Per-user read history that records every time you finish a book, with your re-reads laid out by date
- Personal star ratings plus optional community ratings
- A reading-statistics dashboard (time, pages, per-book sessions) fed straight from KOReader
- "Currently Reading," pulled from both KOReader and manual status

**Rich metadata, automatically**
- Auto-fill missing descriptions, page counts, publishers, and cover art from open metadata sources, in bulk or on demand
- Full support for Calibre custom columns, edited in-app and synced back on your terms
- Smart, rule-based shelves alongside hand-curated ones (shared or private)

**Private and easy to run**
- Self-hosted with Docker; a single bundled reverse proxy puts the whole app behind one clean URL (works smoothly behind a tunnel or HTTPS domain)
- Sensible security built in: per-account access control, login rate-limiting, sanitized content, and guarded external requests
- No telemetry, no cloud dependency, no subscription

## In one line

**Bibliocapsa is the private, self-hosted home for everything you read, digital and physical: beautiful to look at, built for the whole family, with the most complete KOReader integration anywhere, and it never asks you to give up ownership of your own library.**
