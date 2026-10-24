"""
debrid_cloud.py - Unified Debrid Cloud Browser & Streaming Resolver
===================================================================
Provides unified listing, playback unrestrict, and deletion for active
torrents and cached files across Real-Debrid, TorBox, Premiumize, and AllDebrid.
"""
from resources.lib.ui import control, source_utils


def format_bytes(num_bytes):
    """Format bytes into readable size string (e.g. 1.45 GB)"""
    try:
        num_bytes = float(num_bytes)
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if num_bytes < 1024.0:
                if unit == 'B':
                    return f"{int(num_bytes)} B"
                elif unit in ['KB', 'MB']:
                    return f"{num_bytes:.1f} {unit}"
                else:
                    return f"{num_bytes:.2f} {unit}"
            num_bytes /= 1024.0
        return f"{num_bytes:.2f} PB"
    except (ValueError, TypeError):
        return "0 B"


def get_active_providers():
    """Return dict of enabled debrid providers with valid tokens and their display labels."""
    enabled = control.enabled_debrid()
    labels = {
        'realdebrid': 'Real-Debrid',
        'torbox': 'TorBox',
        'premiumize': 'Premiumize',
        'alldebrid': 'AllDebrid',
        'debridlink': 'Debrid-Link',
    }
    return {k: labels.get(k, k.capitalize()) for k, v in enabled.items() if v}


def get_cloud_items(provider, folder_id=None):
    """
    Fetch items from user's debrid cloud.
    If folder_id is None: returns list of torrents/packs/folders.
    If folder_id is provided: returns list of playable video files inside that pack.
    """
    items = []
    try:
        if provider == 'realdebrid':
            from resources.lib.debrid.real_debrid import RealDebrid
            rd = RealDebrid()
            if not folder_id:
                torrents = rd.list_torrents() or []
                for t in torrents:
                    tid = str(t.get('id', ''))
                    filename = t.get('filename', 'Unknown')
                    bytes_val = t.get('bytes', 0)
                    progress = t.get('progress', 0)
                    status = t.get('status', '')
                    is_ready = status == 'downloaded' or progress == 100
                    status_badge = "[COLOR forestgreen][100%][/COLOR]" if is_ready else f"[COLOR orange][{progress}%][/COLOR]"
                    size_badge = f"[{format_bytes(bytes_val)}]"
                    name = f"{status_badge} {size_badge} {filename}"
                    items.append({
                        'name': name,
                        'title': filename,
                        'id': tid,
                        'provider': 'realdebrid',
                        'is_folder': True,
                        'size': format_bytes(bytes_val),
                        'progress': progress,
                        'status': status
                    })
            else:
                info = rd.torrentInfo(folder_id) or {}
                selected_files = [f for f in info.get('files', []) if f.get('selected') == 1]
                links = info.get('links', [])
                for idx, f in enumerate(selected_files):
                    link = links[idx] if idx < len(links) else None
                    if not link:
                        continue
                    path = f.get('path', '')
                    filename = path.rsplit('/', 1)[-1] if '/' in path else path
                    if not source_utils.is_file_ext_valid(filename):
                        continue
                    size_badge = f"[{format_bytes(f.get('bytes', 0))}]"
                    items.append({
                        'name': f"{size_badge} {filename}",
                        'title': filename,
                        'id': folder_id,
                        'file_ref': link,
                        'provider': 'realdebrid',
                        'is_folder': False,
                        'size': format_bytes(f.get('bytes', 0))
                    })

        elif provider == 'premiumize':
            from resources.lib.debrid.premiumize import Premiumize
            pm = Premiumize()
            folder_res = pm.list_folder(folder_id)
            content = folder_res.get('content', []) if isinstance(folder_res, dict) else (folder_res if isinstance(folder_res, list) else [])
            for item in content:
                itype = item.get('type')
                iid = str(item.get('id', ''))
                name = item.get('name', 'Unknown')
                size_val = item.get('size', 0)
                if itype == 'folder':
                    items.append({
                        'name': f"[COLOR deepskyblue][Folder][/COLOR] {name}",
                        'title': name,
                        'id': iid,
                        'provider': 'premiumize',
                        'is_folder': True,
                        'size': format_bytes(size_val),
                    })
                elif itype == 'file':
                    if not source_utils.is_file_ext_valid(name):
                        continue
                    size_badge = f"[{format_bytes(size_val)}]"
                    items.append({
                        'name': f"{size_badge} {name}",
                        'title': name,
                        'id': iid,
                        'file_ref': item.get('link', ''),
                        'provider': 'premiumize',
                        'is_folder': False,
                        'size': format_bytes(size_val)
                    })

        elif provider == 'torbox':
            from resources.lib.debrid.torbox import Torbox
            tb = Torbox()
            if not folder_id:
                torrents = tb.list_torrents() or []
                for t in torrents:
                    tid = str(t.get('id', ''))
                    name = t.get('name', 'Unknown')
                    size_val = t.get('size', 0)
                    progress = int(t.get('progress', 0) * 100) if isinstance(t.get('progress'), float) else t.get('progress', 0)
                    state = t.get('download_state', '')
                    is_ready = state in ('completed', 'cached') or progress == 100
                    status_badge = "[COLOR forestgreen][100%][/COLOR]" if is_ready else f"[COLOR orange][{progress}%][/COLOR]"
                    size_badge = f"[{format_bytes(size_val)}]"
                    items.append({
                        'name': f"{status_badge} {size_badge} {name}",
                        'title': name,
                        'id': tid,
                        'provider': 'torbox',
                        'is_folder': True,
                        'size': format_bytes(size_val),
                        'progress': progress,
                        'status': state
                    })
            else:
                info = tb.get_torrent_info(folder_id) or {}
                files = info.get('files', [])
                for f in files:
                    fid = str(f.get('id', ''))
                    fname = f.get('name', 'Unknown')
                    if not source_utils.is_file_ext_valid(fname):
                        continue
                    fsize = f.get('size', 0)
                    size_badge = f"[{format_bytes(fsize)}]"
                    items.append({
                        'name': f"{size_badge} {fname}",
                        'title': fname,
                        'id': folder_id,
                        'file_ref': fid,
                        'provider': 'torbox',
                        'is_folder': False,
                        'size': format_bytes(fsize)
                    })

        elif provider == 'alldebrid':
            from resources.lib.debrid.all_debrid import AllDebrid
            ad = AllDebrid()
            torrents = ad.list_torrents() or []
            if not folder_id:
                for t in torrents:
                    tid = str(t.get('id', ''))
                    fname = t.get('filename', 'Unknown')
                    fsize = t.get('size', 0)
                    status_code = t.get('statusCode', 0)
                    is_ready = status_code == 4  # 4 = downloaded in AllDebrid
                    status_badge = "[COLOR forestgreen][100%][/COLOR]" if is_ready else "[COLOR orange][Downloading][/COLOR]"
                    size_badge = f"[{format_bytes(fsize)}]"
                    items.append({
                        'name': f"{status_badge} {size_badge} {fname}",
                        'title': fname,
                        'id': tid,
                        'provider': 'alldebrid',
                        'is_folder': True,
                        'size': format_bytes(fsize),
                    })
            else:
                match = next((t for t in torrents if str(t.get('id')) == str(folder_id)), None)
                if match:
                    for link_entry in match.get('links', []):
                        fname = link_entry.get('filename', '')
                        if not source_utils.is_file_ext_valid(fname):
                            continue
                        fsize = link_entry.get('size', 0)
                        link = link_entry.get('link', '')
                        size_badge = f"[{format_bytes(fsize)}]"
                        items.append({
                            'name': f"{size_badge} {fname}",
                            'title': fname,
                            'id': folder_id,
                            'file_ref': link,
                            'provider': 'alldebrid',
                            'is_folder': False,
                            'size': format_bytes(fsize)
                        })

    except Exception as e:
        control.log(f"Error fetching {provider} cloud items: {str(e)}", "error")

    return items


def resolve_stream_url(provider, item_id, file_ref):
    """Resolve direct unrestrict streaming URL from debrid cloud."""
    try:
        if provider == 'realdebrid':
            from resources.lib.debrid.real_debrid import RealDebrid
            res = RealDebrid().resolve_hoster(file_ref)
            if res and isinstance(res, dict):
                return res.get('download')

        elif provider == 'premiumize':
            if file_ref and file_ref.startswith('http'):
                return file_ref
            from resources.lib.debrid.premiumize import Premiumize
            folder_res = Premiumize().list_folder(item_id)
            content = folder_res.get('content', []) if isinstance(folder_res, dict) else (folder_res if isinstance(folder_res, list) else [])
            for item in content:
                if str(item.get('id')) == str(file_ref):
                    return item.get('link')

        elif provider == 'torbox':
            from resources.lib.debrid.torbox import Torbox
            return Torbox().request_dl_link(item_id, file_ref)

        elif provider == 'alldebrid':
            from resources.lib.debrid.all_debrid import AllDebrid
            res = AllDebrid().resolve_hoster(file_ref)
            if res and isinstance(res, dict):
                return res.get('data', {}).get('link') or res.get('link')

    except Exception as e:
        control.log(f"Error resolving {provider} stream URL: {str(e)}", "error")

    return None


def delete_cloud_item(provider, item_id):
    """Delete item/torrent from user's debrid cloud."""
    try:
        if provider == 'realdebrid':
            from resources.lib.debrid.real_debrid import RealDebrid
            return RealDebrid().deleteTorrent(item_id)
        elif provider == 'premiumize':
            from resources.lib.debrid.premiumize import Premiumize
            return Premiumize().delete_torrent(item_id)
        elif provider == 'torbox':
            from resources.lib.debrid.torbox import Torbox
            return Torbox().delete_torrent(item_id)
        elif provider == 'alldebrid':
            from resources.lib.debrid.all_debrid import AllDebrid
            return AllDebrid().delete_magnet(item_id)
    except Exception as e:
        control.log(f"Error deleting {provider} cloud item {item_id}: {str(e)}", "error")
    return False
