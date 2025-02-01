import hashlib
import diskcache

cache = diskcache.Cache("cache_data")

def generate_md5(input_string):
    md5_object = hashlib.md5()
    md5_object.update(input_string.encode('utf-8'))
    return md5_object.hexdigest()