import pickle
import xbmcgui

from resources.lib.ui import control, database
from resources.lib.windows.base_window import BaseWindow
from resources.lib.windows.download_manager import Manager
from resources.lib.windows.resolver import Resolver
from resources.lib import MetaBrowser


class SourceSelect(BaseWindow):
    def __init__(self, xml_file, location, actionArgs=None, sources=None, rescrape=None):
        super().__init__(xml_file, location, actionArgs=actionArgs)
        self.actionArgs = actionArgs
        self.sources = sources
        self.displayed_sources = []  # List to maintain displayed sources
        self.showing_uncached = False  # Track whether uncached sources are being shown
        self.rescrape = rescrape
        self.position = -1
        self.canceled = False
        self.display_list = None
        self.stream_link = None
        self.view_mode = 'both'  # Default view mode
        episode = actionArgs.get('episode')

        # Set properties for the selected episode
        if episode:
            anime_init = MetaBrowser.get_anime_init(actionArgs.get('mal_id'))
            episode = int(episode)
            try:
                self.setProperty('item.info.season', str(anime_init[0][episode - 1]['info']['season']))
                self.setProperty('item.info.episode', str(anime_init[0][episode - 1]['info']['episode']))
                self.setProperty('item.info.title', anime_init[0][episode - 1]['info']['title'])
                self.setProperty('item.info.plot', anime_init[0][episode - 1]['info']['plot'])
                self.setProperty('item.art.thumb', anime_init[0][episode - 1]['image']['thumb'])
                self.setProperty('item.art.poster', anime_init[0][episode - 1]['image']['poster'])
            except IndexError:
                self.setProperty('item.info.season', '-1')
                self.setProperty('item.info.episode', '-1')

            try:
                aired = anime_init[0][episode - 1]['info'].get('aired') or '0000-00-00'
                year, month, day = aired.split('-')
                self.setProperty('item.info.aired', aired)
                self.setProperty('item.info.year', year)
            except (ValueError, AttributeError, IndexError):
                pass
        else:
            show = database.get_show(actionArgs.get('mal_id'))
            if show:
                kodi_meta = pickle.loads(show.get('kodi_meta'))
                self.setProperty('item.info.plot', kodi_meta.get('plot'))
                self.setProperty('item.info.rating', str(kodi_meta.get('rating', {}).get('score')))
                self.setProperty('item.info.aired', kodi_meta.get('start_date') or '')
                self.setProperty('item.art.thumb', kodi_meta.get('poster'))
                try:
                    self.setProperty('item.info.year', kodi_meta.get('start_date').split('-')[0])
                except AttributeError:
                    pass

    def onInit(self):
        self.display_list = self.getControl(1000)
        # build all four lists
        cached = [s for s in self.sources if s.get('cached') is True]
        uncached = [s for s in self.sources if s.get('cached') is False]
        embeds = [s for s in self.sources if s.get('type') in ('embed', 'direct')]
        both = list(self.sources)

        # always start on “both”
        self.view_mode = 'both'
        self._show_current_sources(cached, both, uncached, embeds)
        self.setFocusId(1000)

    def _show_current_sources(self, cached, both, uncached, embeds):
        if self.view_mode == 'both':
            items, label = both, "View Cached"
        elif self.view_mode == 'cached':
            items, label = cached, "View Uncached"
        elif self.view_mode == 'uncached':
            items, label = uncached, "View Embeds"
        else:  # 'embeds'
            items, label = embeds, "View Both"

        self.populate_sources(items)
        # update the button label
        self.getControl(15).setLabel(label)

    def populate_sources(self, sources):
        self.display_list.reset()
        self.displayed_sources = sources  # Update the displayed sources list
        badges_enabled = control.getBool('interface.source_select.badges')
        menu_items = []

        for source in sources:
            if source is None:
                continue

            release_title = source.get('release_title', '')
            quality = str(source.get('quality', ''))
            info = source.get('info', [])
            source_type = source.get('type', '')

            if badges_enabled:
                badges = []
                # Quality badge
                q_upper = quality.upper()
                if '4K' in q_upper or '2160' in q_upper:
                    badges.append('[COLOR gold][4K][/COLOR]')
                elif '1080' in q_upper:
                    badges.append('[COLOR deepskyblue][1080p][/COLOR]')
                elif '720' in q_upper:
                    badges.append('[COLOR springgreen][720p][/COLOR]')
                elif 'SD' in q_upper or '480' in q_upper:
                    badges.append('[COLOR darkgray][SD][/COLOR]')

                # Debrid / Source Type badge
                dp = source.get('debrid_provider')
                if dp:
                    if 'Real-Debrid' in dp or 'RD' in dp:
                        badges.append('[COLOR limegreen][RD][/COLOR]')
                    elif 'AllDebrid' in dp or 'AD' in dp:
                        badges.append('[COLOR orange][AD][/COLOR]')
                    elif 'Premiumize' in dp or 'PM' in dp:
                        badges.append('[COLOR deepskyblue][PM][/COLOR]')
                    elif 'TorBox' in dp or 'TB' in dp:
                        badges.append('[COLOR cyan][TB][/COLOR]')
                    else:
                        badges.append(f'[COLOR springgreen][{dp}][/COLOR]')
                elif source_type in ('embed', 'direct'):
                    badges.append('[COLOR orchid][EMBED][/COLOR]')

                # Audio / Codec badges from info
                info_joined = ' '.join(info).upper()
                if 'DUAL AUDIO' in info_joined or 'DUAL' in info_joined:
                    badges.append('[COLOR coral][DUAL][/COLOR]')
                elif 'DUB' in info_joined:
                    badges.append('[COLOR sandybrown][DUB][/COLOR]')

                if 'HEVC' in info_joined or 'X265' in info_joined or 'H.265' in info_joined:
                    badges.append('[COLOR magenta][HEVC][/COLOR]')
                elif 'AV1' in info_joined:
                    badges.append('[COLOR hotpink][AV1][/COLOR]')

                if '10BIT' in info_joined or '10-BIT' in info_joined:
                    badges.append('[COLOR aqua][10-bit][/COLOR]')

                if badges:
                    display_label = f"{' '.join(badges)} {release_title}"
                else:
                    display_label = release_title
            else:
                display_label = release_title

            menu_item = xbmcgui.ListItem(display_label, offscreen=True)
            properties = {
                'type': source_type,
                'debrid_provider': source.get('debrid_provider', ''),
                'provider': source.get('provider', ''),
                'quality': quality,
                'info': ' '.join(info),
                'seeders': str(source.get('seeders', '')) if source.get('seeders', -1) != -1 else 'na',
                'size': source.get('size', '')
            }
            menu_item.setProperties(properties)
            menu_items.append(menu_item)

        if menu_items:
            self.display_list.addItems(menu_items)

    def doModal(self):
        super(SourceSelect, self).doModal()
        return self.stream_link

    def handle_action(self, action_id):
        # Implement the logic for handling the action here
        # For now, you can just log the action_id
        control.log(f"Action handled: {action_id}")

    def onClick(self, controlId):
        if controlId == 15:  # cycle views
            sequence = ['both', 'cached', 'uncached', 'embeds']
            idx = sequence.index(self.view_mode)
            self.view_mode = sequence[(idx + 1) % len(sequence)]

            # rebuild the four lists and refresh
            cached = [s for s in self.sources if s.get('cached') is True]
            uncached = [s for s in self.sources if s.get('cached') is False]
            embeds = [s for s in self.sources if s.get('type') in ('embed', 'direct')]
            both = list(self.sources)
            self._show_current_sources(cached, both, uncached, embeds)

        elif controlId == 1000:
            pass

    def onAction(self, action):
        actionID = action.getId()

        if actionID in [92, 10]:
            # BACKSPACE / ESCAPE
            control.playList.clear()
            self.stream_link = False
            self.close()

        if actionID in [7, 100] and self.getFocusId() == 1000:
            self.position = self.display_list.getSelectedPosition()
            self.resolve_item()

        if actionID in [117, 101, 11]:  # Context menu (117) or remote long-press Select/Menu (101, 11)
            context = control.context_menu(
                [
                    "Play",
                    "Download",
                    "File Select"
                ]
            )
            self.position = self.display_list.getSelectedPosition()
            if context == 0:  # Play
                self.resolve_item()
            elif context == 1:  # Download
                if self.displayed_sources[self.position]['debrid_provider'] == 'Local-Debrid' or self.displayed_sources[self.position]['debrid_provider'] == '':
                    control.notify(control.ADDON_NAME, "Please Select A Debrid File")
                elif self.displayed_sources[self.position]['debrid_provider'] == 'EasyDebrid':
                    control.notify(control.ADDON_NAME, "EasyDebrid does not support Downloads")
                else:
                    self.close()
                    source = [self.displayed_sources[self.display_list.getSelectedPosition()]]
                    self.actionArgs['play'] = False
                    if control.getInt('general.dialog') in (5, 6):
                        return_data = Resolver('resolver_alt.xml', control.ADDON_PATH, actionArgs=self.actionArgs, source_select=True).doModal(source, {}, False)
                    else:
                        return_data = Resolver('resolver.xml', control.ADDON_PATH, actionArgs=self.actionArgs, source_select=True).doModal(source, {}, False)
                    if isinstance(return_data, dict):
                        Manager().download_file(return_data['link'])

            elif context == 2:  # File Selection
                if not self.displayed_sources[self.position]['debrid_provider']:
                    control.notify(control.ADDON_NAME, "Please Select A Debrid File")
                else:
                    self.resolve_item(True)

    def resolve_item(self, pack_select=False):
        if control.getBool('general.autotrynext') and not pack_select:
            sources = self.displayed_sources[self.position:]
        else:
            sources = [self.displayed_sources[self.position]]
        if self.rescrape:
            selected_source = self.displayed_sources[self.position]
            selected_source['name'] = selected_source['release_title']
        self.actionArgs['close'] = self.close
        if control.getInt('general.dialog') in (5, 6):
            self.stream_link = Resolver('resolver_alt.xml', control.ADDON_PATH, actionArgs=self.actionArgs, source_select=True).doModal(sources, {}, pack_select)
        else:
            self.stream_link = Resolver('resolver.xml', control.ADDON_PATH, actionArgs=self.actionArgs, source_select=True).doModal(sources, {}, pack_select)
        if isinstance(self.stream_link, dict):
            self.close()
