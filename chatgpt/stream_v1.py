import json
import logging
from typing import AsyncGenerator
import jsonpatch


async def transform_delta_stream(input_stream) -> AsyncGenerator[str, None]:
    current_documents = {}
    next_is_delta = False
    current_c = None
    current_o = None
    current_p = None

    try:
        async for line in input_stream:
            line = line.decode("utf-8").strip()
            if not line:
                continue

            if line.startswith("event: "):
                next_is_delta = True
                continue

            if line.startswith("data: ") and next_is_delta:
                data = line[6:]

                if data == "[DONE]":
                    yield line
                    continue

                try:
                    json_data = json.loads(data)

                    if 'c' in json_data:
                        current_c = json_data['c']
                        if 'v' in json_data and isinstance(json_data['v'], dict):
                            current_documents[current_c] = json_data['v']
                            yield f'data: {json.dumps(current_documents[current_c])}'
                        continue

                    if 'v' in json_data:
                        if 'p' in json_data:
                            current_p = json_data['p']
                        if 'o' in json_data:
                            current_o = json_data['o']
                        if current_c is not None and current_c in current_documents:
                            apply_patch(current_documents, current_p, current_o, json_data['v'], current_c)

                    yield f'data: {json.dumps(current_documents[current_c])}'
                except Exception as e:
                    logging.error(f"Error processing JSON data: {e}")
                    yield line
            else:
                yield line
    except GeneratorExit:
        raise
    finally:
        if hasattr(input_stream, 'aclose') and callable(input_stream.aclose):
            try:
                await input_stream.aclose()
            except Exception as e:
                logging.error(f"Error closing input_stream: {e}")


def apply_patch(document, p, o, v, c):
    if o == 'patch':
        for patch in v:
            apply_patch(document, patch['p'], patch['o'], patch['v'], c)

    elif o == 'append':
        current_value = jsonpatch.JsonPointer(p).get(document[c])
        if isinstance(current_value, list):
            new_value = current_value + [v] if not isinstance(v, list) else current_value + v
            patch = jsonpatch.JsonPatch([{
                'op': 'replace',
                'path': p,
                'value': new_value
            }])
        elif isinstance(current_value, str):
            patch = jsonpatch.JsonPatch([{
                'op': 'replace',
                'path': p,
                'value': current_value + str(v)
            }])
        else:
            patch = jsonpatch.JsonPatch([{
                'op': 'replace',
                'path': p,
                'value': v
            }])

        document[c] = patch.apply(document[c])
    else:
        patch = jsonpatch.JsonPatch([{
            'op': o,
            'path': p,
            'value': v
        }])
        document[c] = patch.apply(document[c])
