# 📺 Otaku

[![Kodi version](https://img.shields.io/badge/Kodi-20%20(Nexus)%20%7C%2021%20(Omega)-blue?style=for-the-badge&logo=kodi)](https://kodi.tv/)
[![Python](https://img.shields.io/badge/Python-3.8+-green.svg?style=for-the-badge&logo=python)](https://www.python.org/)
[![License: GPL3](https://img.shields.io/badge/License-GPL3-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/GPL-3.0)

**Otaku** is a high-performance, feature-packed anime streaming add-on for Kodi. Built on modern scraping architecture, deep multi-watchlist synchronization, intelligent episode continuity, and advanced SQLite caching, Otaku delivers an ultra-fast, seamless anime viewing experience on both desktop and low-power Android TV devices.

This project is a fork of the original **Kaito** add-on by **SwagOtaku**. All credit goes to SwagOtaku for the foundational work.

---

## ✨ Key Features

### 🚀 SmartPlay & Episode Continuity
- **Season Pack Continuity Caching**: When playing from a season pack, the torrent infohash, file listing, and episode mappings are cached in RAM and SQLite. Subsequent episodes launch via instant fast-path retrieval (`<1ms`) without rescraping.
- **Multi-Tier Scoring Heuristic**: SmartPlay automatically reorders playback candidates by continuity affinity:
  - Season pack match (`+100,000` pts)
  - Sequential episode pattern match (`+30,000` pts)
  - Same embed provider match (`+25,000` pts)
  - Matching release group (`+20,000` pts)
  - Matching video quality (`+10,000` pts)
- **Background Pre-Scraping**: Automatically initiates background scraping of the next episode during active playback. If the active season pack already covers the next episode, background scraping is skipped to conserve CPU and network bandwidth.
- **Intelligent Playback Failover**: If a stream returns 403/404 errors, fails to demux, or a cached season pack has missing files, Otaku purges the broken pack, advances down the prioritized candidate queue, and triggers a fresh scrape if all candidates fail.
- **User Toggles**: Fully configurable under **Settings → SmartPlay** (Season Pack Reuse, Quality/Group Matching, Embed Continuity).

### 📺 Local Watch History Springboard
- **Instant Local Springboard**: Transformed into a 100% local, zero-lag springboard for recently watched anime (`save_to_watch_history`). Items are deduplicated, prepended, and track `last_watched_episode`, `last_watched_at`, and progress badges (`[Ep X/Y]`).
- **Dynamic Menu Artwork**: The root Watch History menu item dynamically updates its thumbnail and fanart to the poster of your most recently watched anime.
- **Direct Springboard Playback & Context Actions**: Clicking any history item launches directly into the last watched episode. Includes dedicated context menu actions:
  - *Play Next Episode*
  - *Resume Episode*
  - *Browse Episodes*
  - *Remove from Watch History*

### ⚡ Watchlist Performance & Navigation Overhaul
- **Pre-Slicing Pagination**: Overhauled **Simkl** and **AniList** watchlist browsing. Raw list items are sorted and sliced in-memory *before* expensive metadata enrichment and GraphQL queries, dropping menu loading times on 1,000+ item lists from `45s+` to `<0.2s`.
- **Targeted Cache Invalidation**: Progress updates on watched episodes invalidate only the active lists (`watching`/`CURRENT` and `next_up`) across **Simkl**, **AniList**, **Kitsu**, and **MyAnimeList**, preserving large Completed and Plan to Watch caches.
- **Parallel Watchlist Sync**: Dispatches watch progress updates concurrently across all enabled watchlist flavors using `ThreadPoolExecutor`, reducing sync delays from 3–6s down to `<1s`.

### 🎮 Player, Remote & Dialog Refinements
- **AniSkip 500ms Precision Polling**: Dropped intro skip polling interval to 500ms for instantaneous intro skip dialog and auto-skip triggering on the beat.
- **Outro Polling Drop to 1s**: Synchronized outro/playing next dialog polling to 1s for timely next-episode prompts matching AniSkip timestamps.
- **Android TV Remote Enter/Select Fix**: Resolved physical Select/Enter/DPad Center button unresponsiveness on `skip_intro.py` and `playing_next.py` dialogs.
- **Remote Long-Press Context Menu**: Direct access to File Select, Download, and Info via long-press (`Menu` / `Select`) on Android TV remotes within Source Select.
- **Cross-Playback Resume Bookmarking**: Persistent Kodi resume bookmarks across normal playback, widgets, and SmartPlay via `Files.SetFileDetails`, cleanly resetting to 0 on episode completion.
- **Perpetual Token Auto-Refresh**: Background service token refresh loop running every 30 minutes, preventing 401 unauthorized errors on always-on devices.
- **Audio/Subtitle Boundary Guards**: Comprehensive bounds checks on stream index selection to prevent player crashes on media with missing or empty audio/subtitle tracks.

### 💾 Unified Cache & Database Hub
- **Dedicated Hub**: Consolidated Cache category with live database statistics, multi-database VACUUM & optimization, integrity checks, and remote mapping synchronization.
- **Granular Cache Clearing**: Dedicated actions to **Clear All Cache**, **Clear Scrapers Cache Only**, **Clear Debrid Cache Only**, or **Clear Metadata Cache Only**.
- **Global Context Menu**: "Clear Cache" context menu option available across all Otaku items and directories.
- **Customizable TTL Sliders**: Adjust TTLs for Scrapers Cache (1–72h), Torrents Cache (1–168h), Metadata Cache (1–72h), and Airing Calendar Cache (1–48h).
- **Automated Expired Cache Pruning**: Background maintenance automatically purges dead cache rows and expired debrid entries older than 14 days on startup.
- **Dynamic SQLite PRAGMAs**: Dynamically tuned SQLite PRAGMAs (`wal`, `synchronous=NORMAL`, `cache_size=-64000`, `temp_store=MEMORY`) with a 30s TTL cache for peak read/write throughput.

### 🔍 Scrapers & Debrid Engine
- **Supported Debrid Providers**: Real-Debrid, Premiumize, AllDebrid, Debrid-Link, Torbox, and EasyNews.
- **Early Scraping Termination**: Optional toggle to end scraper execution immediately once cached debrid streams are found (`Settings → Scrapers → Terminate on Cached Torrents`).
- **Rescrape with Live Re-Verification**: Rescrape forces a fresh query (`force_refresh=True`), purging stale results from SQLite and RAM while bypassing local debrid cache to re-verify external availability across all candidate hashes.
- **Shallow Dict Cloning**: Worker spawning utilizes shallow dict cloning, delivering a 15–30x speedup over recursive deepcopy.
- **Chunked POST Hash Checking**: Large torrent sets on Premiumize are verified in 100-hash POST batches, eliminating HTTP 414 (*Request-URI Too Long*) errors.

---

## 📌 Requirements

- **Kodi 20 (Nexus)** or **Kodi 21 (Omega)** (or later).
- Python 3.8+ runtime (standard in Kodi 20+).
- An active Debrid account (Real-Debrid, Premiumize, AllDebrid, Debrid-Link, Torbox, or EasyNews) is strongly recommended.

---

## 🔧 Installation & Updates

### 📥 Install via Repository (Recommended)
Installing via the repository ensures you receive automatic updates:
1. Open Kodi and navigate to **Settings (Gear) → File Manager → Add source**.
2. Enter the source URL: `https://goldenfreddy0703.github.io/repository.otaku`
3. Name the source `repository.otaku` and click **OK**.
4. Go to **Settings → Add-ons → Install from zip file** and select `repository.otaku`.
5. Choose `repository.otaku-1.0.zip`.
6. Go to **Install from repository → Otaku Repository → Video add-ons → Otaku** and click **Install**.

### 🛠️ Manual Installation
If installing manually from zip files, install dependencies in order:
1. `context.otaku` (Context Menu add-on)
2. `plugin.video.otaku` (Main add-on)

> [!NOTE]
> After updating the add-on, it is recommended to run **Settings → Cache & Database → Clear All Cache** or use the **Clear Cache** context menu action to ensure new database schemas and features take effect immediately.

---

## ⚙️ Configuration & Tuning Guide

### ⚡ Low-Memory & Android TV Devices (e.g. Onn 4K, Fire TV, Shield)
- **RAM Cache**: Under **Settings → Cache & Database**, toggle **Enable Kodi RAM Cache** according to your device's physical memory.
- **AdvancedSettings Buffer**: Ensure your `advancedsettings.xml` does not allocate excessive memory for `filecache.memorysize` (e.g. 64 MB is ideal for 1.5GB–2GB RAM streaming sticks; avoid allocating 1GB+ buffers which can cause `std::bad_alloc` crashes).
- **Terminate on Cached Torrents**: Under **Settings → Scrapers**, enable **Terminate on Cached Torrents** to drop scraping wait time from ~15s to ~3s as soon as cached streams are found.
- **SmartPlay Continuity**: Under **Settings → SmartPlay**, leave **Reuse Cached Season Pack** enabled to enjoy instant playback across consecutive episodes.

---

## 🛠 Troubleshooting

- **Menu Takes Long to Load**: Run **Clear Metadata Cache Only** in **Settings → Cache & Database**, or update to the latest version to take advantage of in-memory pre-slicing pagination.
- **Streams Not Resolving or 403 Errors**: Use the **Rescrape** context menu option. This bypasses local debrid cache and live-checks hash availability with your provider.
- **Context Menu Missing on Episodes**: Context menu options (Source Select, Rescrape, Clear Cache) are active even while media is playing or paused in the background.

---

## 🤝 Community & Support

- 💬 **Discord Support:** Join the [Addons4Kodi Discord](https://discord.gg/SqX7buB) for Otaku community discussion.
- 🐛 **Bug Reports & Issues:** [GitHub Issues](https://github.com/Goldenfreddy0703/Otaku/issues)
- 📖 **Otaku Wiki:** [Otaku Wiki Documentation](https://github.com/Goldenfreddy0703/Otaku/wiki)

---

## ⚠️ Disclaimer

Otaku is and always will be free and open-source. None of its code or resources may be sold or redistributed for any commercial purposes. This add-on and its developers **DO NOT** host, create, or distribute any of the media content displayed in the add-on; it simply interfaces with ad-financed public websites and user-authorized Debrid accounts. It is the user's responsibility to ensure compliance with applicable local laws and regulations.

---

## 📜 License

Otaku is licensed under the **GNU General Public License v3.0 (GPL-3.0)**.  
See the [GPL-3.0 License](https://opensource.org/licenses/GPL-3.0) for full details.
