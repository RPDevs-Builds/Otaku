import time
import re
import xbmcgui
import xbmcplugin
import xbmc
import urllib.parse

from resources.lib.WatchlistIntegration import watchlist_update_episode
from resources.lib.debrid import all_debrid, debrid_link, easynews, premiumize, real_debrid, torbox, easydebrid
from resources.lib.ui import client, control, database, ffprobe_chapters, source_utils, player
from resources.lib.windows.base_window import BaseWindow

control.sys.path.append(control.dataPath)


class hook_mimetype:
    __MIME_HOOKS = {}

    @classmethod
    def trigger(cls, mimetype, item):
        if mimetype in cls.__MIME_HOOKS.keys():
            return cls.__MIME_HOOKS[mimetype](item)
        return item

    def __init__(self, mimetype):
        self._type = mimetype

    def __call__(self, func):
        assert self._type not in self.__MIME_HOOKS.keys()
        self.__MIME_HOOKS[self._type] = func
        return func


class Resolver(BaseWindow):
    def __init__(self, xml_file, location, actionArgs=None, source_select=False):
        super().__init__(xml_file, location, actionArgs=actionArgs)
        self.return_data = {
            'link': None,
            'linkinfo': None,
            'source': None
        }
        self.canceled = False
        self.sources = None
        self.args = None
        self.image = {}
        self.resolvers = {
            'Alldebrid': all_debrid.AllDebrid,
            'Debrid-Link': debrid_link.DebridLink,
            'Premiumize': premiumize.Premiumize,
            'Real-Debrid': real_debrid.RealDebrid,
            'TorBox': torbox.TorBox,
            'EasyDebrid': easydebrid.EasyDebrid,
            'Easynews': easynews.Easynews,
        }
        self.source_select = source_select
        self.pack_select = False
        self.mal_id = actionArgs['mal_id']
        ep_data = database.get_episode(self.mal_id)
        self.season = ep_data.get('season', 1) if ep_data else 1
        self.episode = int(actionArgs.get('episode', 1))
        self.play = actionArgs.get('play')
        self.source_select_close = actionArgs.get('close')
        self.resume = actionArgs.get('resume')
        self.context = actionArgs.get('context')
        self.silent = actionArgs.get('silent')
        self.params = actionArgs.get('params', {})
        self.abort = False
        self._handle_resolved = False
        self._fallback_attempted = False

    def onInit(self):
        self.sources = self.reorder_sources(self.sources)
        self.resolve(self.sources)

    def reorder_sources(self, sources):
        if len(sources) <= 1 or self.source_select:
            return sources

        last_meta = database.get_last_played_source(self.mal_id)
        lp_setting = control.getSetting('last_played_source')
        lp_str = lp_setting if isinstance(lp_setting, str) else ''

        if not last_meta and not lp_str:
            return sources

        target_ep = str(self.episode)
        target_ep_int = self.episode

        reuse_pack_enabled = control.getBool('smartplay.reuse_season_pack', default=True)
        match_quality_enabled = control.getBool('smartplay.match_quality', default=True)
        prefer_embed_enabled = control.getBool('smartplay.prefer_same_embed', default=True)

        import re
        lp_clean = re.sub(r'\[[0-9A-Fa-f]{8,}\]', '', lp_str).strip()
        L = len(target_ep)
        digit_positions = [
            i for i in range(len(lp_clean) - L + 1)
            if lp_clean[i:i + L].isdigit()
        ]

        def _score(source):
            score = 0
            s_type = source.get('type', '')
            s_provider = source.get('provider', '')
            s_debrid = source.get('debrid_provider', '')
            s_quality = source.get('quality', 0)
            s_title = str(source.get('release_title', ''))
            s_info = source.get('info', [])
            s_hash = source.get('hash', '')
            s_lang = source.get('lang', '')

            # 1. Season Pack Continuity (Highest Priority)
            if reuse_pack_enabled:
                if last_meta and last_meta.get('is_season_pack') and last_meta.get('hash') and s_hash == last_meta.get('hash'):
                    score += 100000
                elif source_utils.is_season_pack(source):
                    if source_utils.season_pack_covers_episode(source, target_ep_int):
                        score += 50000

            # 2. Embed Continuity
            if s_type in ['embed', 'direct']:
                last_is_embed = (last_meta and last_meta.get('type') in ['embed', 'direct']) or (
                    lp_str and not any(ext in lp_str.lower() for ext in ('.mkv', '.mp4', '1080p', '720p', '4k'))
                )
                if last_is_embed and prefer_embed_enabled:
                    last_provider = last_meta.get('provider') if last_meta else lp_str.split(' ')[0]
                    if s_provider and last_provider and s_provider.lower() == last_provider.lower():
                        score += 25000
                    last_info = last_meta.get('info', []) if last_meta else lp_str.split(' ')[1:]
                    if any(tag in s_info for tag in ('SUB', 'DUB', 'SOFT-SUB')) and any(tag in last_info for tag in ('SUB', 'DUB', 'SOFT-SUB')):
                        if any(tag in s_info and tag in last_info for tag in ('SUB', 'DUB', 'SOFT-SUB')):
                            score += 5000
                    if last_meta and last_meta.get('lang') and s_lang == last_meta.get('lang'):
                        score += 2000

            # 3. Torrent / Single Episode Continuity
            elif s_type in ['torrent', 'torrent (uncached)', 'cloud', 'hoster', 'local']:
                last_is_torrent = (last_meta and last_meta.get('type') not in ['embed', 'direct']) or not (last_meta or s_type in ['embed', 'direct'])
                if last_is_torrent:
                    # Release Group Matching
                    s_group = source_utils.extract_release_group(s_title)
                    last_group = last_meta.get('release_group', '') if last_meta else source_utils.extract_release_group(lp_clean)
                    if s_group and last_group and s_group == last_group:
                        score += 20000

                    # Sequential Title Matching (Episode pattern replacement)
                    clean_rel = re.sub(r'\[[0-9A-Fa-f]{8,}\]', '', s_title).strip()
                    if clean_rel == lp_clean:
                        score += 35000
                    else:
                        for pos in digit_positions:
                            if clean_rel.startswith(lp_clean[:pos]) and clean_rel.endswith(lp_clean[pos + L:]):
                                score += 30000
                                break

                    # Quality Matching
                    if match_quality_enabled:
                        last_qual = last_meta.get('quality') if last_meta else None
                        if last_qual is not None:
                            if s_quality == last_qual:
                                score += 10000  # Exact quality match
                            elif s_quality > last_qual:
                                score += 2000   # Prefer higher over lower quality

                    # Debrid Provider Matching
                    if last_meta and last_meta.get('debrid_provider') and s_debrid == last_meta.get('debrid_provider'):
                        score += 5000

                    # Audio Flavor Matching (Dual-Audio / Dub)
                    last_info = last_meta.get('info', []) if last_meta else []
                    if any(tag in s_info and tag in last_info for tag in ('DUAL-AUDIO', 'DUB', 'MULTI-AUDIO')):
                        score += 3000

                    # Cached over Uncached
                    if 'uncached' not in s_type:
                        score += 500

            return score

        return sorted(sources, key=_score, reverse=True)

    def resolve(self, sources):
        """Optimized resolve with sequential stream failover, smart retry, and automatic rescrape fallback"""
        for idx, i in enumerate(sources):
            self.return_data['source'] = i
            if self.canceled:
                break

            # Batch property updates
            self._update_source_properties(i)
            stream_link = None

            if 'uncached' in i['type']:
                stream_link = self.resolve_uncache(i)

            elif i['type'] in ['torrent', 'cloud', 'hoster']:
                if i['type'] == 'cloud' and i['debrid_provider'] == 'Alldebrid':
                    stream_link = i['hash']
                else:
                    stream_link = self.resolve_source(self.resolvers[i['debrid_provider']], i)

            elif i['type'] == 'direct':
                stream_link = i['hash']

            elif i['type'] == 'embed':
                from resources.lib.ui import embed_extractor
                stream_link = embed_extractor.load_video_from_url(i['hash'])

            elif i['type'] == 'local':
                stream_link = i['hash']
                self.return_data['linkinfo'] = {
                    'source': i,
                    'url': stream_link,
                    'local': True,
                    'headers': {}
                }
                self.return_data['link'] = stream_link

            if stream_link:
                self.return_data['link'] = stream_link
                if not self.return_data.get('linkinfo'):
                    try:
                        verified_linkinfo = self.prefetch_play_link(stream_link)
                    except Exception as e:
                        control.log(f"Resolver: prefetch error for {i.get('provider')}: {e}", level='warning')
                        verified_linkinfo = None

                    if verified_linkinfo:
                        self.return_data['linkinfo'] = verified_linkinfo
                        if i.get('subs'):
                            self.return_data['sub'] = i['subs']

                if self.return_data.get('linkinfo'):
                    if self.play:
                        ffprobe_chapters.attach_to_linkinfo(self.return_data['linkinfo'])
                        if self._handle_playback():
                            return
                        else:
                            if source_utils.is_season_pack(i):
                                database.clear_season_pack(self.mal_id, self.season)
                            if control.getBool('general.autotrynext', default=True) and not self.canceled and (idx + 1 < len(sources)):
                                control.notify(control.ADDON_NAME, "Playback failed on source, trying next candidate...", time=3000, sound=False)
                                self.return_data = {'linkinfo': None, 'sub': None, 'source': None}
                                continue
                            else:
                                break
                    else:
                        ffprobe_chapters.attach_to_linkinfo(self.return_data['linkinfo'])
                        break
                else:
                    control.log(f"Resolver: candidate {i.get('provider')} failed prefetch/verification, advancing to next candidate", level='warning')
                    if source_utils.is_season_pack(i):
                        database.clear_season_pack(self.mal_id, self.season)
                    self.return_data['link'] = None
            else:
                if source_utils.is_season_pack(i):
                    database.clear_season_pack(self.mal_id, self.season)

        # Smart failover: if all initial candidates failed and not canceled, rescan fresh sources
        if not self.return_data.get('linkinfo') and not self.canceled and not getattr(self, '_fallback_attempted', False):
            self._fallback_attempted = True
            control.notify(control.ADDON_NAME, "Primary source unavailable, scanning fresh sources...", time=3000, sound=False)
            control.log(f"Resolver: All initial candidates failed for {self.mal_id} ep {self.episode}, rescanning fresh sources...", level='info')
            from resources.lib import MetaBrowser
            fresh_sources = MetaBrowser.get_sources(self.mal_id, self.episode, 'show', rescrape=True, source_select=False, silent=self.silent)
            if fresh_sources:
                failed_hashes = {s.get('hash') for s in sources if s.get('hash')}
                usable_fresh = [s for s in fresh_sources if s.get('hash') not in failed_hashes]
                if not usable_fresh:
                    usable_fresh = fresh_sources
                usable_fresh = self.reorder_sources(usable_fresh)
                return self.resolve(usable_fresh)

        if not self.return_data.get('linkinfo'):
            self.return_data = False
            if not self._handle_resolved and not self.context:
                try:
                    xbmcplugin.setResolvedUrl(control.HANDLE, False, xbmcgui.ListItem())
                except Exception:
                    pass

        self.close()

    def _update_source_properties(self, source):
        """Batch update source properties to reduce overhead"""
        debrid_provider = source.get('debrid_provider', 'None').replace('_', ' ')
        self.setProperty('debrid_provider', debrid_provider)
        self.setProperty('source_provider', source['provider'])
        self.setProperty('release_title', str(source['release_title']))
        self.setProperty('source_resolution', source_utils.res[source['quality']])
        self.setProperty('source_info', " ".join(source['info']))
        self.setProperty('source_type', source['type'])

    def _handle_playback(self):
        """Separate playback handling to reduce resolve() complexity"""
        if self.source_select_close:
            self.source_select_close()

        linkInfo = self.return_data['linkinfo']

        item = xbmcgui.ListItem(path=linkInfo['url'], offscreen=True)

        # Handle subtitles
        if self.return_data.get('sub'):
            from resources.lib.ui import embed_extractor
            embed_extractor.del_subs()
            subtitle_entries = []
            for idx, sub in enumerate(self.return_data['sub']):
                entry = embed_extractor.get_sub(
                    sub.get('url'),
                    sub.get('lang'),
                    headers=sub.get('headers'),
                    sub_index=sub.get('index', idx),
                    display_name=sub.get('name'),
                    source_url=sub.get('file'),
                )
                if entry:
                    subtitle_entries.append(entry)
            if subtitle_entries:
                item.setSubtitles([entry['path'] for entry in subtitle_entries])

        # Handle mimetype - hooks will configure InputStream Adaptive for HLS/DASH
        hdr = linkInfo.get('headers') or {}
        content_type = hdr.get('Content-Type')
        if content_type and content_type != 'application/octet-stream':
            item.setProperty('MimeType', content_type)
            item = hook_mimetype.trigger(content_type, item)

        if self.params.get('image'):
            self.image = self.params.get('image', {})

        # Set video tags from the best available source
        if self.params.get('info'):
            control.set_videotags(item, self.params['info'])
        else:
            control.set_videotags(item, self.params)

        art = self._build_art_dict(use_params=False)
        if isinstance(art, str):
            item.setArt(art)

        # Get the clean URL from item (hooks may have stripped headers)
        stream_url = item.getPath()

        # Detect widget/TMDB player context — Container.PluginName won't match
        # our addon when playback is launched from a widget or external player.
        is_widget = xbmc.getInfoLabel('Container.PluginName') != control.ADDON_ID

        # Check whether we're resolving an auto-next episode inside an existing
        # playlist (build_playlist added items after the first episode started).
        in_playlist = control.playList.size() > 1

        if self._handle_resolved or self.context or (is_widget and not in_playlist):
            control.playList.clear()
            control.playList.add(stream_url, item)
            xbmc.Player().play(control.playList, item)
        else:
            try:
                xbmcplugin.setResolvedUrl(control.HANDLE, True, item)
                self._handle_resolved = True
            except Exception as e:
                control.log(f"Resolver: setResolvedUrl error ({e}), falling back to Player().play", level='warning')
                control.playList.clear()
                control.playList.add(stream_url, item)
                xbmc.Player().play(control.playList, item)

        # Monitor playback start
        monitor = Monitor()
        playback_ok = False
        for _ in range(30):
            if monitor.waitForAbort(1) or monitor.abortRequested():
                self.abort = True
                break
            if monitor.playbackerror:
                control.log(f"Resolver: playback error on {self.return_data.get('source', {}).get('provider')}", level='warning')
                control.playList.clear()
                break
            if monitor.playing:
                playback_ok = True
                break
        else:
            control.log('no xbmc playing source found; Continuing code', level='warning')
        del monitor

        if playback_ok:
            self.close()
            current_src = self.return_data.get('source', {})
            if current_src:
                database.save_last_played_source(self.mal_id, current_src)
                if control.getBool('smartplay.reuse_season_pack', default=True) and source_utils.is_season_pack(current_src):
                    pack_src = dict(current_src)
                    pack_src.pop('filename', None)
                    database.set_season_pack(self.mal_id, self.season, pack_src)
                    control.log(f"Resolver: Cached season pack for {self.mal_id} season {self.season}: {current_src.get('release_title')}", level='info')
            link_info = self.return_data.get('linkinfo') or {}
            ch = link_info.get('chapters') if isinstance(link_info, dict) else None
            player.WatchlistPlayer().handle_player(
                self.mal_id,
                watchlist_update_episode,
                self.episode,
                self.resume,
                self.params.get('path', ''),
                self.return_data['source']['type'] if 'type' in self.return_data['source'] else '',
                self.return_data['source']['provider'] if 'provider' in self.return_data['source'] else '',
                self.context,
                ch,
            )
            return True

        if self.abort:
            self.close()
            if not self._handle_resolved and not self.context:
                try:
                    xbmcplugin.setResolvedUrl(control.HANDLE, False, item)
                except Exception:
                    pass
            control.playList.clear()
            return False

        return False

    def _build_art_dict(self, use_params=False):
        """Build art dictionary efficiently"""
        if use_params:
            return {
                'icon': self.params.get('icon') or self.image.get('icon') or '',
                'thumb': self.params.get('thumb') or self.image.get('thumb') or '',
                'fanart': self.params.get('fanart') or self.image.get('fanart') or '',
                'landscape': self.params.get('landscape') or self.image.get('landscape') or '',
                'banner': self.params.get('banner') or self.image.get('banner') or '',
                'clearart': self.params.get('clearart') or self.image.get('clearart') or '',
                'clearlogo': self.params.get('clearlogo') or self.image.get('clearlogo') or '',
                'tvshow.poster': self.params.get('tvshow.poster') or self.params.get('poster') or '',
            }
        else:
            fanart = self.image.get('fanart')
            if isinstance(fanart, list) and fanart:
                fanart = fanart[0]
            return {
                'icon': self.image.get('icon') or '',
                'thumb': self.image.get('thumb') or '',
                'fanart': fanart or '',
                'landscape': self.image.get('landscape') or '',
                'banner': self.image.get('banner') or '',
                'clearart': self.image.get('clearart') or '',
                'clearlogo': self.image.get('clearlogo') or '',
                'tvshow.poster': self.image.get('poster') or self.params.get('poster') or '',
            }

    def resolve_source(self, api, source):
        """Improved resolve_source with better error handling for Premiumize"""
        try:
            api = api()
            hash_ = source['hash']
            magnet = f"magnet:?xt=urn:btih:{hash_}"
            stream_link = {}

            if source['type'] == 'torrent':
                filename = source.get('filename')
                if filename:
                    ep_reg = source_utils.get_cache_check_reg(self.episode)
                    clean_fname = re.sub(r'\[.*?]', '', filename.split('/')[-1])
                    if not ep_reg.search(clean_fname):
                        filename = None
                ep_re = source.get('episode_re') or str(self.episode)
                stream_link = api.resolve_single_magnet(hash_, magnet, ep_re, self.pack_select, filename)
            elif source['type'] == 'cloud':
                hash_ = api.resolve_cloud(source, self.pack_select)
                if hash_:
                    stream_link = api.resolve_hoster(hash_)
            elif source['type'] == 'hoster':
                if source.get('debrid_provider') == 'Easynews':
                    stream_link = api.unrestrict_link(source['hash'])
                else:
                    hoster_response = api.resolve_hoster(magnet, source['episode_re'], self.pack_select)
                    if hoster_response:
                        stream_link = hoster_response

            return stream_link
        except Exception as e:
            control.log(f"Error resolving source with {source.get('debrid_provider', 'Unknown')}: {str(e)}", 'error')
            return None

    @staticmethod
    def prefetch_play_link(link):
        if not link:
            return None
        url = link
        headers = {}
        if '|' in url:
            url, hdrs = url.split('|', 1)
            for item in hdrs.split('&'):
                if '=' in item:
                    k, v = item.split('=', 1)
                    headers[k] = urllib.parse.unquote_plus(v)

        # If flaresolverr is enabled, fetch cookies to bypass Cloudflare
        if control.getBool('fs_enable'):
            from resources.lib.ui.client import cfcookie
            try:
                cookie_obj = cfcookie()
                cookie, ua = cookie_obj.get(url, control.getInt('fs_timeout'))
                if cookie:
                    headers["Cookie"] = cookie
                    headers["User-Agent"] = ua
            except Exception:
                pass

        # Try HEAD request first
        response = None
        try:
            response = client.head(url, headers=headers, timeout=15)
        except Exception as e:
            control.log(f"Resolver: HEAD request failed for {url}: {e}", level='warning')

        # Fallback to GET with Range: bytes=0-0 if HEAD fails or returns non-200/201/206
        if not response or str(response.status_code) not in ['200', '201', '206']:
            try:
                get_headers = headers.copy()
                get_headers['Range'] = 'bytes=0-0'
                response = client.get(url, headers=get_headers, timeout=15)
            except Exception as e:
                control.log(f"Resolver: GET fallback failed for {url}: {e}", level='warning')

        if not response or str(response.status_code) not in ['200', '201', '206']:
            control.log(f"Resolver: could not verify {url}, status={response.status_code if response else 'failed'}", level='warning')
            return None

        resp_headers = dict(response.headers)
        if 'Content-Type' not in resp_headers.keys():
            if 'Content-Length' not in resp_headers.keys():
                resp_headers.update({'Content-Type': 'video/MP2T'})
            elif '.m3u8' in url:
                resp_headers.update({'Content-Type': 'application/vnd.apple.mpegurl'})
        elif resp_headers['Content-Type'] == 'application/octet-stream':
            clean_url = url.split('?')[0].lower()
            if clean_url.endswith('.mkv'):
                resp_headers['Content-Type'] = 'video/x-matroska'
            elif clean_url.endswith('.mp4'):
                resp_headers['Content-Type'] = 'video/mp4'
            elif '.m3u8' in clean_url:
                resp_headers['Content-Type'] = 'video/MP2T'
            else:
                resp_headers.pop('Content-Type', None)
        return {
            "url": link if '|' in link else response.url,
            "headers": resp_headers,
        }

    def resolve_uncache(self, source):
        heading = f'{control.ADDON_NAME}: Cache Resolver'
        status = None
        api = self.resolvers[source['debrid_provider']]()
        f_string = (f"[I]{source['release_title']}[/I][CR]"
                    f"[CR]"
                    f"This source is not cached. Would you like to cache it now?")

        if source['debrid_provider'] in ['Alldebrid', 'Real-Debrid', 'Debrid-Link']:
            # Get an instance of the debrid API and check torrent status early.
            torrent_status = api.get_torrent_status(source['magnet'])
            # torrent_status returns (torrent_id, status, torrent_info)
            if torrent_status is None or torrent_status[0] is None:
                # Torrent selection failed.
                return

            torrent_id, status, torrent_info = torrent_status
            if source['debrid_provider'] == 'Alldebrid':
                api.delete_magnet(torrent_id)
            elif source['debrid_provider'] == 'Real-Debrid':
                api.deleteTorrent(torrent_id)

        # If the file is already cached, bypass any prompting.
        if status in ['downloaded', 'Ready']:
            runbackground = False
            runinforground = False
        else:
            # Not yet cached: prompt the user.
            yesnocustom = control.yesnocustom_dialog(
                heading, f_string, "Cancel", "Run in Background", "Run in Foreground",
                defaultbutton=xbmcgui.DLG_YESNO_YES_BTN
            )
            if yesnocustom == -1 or yesnocustom == 2:
                self.canceled = True
                return
            runbackground = (yesnocustom == 0)
            runinforground = (yesnocustom == 1)

        try:
            resolved_cache = api.resolve_uncached_source(source, runbackground, runinforground, self.pack_select)
        except Exception as e:
            control.progressDialog.close()
            import traceback
            control.ok_dialog(control.ADDON_NAME, f'Error: {e}')
            control.log(traceback.format_exc(), level='error')
            return

        if not resolved_cache:
            self.canceled = True

        return resolved_cache

    def doModal(self, sources, args, pack_select):
        if sources:
            # Reorder sources first.
            self.sources = self.reorder_sources(sources)
            self.args = args
            # Now assign pack_select after the sources are reordered.
            self.pack_select = pack_select
            self.setProperty('release_title', str(self.sources[0]['release_title']))
            self.setProperty('debrid_provider', self.sources[0].get('debrid_provider', 'None').replace('_', ' '))
            self.setProperty('source_provider', self.sources[0]['provider'])
            self.setProperty('source_resolution', source_utils.res[self.sources[0]['quality']])
            self.setProperty('source_info', " ".join(self.sources[0]['info']))
            self.setProperty('source_type', self.sources[0]['type'])
            self.setProperty('source_size', self.sources[0]['size'])
            self.setProperty('source_seeders', str(self.sources[0].get('seeders', '')))

            database.save_last_played_source(self.mal_id, self.sources[0])
            if control.getBool('smartplay.reuse_season_pack', default=True) and source_utils.is_season_pack(self.sources[0]):
                database.set_season_pack(self.mal_id, self.season, self.sources[0])

            if self.sources[0]['type'] in ['embed', 'direct']:
                control.setSetting('last_played_source', str(self.sources[0]['provider']) + " " + " ".join(map(str, self.sources[0]['info'])))
            else:
                control.setSetting('last_played_source', str(self.sources[0]['release_title']))

            if self.silent:
                if self.source_select_close:
                    self.source_select_close()
                self.resolve(self.sources)
            else:
                super(Resolver, self).doModal()

        return self.return_data

    def onAction(self, action):
        actionID = action.getId()

        if actionID in [92, 10]:
            # BACKSPACE / ESCAPE
            self.canceled = True
            self.close()


class Monitor(xbmc.Monitor):
    def __init__(self):
        super().__init__()
        self.playbackerror = False
        self.playing = False
        self._created = time.time()

    def onNotification(self, sender, method, data):
        if method == 'Player.OnAVStart':
            self.playing = True
            self.playbackerror = False
        elif method == 'Player.OnStop':
            # Ignore OnStop events that arrive within 2 seconds of monitor
            # creation — these are leftover notifications from the previous
            # episode ending (playlist transitions / user stops).
            if time.time() - self._created < 2:
                return
            if not self.playing:
                self.playbackerror = True
        # else:
        #     control.log(f'{method} | {data}')


@hook_mimetype('application/dash+xml')
def _DASH_HOOK(item):
    if control.getBool('inputstreamadaptive.enabled'):
        stream_url = item.getPath()
        import inputstreamhelper
        is_helper = inputstreamhelper.Helper('mpd')
        if is_helper.check_inputstream():
            item.setProperty('inputstream', is_helper.inputstream_addon)
            if control.kodi_version < 20.9:
                item.setProperty('inputstream.adaptive.manifest_type', 'mpd')
                item.setContentLookup(False)
            if '|' in stream_url:
                stream_url, headers = stream_url.split('|')
                item.setPath(stream_url)  # Set clean URL without headers
                item.setProperty('inputstream.adaptive.stream_headers', headers)
                if control.kodi_version > 21.8:
                    item.setProperty('inputstream.adaptive.common_headers', headers)
                else:
                    item.setProperty('inputstream.adaptive.stream_params', headers)
                    item.setProperty('inputstream.adaptive.manifest_headers', headers)
        else:
            raise Exception("InputStream Adaptive is not supported.")
    return item


@hook_mimetype('application/vnd.apple.mpegurl')
@hook_mimetype('video/MP2T')
@hook_mimetype('image/jpeg')
def _HLS_HOOK(item):
    if control.getBool('inputstreamadaptive.enabled'):
        stream_url = item.getPath()
        import inputstreamhelper
        is_helper = inputstreamhelper.Helper('hls')
        if is_helper.check_inputstream():
            item.setProperty('inputstream', is_helper.inputstream_addon)
            if control.kodi_version < 20.9:
                item.setProperty('inputstream.adaptive.manifest_type', 'hls')
                item.setProperty('MimeType', 'application/vnd.apple.mpegurl')
                item.setMimeType('application/vnd.apple.mpegstream_url')
                item.setContentLookup(False)
            if '|' in stream_url:
                stream_url, headers = stream_url.split('|')
                item.setPath(stream_url)  # Set clean URL without headers
                item.setProperty('inputstream.adaptive.stream_headers', headers)
                # For HLS AES-128 encrypted streams, license_key is used for key file requests
                item.setProperty('inputstream.adaptive.license_key', '|' + headers + '||R{SSM}')
                if control.kodi_version > 21.8:
                    item.setProperty('inputstream.adaptive.common_headers', headers)
                else:
                    item.setProperty('inputstream.adaptive.stream_params', headers)
                    item.setProperty('inputstream.adaptive.manifest_headers', headers)

    return item
