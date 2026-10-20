from resources.lib.ui import client, control, database


def _fetch_skip_times(mal_id, episodenum, skip_type):
    # skip_types = op, recap, mixed-ed, mixed-op, ed
    url = 'https://api.aniskip.com/v2/skip-times/%s/%d' % (mal_id, episodenum)
    params = {
        'types': skip_type,
        'episodeLength': 0
    }
    response = client.get(url, params=params)
    if response and response.ok:
        return control.safe_call(response.json, log_msg='AniSkip API error')
    return None


def get_skip_times(mal_id, episodenum, skip_type):
    return database.get(
        _fetch_skip_times,
        168,
        mal_id,
        episodenum,
        skip_type,
        key='aniskip'
    )
