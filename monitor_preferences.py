"""Only two explicit UI preferences; no identity, token or captured data."""
import json
import os
from pathlib import Path
import tempfile

DEFAULTS={'live_identity':True,'minimize_on_start':False}


def load_preferences(directory):
    result=dict(DEFAULTS)
    try:
        path=Path(directory)/'monitor-preferences.json'
        if path.stat().st_size>4096:return result
        value=json.loads(path.read_text(encoding='utf8'))
        if not isinstance(value,dict) or value.get('schema_version')!=1:return result
        for key in DEFAULTS:
            if type(value.get(key)) is bool:result[key]=value[key]
    except (OSError,ValueError,TypeError):pass
    return result


def save_preferences(directory,values):
    if set(values)!=set(DEFAULTS) or any(type(v) is not bool for v in values.values()):raise ValueError('Invalid UI preferences')
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.monitor-preferences-',suffix='.tmp',dir=directory)
    try:
        with os.fdopen(fd,'w',encoding='utf8') as stream:json.dump({'schema_version':1,**values},stream)
        os.replace(name,directory/'monitor-preferences.json')
    finally:
        try:os.unlink(name)
        except FileNotFoundError:pass
