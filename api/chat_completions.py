import base64
import io
import math

import tiktoken
from PIL import Image

from utils.Client import Client

model_proxy = {
    "gpt-3.5-turbo": "gpt-3.5-turbo-0125",
    "gpt-3.5-turbo-16k": "gpt-3.5-turbo-16k-0613",
    "gpt-4": "gpt-4-0613",
    "gpt-4-32k": "gpt-4-32k-0613",
    "gpt-4-turbo-preview": "gpt-4-0125-preview",
    "gpt-4-vision-preview": "gpt-4-1106-vision-preview",
    "gpt-4-turbo": "gpt-4-turbo-2024-04-09",
    "claude-3-opus": "claude-3-opus-20240229",
    "claude-3-sonnet": "claude-3-sonnet-20240229",
    "claude-3-haiku": "claude-3-haiku-20240307",
}

model_system_fingerprint = {
    "gpt-3.5-turbo-0125": ["fp_b28b39ffa8"],
    "gpt-3.5-turbo-1106": ["fp_592ef5907d"],
    "gpt-4-0125-preview": ["fp_f38f4d6482", "fp_2f57f81c11", "fp_a7daf7c51e", "fp_a865e8ede4", "fp_13c70b9f70",
                           "fp_b77cb481ed"],
    "gpt-4-1106-preview": ["fp_e467c31c3d", "fp_d986a8d1ba", "fp_99a5a401bb", "fp_123d5a9f90", "fp_0d1affc7a6",
                           "fp_5c95a4634e"],
    "gpt-4-turbo-2024-04-09": ["fp_d1bac968b4"]
}


async def decode_base64_image(base64_string):
    if "base64," in base64_string:
        base64_str = base64_string.split("base64,")[1]
    image_data = base64.b64decode(base64_str)
    image_file = io.BytesIO(image_data)
    with Image.open(image_file) as img:
        img.load()
        return img


async def fetch_and_open_image(url):
    client = Client()
    r = await client.get(url)
    r.raise_for_status()
    partial_image_data = io.BytesIO(r.content)
    with Image.open(partial_image_data) as img:
        img.load()
        return img


async def get_img(url):
    if url.startswith("data:image"):
        img = await decode_base64_image(url)
    else:
        img = await fetch_and_open_image(url)
    return img


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
    if model in {
        "gpt-3.5-turbo-0613",
        "gpt-3.5-turbo-16k-0613",
        "gpt-4-0314",
        "gpt-4-32k-0314",
        "gpt-4-0613",
        "gpt-4-32k-0613",
    }:
        tokens_per_message = 3
    elif model == "gpt-3.5-turbo-0301":
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
