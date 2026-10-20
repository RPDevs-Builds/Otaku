# Changelog

All notable changes to the **Otaku** Kodi Addon (RPDevs fork) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased] - 2026-10-19

### Added
- **Clear Cache Context Menu Item (`context.otaku`, `control.py`, `settings.xml`, `anichart.py`)**:
  - Added global "Clear Cache" context menu item for instant cache wiping across all Otaku items and directories.
  - Added `context.otaku.clearcache` toggle under **Settings → Context Customization** (enabled by default) and mirrored window properties for both main and testing addons.
  - Added "Clear Cache" action support in AniChart dialog context menu.
- **Centralized Cache Settings Hub & Granular Actions (`settings.xml`, `database.py`, `Main.py`, `AnimeSchedule.py`)**:
  - Expanded **Cache** settings tab with 4 granular clearing actions: **Clear All Cache**, **Clear Scrapers Cache Only**, **Clear Debrid Cache Only**, and **Clear Metadata Cache Only**.
  - Relocated **Enable Kodi RAM Cache** toggle (`general.kodi.cache`) into the Cache category.
  - Added 4 customizable TTL duration sliders: **Scrapers Cache TTL** (1–72h), **Torrents Cache TTL** (1–168h), **Metadata Cache TTL** (1–72h), and **Airing Calendar Cache TTL** (1–48h).
  - Wired metadata TTL resolution into `database.get()` and calendar TTL into `AnimeScheduleCalendar`.

### Fixed
- **Context Menu Options for Testing Addon (`control.py`, `default.py`)**:
  - Updated `process_context()` to populate both `context.otaku.*` and `context.otaku.testing.*` window properties so Source Select, Rescrape, and watchlist options appear in the context menu for both live and testing add-on instances.
  - Added `process_context()` invocation at `default.py` entrypoint to ensure context menu window properties remain warm across navigation.
- **Debrid Cache Maintenance & Storage Pruning (`debrid_cache.py`, `database.py`)**:
  - Integrated `debrid_cache` table dropping into `database.cache_clear()` so **Settings → General → Clear Cache** purges debrid hash records along with general cache and watchlist data.
  - Added indexed automatic TTL pruning (`DELETE FROM debrid_cache WHERE expires < now`) executed periodically on write workers to prevent unbounded SQLite file growth.
- **Premiumize Torrent Cache Checking (`hash_check`)**:
  - Replaced query-string `GET` requests with chunked `POST` requests (`chunk_size=100`) transmitting form data `[('items[]', hash) ...]`.
  - Fixes HTTP 414 (*Request-URI Too Long*) errors when scraping high-volume sources and checking 100+ torrent infohashes simultaneously.
- **Premiumize Account Storage Management (`manage_storage_space`)**:
  - Added safety checks for `storage_info` response and `'space_used'` key existence.
  - Prevents unhandled `KeyError` and `TypeError` crashes during storage quota checks if the API returns rate limits, errors, or maintenance responses.
- **Premiumize Torrent File Extension Validation (`resolve_single_magnet` & `resolve_uncached_source`)**:
  - Updated `is_file_ext_valid()` check to inspect `i.get('path')` first, falling back to `i.get('link', '')`.
  - Fixes false negatives during video filtering caused by CDN query parameters and token strings in download URLs (`.split('.')[-1]`).
- **Premiumize Torrent Episode Matching & Branch Logic**:
  - Fixed dead fallback branch where `elif len(filter_list) >= 1:` previously shadowed the multi-file fallback block; corrected to `elif len(filter_list) > 1:`.
  - Added sample file filtering fallback (`'sample' not in path.lower()`) to select the main feature when regex episode matching returns no match.
  - Handled interactive dialog cancellation: aborts playback cleanly (`return None`) when the user cancels the file selection modal (`user_select`) instead of forcing playback of the first file.
- **Kodi Video Stream Resolver (`resolver.py`)**:
  - **MIME Type Normalization**: Handled `application/octet-stream` responses returned by CDN nodes (CloudFront / Akamai / Cloudflare). Automatically maps `.mkv` to `video/x-matroska`, `.mp4` to `video/mp4`, `.m3u8` to `video/MP2T`, or removes `Content-Type` for other video containers so Kodi's internal FFmpeg demuxer can inspect stream magic bytes directly.
  - **ListItem Property Guard**: Guarded `item.setProperty('MimeType', content_type)` in `_handle_playback()` to ignore `application/octet-stream`, avoiding playback failure and InputStream Adaptive conflicts on Android devices.

### Infrastructure & Hardware Tuning
- **Android TV / Low-Memory Hardware Cache Buffer**:
  - Diagnosed `std::bad_alloc` crash in `CFileCache::Open` occurring on 32-bit ARM Android systems (e.g. onn. Streaming Device 4K Pro) when Kodi `filecache.memorysize` was configured to 1024 MB (1 GB contiguous buffer request on ~52 MB available heap).
  - Validated stable playback by configuring `filecache.memorysize` to 64 MB.

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
