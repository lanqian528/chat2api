import tiktoken

model_proxy = {
    "gpt-3.5-turbo": "gpt-3.5-turbo-0125",
    "gpt-3.5-turbo-16k": "gpt-3.5-turbo-16k-0613",
    "gpt-4": "gpt-4-0613",
    "gpt-4-32k": "gpt-4-32k-0613",
    "gpt-4-turbo-preview": "gpt-4-0125-preview",
    "gpt-4-vision-preview": "gpt-4-1106-vision-preview",
    "gpt-4-turbo": "gpt-4-turbo-2024-04-09"
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


def num_tokens_from_messages(messages, model=None):
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
            else:
                num_tokens += len(encoding.encode(value))
    num_tokens += 3
    return num_tokens


def num_tokens_from_content(content, model=None):
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    encoded_content = encoding.encode(content)
    len_encoded_content = len(encoded_content)
    return len_encoded_content


def split_tokens_from_content(content, max_tokens, model=None):
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
