"""Explicit UI preferences only; no identity, token or captured data."""
import json
import os
from pathlib import Path
import tempfile

DEFAULTS={'live_identity':True,'minimize_on_start':False,
          'auto_item_sets':False,'item_set_dir':''}
MAX_PATH=500


def load_preferences(directory):
    result=dict(DEFAULTS)
    try:
        path=Path(directory)/'monitor-preferences.json'
        if path.stat().st_size>8192:return result
        value=json.loads(path.read_text(encoding='utf8'))
        if not isinstance(value,dict) or value.get('schema_version')!=1:return result
        for key,default in DEFAULTS.items():
            if key=='item_set_dir':
                item_dir=value.get(key)
                if isinstance(item_dir,str) and len(item_dir)<=MAX_PATH and '\x00' not in item_dir:
                    result[key]=item_dir
            elif type(value.get(key)) is bool:
                result[key]=value[key]
    except (OSError,ValueError,TypeError):pass
    return result


def save_preferences(directory,values):
    if set(values)!=set(DEFAULTS):raise ValueError('Invalid UI preferences')
    for key,value in values.items():
        if key=='item_set_dir':
            if not isinstance(value,str) or len(value)>MAX_PATH or '\x00' in value:
                raise ValueError('Invalid item set directory')
        elif type(value) is not bool:
            raise ValueError('Invalid UI preferences')
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.monitor-preferences-',suffix='.tmp',dir=directory)
    try:
        with os.fdopen(fd,'w',encoding='utf8') as stream:json.dump({'schema_version':1,**values},stream)
        os.replace(name,directory/'monitor-preferences.json')
    finally:
        try:os.unlink(name)
        except FileNotFoundError:pass
