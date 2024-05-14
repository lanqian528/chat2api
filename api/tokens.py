import math

import tiktoken


async def calculate_image_tokens(width, height, detail):
    if detail == "low":
        return 85
    else:
        max_dimension = max(width, height)
        if max_dimension > 2048:
            scale_factor = 2048 / max_dimension
            new_width = int(width * scale_factor)
            new_height = int(height * scale_factor)
        else:
            new_width = width
            new_height = height

        width, height = new_width, new_height
        min_dimension = min(width, height)
        if min_dimension > 768:
            scale_factor = 768 / min_dimension
            new_width = int(width * scale_factor)
            new_height = int(height * scale_factor)
        else:
            new_width = width
            new_height = height

        width, height = new_width, new_height
        num_masks_w = math.ceil(width / 512)
        num_masks_h = math.ceil(height / 512)
        total_masks = num_masks_w * num_masks_h

        tokens_per_mask = 170
        total_tokens = total_masks * tokens_per_mask + 85

        return total_tokens


async def num_tokens_from_messages(messages, model=''):
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    if model == "gpt-3.5-turbo-0301":
        tokens_per_message = 4
    else:
        tokens_per_message = 3
    num_tokens = 0
    for message in messages:
        num_tokens += tokens_per_message
        for key, value in message.items():
            if isinstance(value, list):
                for item in value:
                    if item.get("type") == "text":
                        num_tokens += len(encoding.encode(item.get("text")))
                    if item.get("type") == "image_url":
                        pass
            else:
                num_tokens += len(encoding.encode(value))
    num_tokens += 3
    return num_tokens


async def num_tokens_from_content(content, model=None):
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    encoded_content = encoding.encode(content)
    len_encoded_content = len(encoded_content)
    return len_encoded_content


async def split_tokens_from_content(content, max_tokens, model=None):
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    encoded_content = encoding.encode(content)
    len_encoded_content = len(encoded_content)
    if len_encoded_content >= max_tokens:
        content = encoding.decode(encoded_content[:max_tokens])
        return content, max_tokens, "length"
    else:
        return content, len_encoded_content, "stop"
