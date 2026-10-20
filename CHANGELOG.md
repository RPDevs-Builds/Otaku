# Changelog

All notable changes to the **Otaku** Kodi Addon (RPDevs fork) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [5.3.5] - 2026-10-20

### 🚀 SmartPlay & Episode Continuity
- **Season Pack Continuity Caching**: When an episode is selected from a season pack, the torrent infohash, file listing, and episode mappings are automatically cached in RAM and SQLite (`database.set_season_pack`, `database.get_season_pack`). Subsequent episodes launch via instant fast-path retrieval (<1ms) without rescraping.
- **Multi-Tier Candidate Scoring Engine**: Built a multi-factor scoring heuristic in `ui/source_utils.py` and `windows/resolver.py` that reorders playback candidates by continuity affinity:
  - Season pack match (`+100,000` pts)
  - Sequential episode pattern match (`+30,000` pts)
  - Same embed provider match (`+25,000` pts)
  - Matching release group (`+20,000` pts)
  - Video quality match (`+10,000` pts)
- **Background Pre-Scraping with Coverage Verification**: Automatically initiates background scraping of the next episode during active playback (`ui/player.py`). Before launching background scrapers, Otaku checks if the active season pack already covers the next episode; if so, redundant scraper thread execution is bypassed to conserve CPU and network resources.
- **Intelligent Playback Failover**: If a stream returns 403/404 errors, fails to demux, or a cached season pack has missing files, Otaku automatically purges the invalid season pack cache, advances down the prioritized candidate queue, and triggers a fresh scrape if all cached candidates fail.
- **SmartPlay User Toggles**: Added user settings in **Settings → SmartPlay** for season pack reuse (`smartplay.seasonpack.reuse`), quality/group matching (`smartplay.match.quality`), and same-embed continuity (`smartplay.embed.continuity`).

### 📺 Watch History Springboard
- **High-Speed Local Springboard**: Transformed Watch History into a 100% local, zero-lag springboard for recently watched anime (`save_to_watch_history` in `Main.py` and `ui/player.py`). Deduplicates and prepends items, tracking `last_watched_episode`, `last_watched_at`, and total progress badges (`[Ep X/Y]`).
- **Dynamic Artwork & Badges**: Main menu Watch History folder dynamically displays poster artwork extracted from the most recently watched anime entry.
- **Customizable Click Action**: Added `interface.watchhistory.click` in **Settings → General** to configure primary click behavior on history items:
  - `0` (Default): *Open Episode List*
  - `1`: *Play Next Episode*
  - `2`: *Resume / Replay Last Episode*
- **Context Menu Mark as Watched Sync**: Automatically records and updates Watch History when an episode is marked as watched via the Kodi context menu (`MARKED_AS_WATCHED`).
- **Direct Springboard Playback & Context Actions**: Added rich context menu actions:
  - *Play Next Episode*
  - *Resume Episode*
  - *Browse Episodes*
  - *Remove from Watch History*

### ⚡ Watchlist Performance & Navigation Overhaul
- **Pre-Slicing Pagination (Simkl & AniList)**: Fixed severe 30–60s menu freezes and timeouts on massive lists (1,000+ anime in Currently Watching and Completed). Raw list items are now sorted and sliced into page batches in-memory *before* executing expensive metadata enrichment (`collect_meta` and AniList GraphQL queries), reducing menu loading time to `<0.2s`.
- **Targeted Cache Invalidation**: Progress updates on watched episodes now invalidate only the active lists (`watching`/`CURRENT` and `next_up`) across Simkl, AniList, Kitsu, and MyAnimeList, preserving large Completed and Plan to Watch caches.
- **Granular Remote Activity Invalidation**: Updated `_should_refresh_cache(status)` across all watchlist flavors to only invalidate the active status rather than clearing all cached lists on remote activity checks.
- **Watchlist to Episode Route Parsing Guard**: Fixed `# todo needs to be fixed` in `WatchlistIntegration.py` line 98, introducing robust variable-length path parsing and handling malformed/corrupted metadata.
- **Parallel Multi-Watchlist Progress Sync**: Concurrently dispatches watch progress updates across all enabled watchlist flavors using `ThreadPoolExecutor` in `WatchlistFlavor/__init__.py`, cutting sync delays from 3–6s down to `<1s`.

### 🎮 Player, Dialogs & Remote Control Optimization
- **Playback Stopped Watched Milestone Guarantee**: When playback is stopped after reaching the watched threshold (`pct >= update_percent`), immediately triggers watchlist scrobble and history updates before `keepAlive` tick fires, ensuring progress is never lost.
- **Episode Number Integer Coercion**: Coerced episode strings to integers in `handle_player` to prevent `TypeError` during playlist slicing.
- **AniSkip 500ms Precision Polling**: Dropped intro skip polling interval from 2000ms to 500ms in `ui/player.py` for instantaneous intro skip dialog and auto-skip triggering on the beat.
- **Outro Polling Drop to 1s**: Reduced outro/playing next dialog polling sleep from 5s to 1s for immediate synchronization with AniSkip outro timestamps.
- **Android TV Remote Enter/Select Fix**: Resolved an issue where physical Select/Enter/DPad Center button on Android TV remotes failed to trigger buttons on `skip_intro.py` and `playing_next.py` dialogs by checking `action.getId() in [ACTION_SELECT_ITEM, 7]`.
- **Remote Long-Press Context Menu on Source Select**: Added action IDs `101` (context menu) and `11` (long press / multi-info) in `windows/source_select.py` for direct context menu access on Android TV remotes (File Select / Download / Info).
- **Cross-Playback Resume Bookmarking**: Enabled persistent Kodi resume bookmarks across normal playback, widget playback, and SmartPlay via `Files.SetFileDetails`, properly resetting bookmarks to 0 on episode completion.
- **Perpetual Token Auto-Refresh**: Added a 30-minute background token refresh loop in `service.py` to prevent 401 unauthorized errors on always-on devices without tying service monitor to the cache setting.
- **Audio/Subtitle Boundary Guards**: Added bounds safety checks on stream index selection in `ui/player.py` to prevent playback crashes on files with missing or empty audio/subtitle tracks.
- **Subtitle Auto-Selection Fix**: Fixed auto-selection bug when single-track Japanese audio was present.

### 🔍 Scrapers & Debrid Engine
- **Worker Exception Safety & Freeze Elimination**: Wrapped `_torrent_sources_worker`, `_hoster_sources_worker`, `_embed_sources_worker`, `user_local_inspection`, and `user_cloud_inspection` in `try ... finally:` blocks in `pages/__init__.py`. Guaranteed provider removal on error prevents scraping dialogs from hanging for 60s when a scraper fails.
- **Early Scraping Termination on Cached Torrents**: Added `general.terminate.ontorrent` toggle ("Terminate on Cached Torrents", strings #30527 & #30528) to stop scraper execution early once cached debrid streams are found.
- **Rescrape Cache Invalidation & Live Debrid Re-Verification**: `force_refresh=True` purges stale scraper results from SQLite and RAM cache during Rescrape, while bypassing local debrid cache to re-verify external availability live across all candidate hashes.
- **Shallow Dict Cloning**: Replaced recursive `deepcopy` with shallow dict cloning in `debrid/__init__.py`, accelerating worker spawning by 15–30x.
- **Threadpool Churn Elimination**: Replaced on-the-fly thread pool instantiation with single-pass synchronous counters and optimized worker pools.
- **Chunked POST Hash Checking (Premiumize)**: Replaced query-string `GET` requests with chunked `POST` requests (`chunk_size=100`) transmitting form data `[('items[]', hash) ...]`, eliminating HTTP 414 (*Request-URI Too Long*) errors on large torrent sets.
- **Premiumize Storage Quota & File Matching**: Added safety checks for `storage_info` and `'space_used'` key existence; refined video extension validation to inspect `i.get('path')` before download URLs with query tokens.

### 💾 Unified Cache & Database Hub
- **Database Context Manager Connection Safety**: Initialized `_conn` and `_cursor` in `SQL.__init__` to protect against `AttributeError` in `__exit__` if connection fails; guarded `clean_expired_cache` against uninitialized debrid caches.
- **Consolidated Cache Hub**: Expanded **Cache** settings tab with 4 granular clearing actions: **Clear All Cache**, **Clear Scrapers Cache Only**, **Clear Debrid Cache Only**, and **Clear Metadata Cache Only**.
- **Global Context Menu**: Added "Clear Cache" context menu item for instant cache wiping across all Otaku items and directories, with mirrored window properties for both main and testing addons.
- **Automated Expired Cache Pruning**: Scheduled `database.clean_expired_cache(max_age_days=14)` during service startup maintenance to purge dead cache rows and expired debrid entries, preventing database bloat.
- **Customizable TTL Sliders**: Added sliders for Scrapers Cache TTL (1–72h), Torrents Cache TTL (1–168h), Metadata Cache TTL (1–72h), and Airing Calendar Cache TTL (1–48h).
- **Dynamic SQLite PRAGMA Tuning**: Dynamically applied SQLite PRAGMAs (`wal`, `synchronous=NORMAL`, `cache_size=-64000`, `temp_store=MEMORY`) with a 30s TTL cache in `ui/database.py`.
- **Database Maintenance & Telemetry**: Added live database statistics, multi-database VACUUM & optimization, integrity checks, and remote mapping synchronization under Cache settings.
- **Source Select UI Badges**: Added color-coded resolution, audio, debrid, and format badges in the Source Select dialog.

### 🛠️ Bug Fixes & Stability
- **Route Path Parsing Hardening**: Replaced naive `rsplit("/")` across `animes/*`, `play/*`, `play_movie/*`, `find_recommendations/*`, `find_relations/*`, `watch_order/*`, and `delete_anime_database/*` with safe strip-and-slice tokenization.
- **CLI Argument Exception Guard**: Caught `ValueError` alongside `IndexError` on non-numeric `sys.argv[1]` in `control.py`.
- **SourceSelect onInit TypeError**: Fixed `TypeError` in `windows/source_select.py` by supporting default argument in `control.getBool` and `control.getInt`.
- **Search History Typo**: Corrected typo in `ui/utils.py` to `'Remove Search Item'`.
- **AniDB Client ID Guard**: Guarded `api_info['client_id']` in `endpoints/anidb.py` against `NoneType`.
- **Airing Calendar Feedback**: Added visual notification when calendar data is unavailable instead of silent failure.
- **Active Background Playback Context Menu**: Removed `!Player.HasMedia` constraint from Source Select, Rescrape, and Marked as Watched context menu items, enabling context menus during background playback.
- **MIME Type Normalization**: Handled `application/octet-stream` responses returned by CDN nodes in `resolver.py` to avoid demuxer failures and InputStream Adaptive conflicts on Android devices.
- **Settings Help Descriptions**: Added descriptive user-facing help text across all advanced settings tabs in `strings.po` and `settings.xml`.

---

## [5.3.4] - 2026-10-18

### Fixed
- Otaku browser: fixed Airing Last, This, and Next season tabs (season query casing for the metadata API).
- AnimePahe: fail soft when search API returns no data; fixed invalid-JSON exception handling.
- MegaPlay: decrypt encrypted embed sources using AES-CBC when the API no longer returns plain file URLs.
- Settings maintenance: renamed `Instructions.txt` to `instructions.txt` for the instructions viewer.

---

## [5.3.3] - 2026-09-13

### Fixed
- Fixed MegaPlay extractor parsing and stream extraction.
