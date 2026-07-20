model_proxy = {
    "gpt-3.5-turbo": "gpt-3.5-turbo-0125",
    "gpt-3.5-turbo-16k": "gpt-3.5-turbo-16k-0613",
    "gpt-4": "gpt-4-0613",
    "gpt-4-32k": "gpt-4-32k-0613",
    "gpt-4-turbo-preview": "gpt-4-0125-preview",
    "gpt-4-vision-preview": "gpt-4-1106-vision-preview",
    "gpt-4-turbo": "gpt-4-turbo-2024-04-09",
    "gpt-4o": "gpt-4o-2024-08-06",
    "gpt-4o-mini": "gpt-4o-mini-2024-07-18",
    "gpt-5": "gpt-5",
    "gpt-5-mini": "gpt-5-mini",
    "gpt-5-thinking": "gpt-5-thinking",
    "gpt-5-pro": "gpt-5-pro",
    "gpt-5-5": "gpt-5-5",
    "o1-preview": "o1-preview-2024-09-12",
    "o1-mini": "o1-mini-2024-09-12",
    "o1": "o1-2024-12-18",
    "o3-mini": "o3-mini-2025-01-31",
    "o3-mini-high": "o3-mini-high-2025-01-31",
    "o3-deep-research": "o3-deep-research-2025-06-26",
    "o4-mini-deep-research": "o4-mini-deep-research-2025-06-26",
    "gpt-4o-deep-research": "gpt-4o-deep-research",
    "deep-research": "deep-research",
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
    "gpt-4-turbo-2024-04-09": ["fp_d1bac968b4"],
    "gpt-4o-2024-05-13": ["fp_3aa7262c27"],
    "gpt-4o-mini-2024-07-18": ["fp_c9aa9c0491"]
}

MODEL_REQUEST_RULES = (
    ("o3-deep-research", "o3-deep-research"),
    ("o4-mini-deep-research", "o4-mini-deep-research"),
    ("gpt-4o-deep-research", "gpt-4o-deep-research"),
    ("deep-research", "deep-research"),
    ("o3-mini-high", "o3-mini-high"),
    ("o3-mini-medium", "o3-mini-medium"),
    ("o3-mini-low", "o3-mini-low"),
    ("o3-mini", "o3-mini"),
    ("o3", "o3"),
    ("o1-preview", "o1-preview"),
    ("o1-pro", "o1-pro"),
    ("o1-mini", "o1-mini"),
    ("o1", "o1"),
    ("gpt-5-5", "gpt-5-5"),
    ("gpt-5-pro", "gpt-5-pro"),
    ("gpt-5-thinking", "gpt-5-thinking"),
    ("gpt-5-mini", "gpt-5-mini"),
    ("gpt-5", "gpt-5"),
    ("gpt-4.5o", "gpt-4.5o"),
    ("gpt-4o-canmore", "gpt-4o-canmore"),
    ("gpt-4o-mini", "gpt-4o-mini"),
    ("gpt-4o", "gpt-4o"),
    ("gpt-4-mobile", "gpt-4-mobile"),
    ("gpt-4", "gpt-4"),
    ("gpt-3.5", "text-davinci-002-render-sha"),
    ("auto", "auto"),
)

DEEP_RESEARCH_MODEL_ALIASES = (
    "o3-deep-research",
    "o4-mini-deep-research",
    "gpt-4o-deep-research",
    "deep-research",
)


def should_expose_deep_research_aliases(model_slugs):
    paid_markers = (
        "gpt-4",
        "gpt-4o",
        "gpt-5",
        "o1",
        "o3",
        "o4",
    )
    return any(
        isinstance(slug, str) and slug.startswith(paid_markers)
        for slug in (model_slugs or [])
    )


def augment_model_slugs(model_slugs):
    slugs = set(model_slugs or [])
    if should_expose_deep_research_aliases(slugs):
        slugs.update(DEEP_RESEARCH_MODEL_ALIASES)
    return slugs


def get_response_model(origin_model):
    return model_proxy.get(origin_model, origin_model)


def match_model_family(origin_model, alias):
    return origin_model == alias or origin_model.startswith(f"{alias}-")


def resolve_request_model(origin_model):
    origin_model = (origin_model or "gpt-5-5").strip()
    base_model = origin_model
    gizmo_id = None

    if "-gizmo-g-" in origin_model:
        base_model, _, gizmo_suffix = origin_model.partition("-gizmo-")
        gizmo_id = gizmo_suffix
    elif origin_model.startswith("g-"):
        gizmo_id = origin_model
        base_model = "gpt-5-5"

    for alias, target in MODEL_REQUEST_RULES:
        if match_model_family(base_model, alias):
            return target, gizmo_id, False

    return base_model, gizmo_id, True


def extract_model_slugs(models_payload):
    slugs = set()
    model_items = models_payload.get("models", [])
    if isinstance(model_items, dict):
        model_items = model_items.values()

    for model in model_items:
        if not isinstance(model, dict):
            continue

        for key in ("slug", "id", "model_slug"):
            value = model.get(key)
            if isinstance(value, str) and value:
                slugs.add(value)

        nested_model = model.get("model")
        if isinstance(nested_model, dict):
            for key in ("slug", "id", "model_slug"):
                value = nested_model.get(key)
                if isinstance(value, str) and value:
                    slugs.add(value)

    return slugs
