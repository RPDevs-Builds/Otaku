"""
database.py - Otaku Database & Caching Layer
=============================================
Clean, organized caching and metadata storage.

Architecture
------------
SQL          - Lock-free SQLite context manager (WAL mode concurrent access)
Memory Cache - Window-property RAM cache with expiry
General Cache- 3-tier caching: RAM → SQLite → fresh API call
Shows        - Anime show / meta / episode CRUD
Mappings     - Cross-service ID lookups
Watchlist    - Per-service watchlist cache with activity invalidation
Enrichment   - AniList supplementary metadata cache
History      - Per-category search history
Maintenance  - Cache clearing helpers
"""

import ast
import hashlib
import os
import pickle
import re
import time

import xbmcgui
import xbmcvfs

from sqlite3 import OperationalError, dbapi2
from resources.lib.ui import control


# ═══════════════════════════════════════════════════════════════════════════
#  SQL - SQLite Context Manager (WAL-mode concurrent access)
# ═══════════════════════════════════════════════════════════════════════════

_cached_pragmas = None
_cached_pragmas_time = 0
_PRAGMA_CACHE_TTL = 30  # re-read settings at most once every 30 seconds


def _get_sqlite_pragmas():
    global _cached_pragmas, _cached_pragmas_time
    now = time.time()
    if _cached_pragmas is not None and (now - _cached_pragmas_time) < _PRAGMA_CACHE_TTL:
        return _cached_pragmas

    cache_size_mb = 16
    mmap_size_mb = 32
    sync_val = 'NORMAL'
    temp_store_ram = True

    try:
        c_mb = control.getInt('db.sqlite.cache_size_mb')
        if c_mb > 0:
            cache_size_mb = c_mb
    except Exception:
        pass

    try:
        m_mb = control.getInt('db.sqlite.mmap_size_mb')
        if m_mb >= 0:
            mmap_size_mb = m_mb
    except Exception:
        pass

    try:
        sync_mode = control.getSetting('db.sqlite.synchronous') or '1'
        sync_map = {'0': 'OFF', '1': 'NORMAL', '2': 'FULL'}
        sync_val = sync_map.get(str(sync_mode), 'NORMAL')
    except Exception:
        pass

    try:
        temp_store_ram = control.getBool('db.sqlite.temp_store_ram')
    except Exception:
        pass

    stmts = [
        "PRAGMA foreign_keys = ON",
        f"PRAGMA synchronous = {sync_val}",
        "PRAGMA journal_mode = WAL",
        f"PRAGMA cache_size = -{cache_size_mb * 1024}",
        f"PRAGMA mmap_size = {mmap_size_mb * 1024 * 1024}"
    ]
    if temp_store_ram:
        stmts.append("PRAGMA temp_store = MEMORY")

    _cached_pragmas = tuple(stmts)
    _cached_pragmas_time = now
    return _cached_pragmas


def clear_pragma_cache():
    """Clear cached PRAGMA configuration tuple to force immediate reload from settings."""
    global _cached_pragmas, _cached_pragmas_time
    _cached_pragmas = None
    _cached_pragmas_time = 0


def _dict_factory(cursor, row):
    """Row factory that returns dicts keyed by column name."""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


class SQL:
    """SQLite context manager with optimized PRAGMAs.

    WAL journal mode allows concurrent readers without locking.
    isolation_level=None enables autocommit for faster writes.

    Usage::

        with SQL(db_path) as cursor:
            cursor.execute('SELECT ...')
            cursor.connection.commit()   # needed for writes
    """

    def __init__(self, path, timeout=30):
        self.path = path
        self.timeout = timeout

    def __enter__(self):
        dir_name = os.path.dirname(self.path) or control.dataPath
        if dir_name and not os.path.exists(dir_name):
            try:
                os.makedirs(dir_name, exist_ok=True)
            except Exception:
                pass
        try:
            self._conn = dbapi2.connect(self.path, timeout=self.timeout, isolation_level=None)
            self._conn.row_factory = _dict_factory

            for pragma in _get_sqlite_pragmas():
                self._conn.execute(pragma)

            self._cursor = self._conn.cursor()
            return self._cursor
        except Exception:
            raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if self._cursor is not None:
                self._cursor.close()
            if self._conn is not None:
                self._conn.close()
        except Exception:
            pass

        if exc_type:
            if exc_type is OperationalError:
                import traceback
                control.log('database OperationalError', level='error')
                control.log(''.join(traceback.format_exception(
                    exc_type, exc_val, exc_tb)), level='error')
                return True
            import traceback
            control.log('database error', level='error')
            control.log(''.join(traceback.format_exception(
                exc_type, exc_val, exc_tb)), level='error')
        return False


# ═══════════════════════════════════════════════════════════════════════════
#  Memory Cache - Kodi Window Properties with Expiry
# ═══════════════════════════════════════════════════════════════════════════

_window = xbmcgui.Window(10000)
_MEM_PREFIX = f"{control.ADDON_ID}_mem_"


def _mem_get(key):
    """Return parsed data or *None* if missing / expired."""
    raw = _window.getProperty(_MEM_PREFIX + key)
    if not raw:
        return None
    try:
        sep = raw.index('|')
        if int(raw[:sep]) > int(time.time()):
            return ast.literal_eval(raw[sep + 1:])
    except Exception:
        pass
    _window.clearProperty(_MEM_PREFIX + key)
    return None


def _mem_set(key, value_repr, hours):
    """Store *value_repr* (a ``repr()`` string) with an expiry of *hours*."""
    expires = int(time.time() + hours * 3600)
    _window.setProperty(_MEM_PREFIX + key, f"{expires}|{value_repr}")


def _mem_del(key):
    """Remove a single key from the RAM cache."""
    _window.clearProperty(_MEM_PREFIX + key)


# ═══════════════════════════════════════════════════════════════════════════
#  Lazy Table Initialization (once per session)
# ═══════════════════════════════════════════════════════════════════════════

_tables_ready = set()


def _ensure_table(db_path, name, ddl):
    """Run *ddl* only the first time (*db_path*, *name*) is seen."""
    tag = f"{db_path}:{name}"
    if tag in _tables_ready:
        return
    with SQL(db_path) as cur:
        cur.execute(ddl)
        cur.connection.commit()
    _tables_ready.add(tag)


def _init_cache_table():
    _ensure_table(
        control.cacheFile, 'cache',
        'CREATE TABLE IF NOT EXISTS cache '
        '(key TEXT UNIQUE, value TEXT, date INTEGER)'
    )
    # Index once at init; avoid running DDL on every cache write (hot path).
    _ensure_table(
        control.cacheFile, 'cache_ix_key',
        'CREATE UNIQUE INDEX IF NOT EXISTS ix_cache ON cache (key)'
    )
    _ensure_table(
        control.cacheFile, 'cache_ix_date',
        'CREATE INDEX IF NOT EXISTS ix_cache_date ON cache (date)'
    )


# ═══════════════════════════════════════════════════════════════════════════
#  General Cache - 3-Tier: RAM → SQLite → Fresh API Call
# ═══════════════════════════════════════════════════════════════════════════

def _is_empty_result(val):
    """Detect empty results that should not poison the cache.
    Includes None, empty sequences, empty dicts, or torrent dicts with empty buckets."""
    if not val:
        return True
    if isinstance(val, dict):
        if not any(val.values()):
            return True
        if all(isinstance(v, (list, tuple, set, dict)) and not v for v in val.values()):
            return True
    return False


def get(function, duration, *args, **kwargs):
    """Cached function call with 3-tier lookup.

    :param function:  Callable to execute on cache miss.
    :param duration:  Cache validity in **hours**.
    :param args/kwargs:  Forwarded to *function* on miss.
        Special kwarg ``key`` is popped and appended to the cache key.
    """
    if 'Browser' in getattr(function, '__module__', ''):
        duration = control.getInt('cache.metadata.ttl') or duration

    force_refresh = kwargs.pop('force_refresh', False)

    key = _hash_function(function, args, kwargs)
    if 'key' in kwargs:
        key += kwargs.pop('key')

    if not force_refresh:
        # --- Tier 1: RAM (instant) ---
        mem = _mem_get(key)
        if mem is not None and not _is_empty_result(mem):
            return mem

        # --- Tier 2: SQLite ---
        _init_cache_table()
        with SQL(control.cacheFile) as cur:
            cur.execute('SELECT value, date FROM cache WHERE key=?', (key,))
            row = cur.fetchone()

        if row and is_cache_valid(row['date'], duration):
            try:
                data = ast.literal_eval(row['value'])
                if data is not None and not _is_empty_result(data):
                    _mem_set(key, row['value'], duration)
                    return data
            except Exception:
                control.log(
                    f"Cache corrupt for key {key}, fetching fresh data",
                    level='warning')
    else:
        _cache_delete(key)
        _mem_del(key)

    # --- Tier 3: Fresh call ---
    result = function(*args, **kwargs)
    if result is None or _is_empty_result(result):
        return result
    result_repr = repr(result)
    _cache_write(key, result_repr)
    _mem_set(key, result_repr, duration)
    return result


def remove(function, *args, **kwargs):
    """Remove the cached value for a function call."""
    try:
        key = _hash_function(function, args, kwargs)
        _cache_delete(key)
        _mem_del(key)
        return True
    except Exception:
        return False


# — helpers ------------------------------------------------------------------

def _hash_function(func, args, kwargs):
    name = re.sub(
        r'.+\smethod\s|.+function\s|\sat\s.+|\sof\s.+', '', repr(func))
    return name + generate_md5((args, kwargs))


def generate_md5(*args):
    """MD5 hex-digest of the string representation of *args*."""
    md5 = hashlib.md5()
    for arg in args:
        md5.update(str(arg).encode())
    return md5.hexdigest()


def is_cache_valid(cached_time, hours):
    """True when *cached_time* (epoch) is younger than *hours*."""
    return (int(time.time()) - cached_time) < (hours * 3600)


def _cache_write(key, value_repr):
    _init_cache_table()
    with SQL(control.cacheFile) as cur:
        cur.execute(
            'REPLACE INTO cache (key, value, date) VALUES (?, ?, ?)',
            (key, value_repr, int(time.time())))
        cur.connection.commit()


def _cache_delete(key):
    with SQL(control.cacheFile) as cur:
        cur.execute('DELETE FROM cache WHERE key=?', (key,))
        cur.connection.commit()


# — backward-compat aliases (kept for any external callers) -----------------

def hash_function(function_instance, *args):
    function_name = re.sub(
        r'.+\smethod\s|.+function\s|\sat\s.+|\sof\s.+', '',
        repr(function_instance))
    return function_name + generate_md5(args)


def cache_get(key):
    _init_cache_table()
    with SQL(control.cacheFile) as cur:
        cur.execute('SELECT * FROM cache WHERE key=?', (key,))
        return cur.fetchone()


def cache_insert(key, value):
    _cache_write(key, value)


def cache_remove(key):
    _cache_delete(key)


def cache_clear():
    """Wipe general cache, debrid hash cache, watchlist cache, activity, and enrichment data."""
    with SQL(control.cacheFile) as cur:
        cur.execute("DROP TABLE IF EXISTS cache")
        cur.execute("DROP TABLE IF EXISTS debrid_cache")
        cur.execute("VACUUM")
        cur.connection.commit()
    _tables_ready.discard(f"{control.cacheFile}:cache")
    _tables_ready.discard(f"{control.cacheFile}:cache_ix_key")
    _tables_ready.discard(f"{control.cacheFile}:debrid_cache")
    _tables_ready.discard(f"{control.cacheFile}:debrid_cache_ix_expires")

    clear_watchlist_cache()
    clear_watchlist_activity()
    clear_anilist_enrichment()
    clear_season_pack()

    control.notify(
        f'{control.ADDON_NAME}: {control.lang(30086)}',
        control.lang(30087), time=5000, sound=False)


def cache_clear_scrapers():
    """Wipe scraper and API response cache without touching metadata, debrid, or watchlists."""
    with SQL(control.cacheFile) as cur:
        cur.execute("DELETE FROM cache WHERE key NOT LIKE '%Browser.%'")
        cur.execute("VACUUM")
        cur.connection.commit()
    clear_season_pack()
    control.notify(
        f'{control.ADDON_NAME}: Scraper Cache',
        'Scraper cache successfully cleared', time=5000, sound=False)


def cache_clear_metadata():
    """Wipe browser metadata cache and AniList enrichment without touching scrapers, debrid, or watchlists."""
    with SQL(control.cacheFile) as cur:
        cur.execute("DELETE FROM cache WHERE key LIKE '%Browser.%'")
        cur.execute("VACUUM")
        cur.connection.commit()
    clear_anilist_enrichment()
    control.notify(
        f'{control.ADDON_NAME}: Metadata Cache',
        'Metadata cache successfully cleared', time=5000, sound=False)


def cache_clear_show(mal_id):
    """Purge all cached scraper and metadata entries relating to a specific show."""
    with SQL(control.cacheFile) as cur:
        cur.execute("DELETE FROM cache WHERE key LIKE ?", (f'%{mal_id}%',))
        cur.connection.commit()
    clear_season_pack(mal_id)
    control.notify(
        f'{control.ADDON_NAME}: Show Cache',
        f'Cache for anime ID {mal_id} cleared', time=4000, sound=False)


# ═══════════════════════════════════════════════════════════════════════════
#  Season Pack & Playback Continuity Caching
# ═══════════════════════════════════════════════════════════════════════════

def set_season_pack(mal_id, season, source):
    """Cache the selected season pack source for subsequent episode playback."""
    if not source or not mal_id:
        return
    key = f"season_pack_{mal_id}_{season or 1}"
    source_copy = dict(source)
    source_repr = repr(source_copy)
    duration = 720  # 30 days
    _cache_write(key, source_repr)
    _mem_set(key, source_repr, duration)


def get_season_pack(mal_id, season=1):
    """Retrieve the cached season pack source for this show and season."""
    if not mal_id:
        return None
    key = f"season_pack_{mal_id}_{season or 1}"
    mem = _mem_get(key)
    if mem is not None:
        return mem
    _init_cache_table()
    with SQL(control.cacheFile) as cur:
        cur.execute('SELECT value, date FROM cache WHERE key=?', (key,))
        row = cur.fetchone()
    if row and is_cache_valid(row['date'], 720):
        try:
            data = ast.literal_eval(row['value'])
            if data:
                _mem_set(key, row['value'], 720)
                return data
        except Exception:
            pass
    return None


def clear_season_pack(mal_id=None, season=None):
    """Purge cached season packs from SQLite and memory cache."""
    _init_cache_table()
    with SQL(control.cacheFile) as cur:
        if mal_id and season:
            key = f"season_pack_{mal_id}_{season}"
            cur.execute('DELETE FROM cache WHERE key=?', (key,))
            _mem_del(key)
        elif mal_id:
            cur.execute("DELETE FROM cache WHERE key LIKE ?", (f"season_pack_{mal_id}_%",))
            for s in range(1, 10):
                _mem_del(f"season_pack_{mal_id}_{s}")
        else:
            cur.execute("DELETE FROM cache WHERE key LIKE 'season_pack_%'")
        cur.connection.commit()


def save_last_played_source(mal_id, source):
    """Save structured metadata of the last played source for smart scoring."""
    if not source or not mal_id:
        return
    from resources.lib.ui import source_utils
    key = f"last_played_{mal_id}"
    meta = {
        'mal_id': str(mal_id),
        'type': source.get('type', ''),
        'provider': source.get('provider', ''),
        'debrid_provider': source.get('debrid_provider', ''),
        'quality': source.get('quality', 0),
        'release_title': source.get('release_title', ''),
        'hash': source.get('hash', ''),
        'info': source.get('info', []),
        'lang': source.get('lang', ''),
        'release_group': source_utils.extract_release_group(source.get('release_title', '')),
        'is_season_pack': source_utils.is_season_pack(source),
        'timestamp': int(time.time()),
    }
    meta_repr = repr(meta)
    duration = 720
    _cache_write(key, meta_repr)
    _mem_set(key, meta_repr, duration)
    # Maintain backward compatibility with legacy setting string
    if meta['type'] in ['embed', 'direct']:
        control.setSetting('last_played_source', str(source.get('provider', '')) + " " + " ".join(map(str, source.get('info', []))))
    else:
        control.setSetting('last_played_source', str(source.get('release_title', '')))


def get_last_played_source(mal_id):
    """Retrieve structured metadata of the last played source for smart scoring."""
    if not mal_id:
        return None
    key = f"last_played_{mal_id}"
    mem = _mem_get(key)
    if mem is not None:
        return mem
    _init_cache_table()
    with SQL(control.cacheFile) as cur:
        cur.execute('SELECT value, date FROM cache WHERE key=?', (key,))
        row = cur.fetchone()
    if row and is_cache_valid(row['date'], 720):
        try:
            data = ast.literal_eval(row['value'])
            if data:
                _mem_set(key, row['value'], 720)
                return data
        except Exception:
            pass
    return None



def _format_db_bytes(size=0):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0 or unit == 'GB':
            return f"{size:.1f} {unit}" if unit != 'B' else f"{int(size)} B"
        size /= 1024.0
    return f"{size:.1f} GB"


def get_database_stats():
    """Gather diagnostic telemetry across all Otaku SQLite databases."""
    stats = []
    total_size = 0

    dbs = [
        ('Cache Database', control.cacheFile, 'cache.db'),
        ('Shows & Episodes DB', control.malSyncDB, 'malSync.db'),
        ('Anime ID Mappings DB', control.mappingDB, 'mappings.db'),
        ('Search History DB', control.searchHistoryDB, 'search.db')
    ]

    for label, path, filename in dbs:
        size_bytes = 0
        exists = os.path.exists(path)
        if exists:
            try:
                size_bytes = os.path.getsize(path)
                total_size += size_bytes
            except OSError:
                pass

        details = []
        if exists:
            try:
                with SQL(path) as cur:
                    if filename == 'cache.db':
                        try:
                            cur.execute("SELECT count(*) as count FROM cache WHERE key NOT LIKE '%Browser.%'")
                            row = cur.fetchone()
                            if row:
                                details.append(f"{row['count']} scraper/API items")
                        except Exception:
                            pass
                        try:
                            cur.execute("SELECT count(*) as count FROM cache WHERE key LIKE '%Browser.%'")
                            row = cur.fetchone()
                            if row:
                                details.append(f"{row['count']} metadata items")
                        except Exception:
                            pass
                        try:
                            cur.execute("SELECT count(*) as count FROM debrid_cache")
                            row = cur.fetchone()
                            if row:
                                details.append(f"{row['count']} debrid hashes")
                        except Exception:
                            pass
                    elif filename == 'malSync.db':
                        try:
                            cur.execute("SELECT count(*) as count FROM shows")
                            row = cur.fetchone()
                            if row:
                                details.append(f"{row['count']} shows")
                        except Exception:
                            pass
                        try:
                            cur.execute("SELECT count(*) as count FROM episodes")
                            row = cur.fetchone()
                            if row:
                                details.append(f"{row['count']} episodes")
                        except Exception:
                            pass
                    elif filename == 'mappings.db':
                        try:
                            cur.execute("SELECT count(*) as count FROM anime")
                            row = cur.fetchone()
                            if row:
                                details.append(f"{row['count']} mappings")
                        except Exception:
                            pass
                    elif filename == 'search.db':
                        try:
                            cur.execute("SELECT count(*) as count FROM history")
                            row = cur.fetchone()
                            if row:
                                details.append(f"{row['count']} queries")
                        except Exception:
                            pass
            except Exception as e:
                details.append(f"read error: {e}")

        detail_str = f" ({', '.join(details)})" if details else ""
        stats.append(f"• {label:<22} : {_format_db_bytes(size_bytes):>9}{detail_str}")

    # PRAGMA telemetry
    pragma_info = []
    try:
        with SQL(control.cacheFile) as cur:
            cur.execute("PRAGMA journal_mode")
            r = cur.fetchone()
            if r:
                pragma_info.append(f"Journal: {r.get('journal_mode', '').upper()}")
            cur.execute("PRAGMA synchronous")
            r = cur.fetchone()
            if r:
                sync_map = {'0': 'OFF', '1': 'NORMAL', '2': 'FULL'}
                pragma_info.append(f"Sync: {sync_map.get(str(r.get('synchronous', '')), str(r.get('synchronous', '')))}")
            cur.execute("PRAGMA cache_size")
            r = cur.fetchone()
            if r:
                c_val = r.get('cache_size', 0)
                pragma_info.append(f"Cache: {abs(int(c_val)) // 1024 if c_val < 0 else abs(int(c_val)) * 4 // 1024} MB")
            cur.execute("PRAGMA mmap_size")
            r = cur.fetchone()
            if r:
                pragma_info.append(f"MMAP: {int(r.get('mmap_size', 0)) // (1024 * 1024)} MB")
    except Exception:
        pass

    pragma_str = " | ".join(pragma_info) if pragma_info else "Default"

    # Integrity summary
    healthy, _ = check_database_integrity()
    integrity_status = "All databases healthy (OK)" if healthy else "Warning: integrity issues detected"

    output = [
        "Otaku Database & Storage Telemetry",
        "═" * 58,
        "\n".join(stats),
        "─" * 58,
        f"• Total Storage Used   : {_format_db_bytes(total_size):>9}",
        f"• Active SQLite Mode   : {pragma_str}",
        f"• Database Integrity   : {integrity_status}",
        "═" * 58
    ]
    return "\n".join(output)


def check_database_integrity():
    """Run PRAGMA integrity_check on all 4 Otaku SQLite databases."""
    dbs = [
        ('cache.db', control.cacheFile),
        ('malSync.db', control.malSyncDB),
        ('mappings.db', control.mappingDB),
        ('search.db', control.searchHistoryDB)
    ]
    all_ok = True
    results = {}
    for name, path in dbs:
        if os.path.exists(path):
            try:
                with SQL(path) as cur:
                    cur.execute("PRAGMA integrity_check")
                    rows = cur.fetchall()
                    if rows and rows[0].get('integrity_check') == 'ok':
                        results[name] = 'OK'
                    else:
                        all_ok = False
                        results[name] = f"Issue: {rows}"
            except Exception as e:
                all_ok = False
                results[name] = f"Error: {e}"
        else:
            results[name] = 'Not created yet'
    return all_ok, results


def vacuum_all_databases():
    """Run PRAGMA optimize and VACUUM across all Otaku SQLite databases."""
    dbs = [control.cacheFile, control.malSyncDB, control.mappingDB, control.searchHistoryDB]
    bytes_before = 0
    bytes_after = 0

    for path in dbs:
        if os.path.exists(path):
            try:
                bytes_before += os.path.getsize(path)
                with SQL(path) as cur:
                    cur.execute("PRAGMA optimize")
                    cur.execute("VACUUM")
                bytes_after += os.path.getsize(path)
            except Exception as e:
                control.log(f"Failed to vacuum {path}: {e}", level='warning')

    reclaimed = max(0, bytes_before - bytes_after)
    return reclaimed


# ═══════════════════════════════════════════════════════════════════════════
#  Show Operations
# ═══════════════════════════════════════════════════════════════════════════

def get_show(mal_id):
    with SQL(control.malSyncDB) as cur:
        cur.execute('SELECT * FROM shows WHERE mal_id=?', (mal_id,))
        return cur.fetchone()


def update_show(mal_id, kodi_meta, anime_schedule_route=''):
    with SQL(control.malSyncDB) as cur:
        cur.execute(
            'INSERT INTO shows (mal_id, kodi_meta, anime_schedule_route) VALUES (?, ?, ?) '
            'ON CONFLICT(mal_id) DO UPDATE SET kodi_meta=excluded.kodi_meta, anime_schedule_route=excluded.anime_schedule_route',
            (mal_id, kodi_meta, anime_schedule_route))
        cur.connection.commit()


def get_show_meta(mal_id):
    with SQL(control.malSyncDB) as cur:
        cur.execute('SELECT * FROM shows_meta WHERE mal_id=?', (mal_id,))
        return cur.fetchone()


def update_show_meta(mal_id, meta_ids, art):
    with SQL(control.malSyncDB) as cur:
        cur.execute('PRAGMA foreign_keys=OFF')
        cur.execute(
            'REPLACE INTO shows_meta (mal_id, meta_ids, art) VALUES (?, ?, ?)',
            (mal_id, pickle.dumps(meta_ids), pickle.dumps(art)))
        cur.execute('PRAGMA foreign_keys=ON')
        cur.connection.commit()


def update_kodi_meta(mal_id, kodi_meta):
    with SQL(control.malSyncDB) as cur:
        cur.execute(
            'UPDATE shows SET kodi_meta=? WHERE mal_id=?',
            (pickle.dumps(kodi_meta), mal_id))
        cur.connection.commit()


def add_mapping_id(mal_id, column, value):
    with SQL(control.malSyncDB) as cur:
        cur.execute(
            f'UPDATE shows SET {column}=? WHERE mal_id=?', (value, mal_id))
        cur.connection.commit()


def get_show_data(mal_id):
    with SQL(control.malSyncDB) as cur:
        cur.execute('SELECT * FROM show_data WHERE mal_id=?', (mal_id,))
        return cur.fetchone()


def update_show_data(mal_id, data, last_updated=''):
    with SQL(control.malSyncDB) as cur:
        cur.execute('PRAGMA foreign_keys=OFF')
        cur.execute(
            'REPLACE INTO show_data '
            '(mal_id, data, last_updated) VALUES (?, ?, ?)',
            (mal_id, pickle.dumps(data), last_updated))
        cur.execute('PRAGMA foreign_keys=ON')
        cur.connection.commit()


# ═══════════════════════════════════════════════════════════════════════════
#  Episode Operations
# ═══════════════════════════════════════════════════════════════════════════

def get_episode(mal_id, episode=None):
    with SQL(control.malSyncDB) as cur:
        if episode:
            cur.execute(
                'SELECT * FROM episodes WHERE mal_id=? AND number=?',
                (mal_id, episode))
        else:
            cur.execute(
                'SELECT * FROM episodes WHERE mal_id=?', (mal_id,))
        return cur.fetchone()


def get_episode_list(mal_id):
    with SQL(control.malSyncDB) as cur:
        cur.execute('SELECT * FROM episodes WHERE mal_id=?', (mal_id,))
        return cur.fetchall()


def update_episode(mal_id, season, number, update_time, kodi_meta,
                   filler='', anidb_ep_id=''):
    with SQL(control.malSyncDB) as cur:
        cur.execute(
            'REPLACE INTO episodes '
            '(mal_id, season, kodi_meta, last_updated, number, filler, anidb_ep_id) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (mal_id, season, kodi_meta, update_time, number, filler, anidb_ep_id))
        cur.connection.commit()


def update_episode_column(mal_id, episode, column, value):
    with SQL(control.malSyncDB) as cur:
        cur.execute(
            f'UPDATE episodes SET {column}=? WHERE mal_id=? AND number=?',
            (value, mal_id, episode))
        cur.connection.commit()


def update_episode_batch(episode_batch):
    """Batch insert/replace episodes in a single transaction using executemany."""
    if not episode_batch:
        return
    with SQL(control.malSyncDB) as cur:
        cur.executemany(
            'REPLACE INTO episodes '
            '(mal_id, season, kodi_meta, last_updated, number, filler, anidb_ep_id) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            episode_batch)
        cur.connection.commit()


# ═══════════════════════════════════════════════════════════════════════════
#  Mapping & Info Lookups
# ═══════════════════════════════════════════════════════════════════════════

def get_mappings(anime_id, send_id):
    with SQL(control.mappingDB) as cur:
        cur.execute(
            f'SELECT * FROM anime WHERE {send_id}=?', (anime_id,))
        rows = cur.fetchall()
        return rows[0] if rows else {}


def get_unique_ids(anime_id, send_id):
    with SQL(control.mappingDB) as cur:
        cur.execute(
            f'SELECT mal_id, mal_dub_id, anilist_id, kitsu_id, anidb_id, '
            f'simkl_id, thetvdb_id, themoviedb_id, imdb_id, trakt_id '
            f'FROM anime WHERE {send_id}=?', (anime_id,))
        row = cur.fetchone()
        if not row:
            return {}
        return {
            'mal_id':     row.get('mal_id'),
            'mal_dub_id': row.get('mal_dub_id'),
            'anilist_id': row.get('anilist_id'),
            'kitsu_id':   row.get('kitsu_id'),
            'anidb':      row.get('anidb_id'),
            'simkl':      row.get('simkl_id'),
            'tvdb':       row.get('thetvdb_id'),
            'tmdb':       row.get('themoviedb_id'),
            'imdb':       row.get('imdb_id'),
            'trakt':      row.get('trakt_id'),
        }


def get_mal_ids(anime_id, send_id):
    with SQL(control.mappingDB) as cur:
        cur.execute(
            f'SELECT * FROM anime WHERE {send_id}=?', (anime_id,))
        return cur.fetchall() or []


def get_info(api_name):
    with SQL(control.infoDB) as cur:
        cur.execute('SELECT * FROM info WHERE api_name=?', (api_name,))
        return cur.fetchone()


def remove_from_database(table, mal_id):
    with SQL(control.malSyncDB) as cur:
        cur.execute(f'DELETE FROM {table} WHERE mal_id=?', (mal_id,))
        cur.connection.commit()


# ═══════════════════════════════════════════════════════════════════════════
#  Watchlist Cache
# ═══════════════════════════════════════════════════════════════════════════

def get_watchlist_cache(service, status, limit=None, offset=0):
    """Cached watchlist items, optionally paginated."""
    with SQL(control.malSyncDB) as cur:
        if limit:
            cur.execute(
                'SELECT * FROM watchlist_cache '
                'WHERE service=? AND status=? ORDER BY id LIMIT ? OFFSET ?',
                (service, status, limit, offset))
        else:
            cur.execute(
                'SELECT * FROM watchlist_cache '
                'WHERE service=? AND status=? ORDER BY id',
                (service, status))
        return cur.fetchall()


def get_watchlist_cache_count(service, status):
    """Count of cached items for a service / status pair."""
    with SQL(control.malSyncDB) as cur:
        cur.execute(
            'SELECT COUNT(*) as count FROM watchlist_cache '
            'WHERE service=? AND status=?', (service, status))
        row = cur.fetchone()
        return row['count'] if row else 0


def get_watchlist_cache_last_updated(service, status):
    """Oldest update timestamp for a service / status pair."""
    with SQL(control.malSyncDB) as cur:
        cur.execute(
            'SELECT MIN(last_updated) as last_updated FROM watchlist_cache '
            'WHERE service=? AND status=?', (service, status))
        row = cur.fetchone()
        return row['last_updated'] if row else None


def save_watchlist_cache(service, status, items):
    """Replace all cache entries for a service / status pair."""
    now = int(time.time())
    with SQL(control.malSyncDB) as cur:
        cur.execute(
            'DELETE FROM watchlist_cache WHERE service=? AND status=?',
            (service, status))
        for idx, item in enumerate(items):
            cur.execute(
                'INSERT INTO watchlist_cache '
                '(service, status, mal_id, item_order, data, last_updated) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                (service, status, _extract_mal_id(service, item),
                 idx, pickle.dumps(item), now))
        cur.connection.commit()


def _extract_mal_id(service, item):
    """Pull MAL ID from a watchlist item based on service structure."""
    extractors = {
        'simkl':   lambda i: i.get('show', {}).get('ids', {}).get('mal'),
        'kitsu':   lambda i: i.get('mal_id'),
        'mal':     lambda i: i.get('node', {}).get('id'),
        'anilist': lambda i: i.get('media', {}).get('idMal'),
    }
    fn = extractors.get(service)
    return fn(item) if fn else None


def clear_watchlist_cache(service=None, status=None):
    """Clear cache, optionally filtered by service and/or status."""
    with SQL(control.malSyncDB) as cur:
        if service and status:
            cur.execute(
                'DELETE FROM watchlist_cache WHERE service=? AND status=?',
                (service, status))
        elif service:
            cur.execute(
                'DELETE FROM watchlist_cache WHERE service=?', (service,))
        else:
            cur.execute('DELETE FROM watchlist_cache')
        cur.connection.commit()


def is_watchlist_cache_valid(service, status, cache_hours=24):
    """Safety-net fallback (primary invalidation is activity-based)."""
    last = get_watchlist_cache_last_updated(service, status)
    return is_cache_valid(last, cache_hours) if last else False


# ═══════════════════════════════════════════════════════════════════════════
#  Watchlist Activity  (activity-based cache invalidation)
# ═══════════════════════════════════════════════════════════════════════════

def get_watchlist_activity(service):
    """Stored activity record for a watchlist service."""
    with SQL(control.malSyncDB) as cur:
        cur.execute(
            'SELECT * FROM watchlist_activity WHERE service=?', (service,))
        return cur.fetchone()


def save_watchlist_activity(service, activity_timestamp):
    """Save the last known activity timestamp for a service."""
    with SQL(control.malSyncDB) as cur:
        cur.execute(
            'REPLACE INTO watchlist_activity '
            '(service, activity_timestamp, last_checked) VALUES (?, ?, ?)',
            (service, str(activity_timestamp), int(time.time())))
        cur.connection.commit()


def clear_watchlist_activity(service=None):
    """Clear stored activity timestamps."""
    try:
        with SQL(control.malSyncDB) as cur:
            if service:
                cur.execute(
                    'DELETE FROM watchlist_activity WHERE service=?',
                    (service,))
            else:
                cur.execute('DELETE FROM watchlist_activity')
            cur.connection.commit()
    except Exception:
        pass  # table may not exist on first run


# ═══════════════════════════════════════════════════════════════════════════
#  AniList Enrichment Cache
# ═══════════════════════════════════════════════════════════════════════════

def get_all_watchlist_mal_ids():
    """All unique MAL IDs across every cached watchlist entry."""
    with SQL(control.malSyncDB) as cur:
        cur.execute(
            'SELECT DISTINCT mal_id FROM watchlist_cache '
            'WHERE mal_id IS NOT NULL')
        rows = cur.fetchall()
    result = []
    for row in rows:
        try:
            result.append(int(row['mal_id']))
        except (ValueError, TypeError):
            pass
    return result


def save_anilist_enrichment_batch(data_list):
    """Save AniList media objects keyed by ``idMal``."""
    if not data_list:
        return
    now = int(time.time())
    with SQL(control.malSyncDB) as cur:
        for item in data_list:
            mal_id = item.get('idMal')
            if not mal_id:
                continue
            cur.execute(
                'REPLACE INTO anilist_enrichment '
                '(mal_id, data, last_updated) VALUES (?, ?, ?)',
                (int(mal_id), pickle.dumps(item), now))
        cur.connection.commit()


def get_anilist_enrichment_batch(mal_ids, max_age_hours=168):
    """Cached AniList enrichment for given MAL IDs (default 7 days max)."""
    if not mal_ids:
        return {}
    cutoff = int(time.time()) - (max_age_hours * 3600)
    result = {}
    with SQL(control.malSyncDB) as cur:
        ph = ','.join('?' for _ in mal_ids)
        cur.execute(
            f'SELECT * FROM anilist_enrichment '
            f'WHERE mal_id IN ({ph}) AND last_updated > ?',
            [int(m) for m in mal_ids] + [cutoff])
        for row in cur.fetchall():
            try:
                result[row['mal_id']] = pickle.loads(row['data'])
            except Exception:
                pass
    return result


def clear_anilist_enrichment():
    """Clear all AniList enrichment data."""
    with SQL(control.malSyncDB) as cur:
        cur.execute('DELETE FROM anilist_enrichment')
        cur.connection.commit()


# ═══════════════════════════════════════════════════════════════════════════
#  Search History
# ═══════════════════════════════════════════════════════════════════════════

_SEARCH_TYPES = (
    'anime', 'movie', 'tv_show', 'tv_short',
    'special', 'ova', 'ona', 'music',
)


def _ensure_search_tables(cur):
    for t in _SEARCH_TYPES:
        cur.execute(f'CREATE TABLE IF NOT EXISTS {t} (value TEXT UNIQUE)')


def getSearchHistory(media_type):
    with SQL(control.searchHistoryDB) as cur:
        _ensure_search_tables(cur)
        cur.execute(f'SELECT * FROM {media_type}')
        history = cur.fetchall()
    history.reverse()
    seen = set()
    return [h['value'] for h in history[:50]
            if h['value'] not in seen and not seen.add(h['value'])]


def addSearchHistory(search_string, media_type):
    with SQL(control.searchHistoryDB) as cur:
        _ensure_search_tables(cur)
        cur.execute(
            f'REPLACE INTO {media_type} VALUES (?)', (search_string,))
        cur.connection.commit()


def clearSearchHistory():
    if not control.yesno_dialog(
            control.ADDON_NAME, "Clear all search history?"):
        return
    with SQL(control.searchHistoryDB) as cur:
        for t in _SEARCH_TYPES:
            cur.execute(f'DROP TABLE IF EXISTS {t}')
        cur.execute("VACUUM")
        cur.connection.commit()
    control.refresh()
    control.notify(
        control.ADDON_NAME, "Search History has been cleared", time=5000)


def clearSearchCatagory(media_type):
    if not control.yesno_dialog(
            control.ADDON_NAME, "Clear search history?"):
        return
    with SQL(control.searchHistoryDB) as cur:
        cur.execute(f'DROP TABLE IF EXISTS {media_type}')
        cur.execute(
            f'CREATE TABLE IF NOT EXISTS {media_type} (value TEXT UNIQUE)')
        cur.connection.commit()
    control.refresh()
    control.notify(
        control.ADDON_NAME, "Search History has been cleared", time=5000)


def remove_search(table, value):
    norm = value.strip()
    with SQL(control.searchHistoryDB) as cur:
        cur.execute(f'DELETE FROM {table} WHERE value=?', (norm,))
        deleted = cur.rowcount
        cur.connection.commit()
    control.refresh()
    if deleted == 0:
        control.notify(
            control.ADDON_NAME,
            f"Search item not found: '{norm}'", time=3000)
