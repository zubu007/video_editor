"""
Feature registry for available video editing features.
"""

# How long a B-roll cutaway may hold the frame before viewer attention drops.
# Standard B-roll pacing keeps cutaways in the 2-6 second range; a still image
# goes stale faster than motion, so it gets a tighter cap than a video clip.
STOCK_MEDIA_MAX_SECONDS = {
    "video": 5.0,
    "image": 3.0,
}
DEFAULT_STOCK_MEDIA_TYPE = "video"


def normalize_stock_media_type(value: object) -> str:
    """Coerce a stock-footage ``media_type`` value to a supported one.

    Args:
        value: The raw media type (typically from LLM output or edit details).

    Returns:
        str: ``"video"`` or ``"image"``; unknown values fall back to the default.
    """
    if isinstance(value, str) and value.strip().lower() in STOCK_MEDIA_MAX_SECONDS:
        return value.strip().lower()
    return DEFAULT_STOCK_MEDIA_TYPE


def clamp_stock_footage_end(start: float, end: float, media_type: str) -> float:
    """Cut a stock-footage span down to its attention-span limit.

    Args:
        start: Span start time in seconds.
        end: Requested span end time in seconds.
        media_type: ``"video"`` or ``"image"``.

    Returns:
        float: ``end``, reduced so the span never exceeds the media type's
        maximum duration (5s for video, 3s for a still image).
    """
    max_seconds = STOCK_MEDIA_MAX_SECONDS[normalize_stock_media_type(media_type)]
    return min(end, start + max_seconds)


AVAILABLE_FEATURES = {
    "zoom": {
        "name": "zoom",
        "description": "Adds a punch-in zoom effect to emphasize important content (zooms toward the speaker's face, or the frame center if no face is found)",
        "use_case": "Use for key points, important statements, or to add visual interest",
        "parameters": [
            {
                "name": "zoom_level",
                "type": "float",
                "description": "Zoom factor (e.g., 1.2 for 20% zoom)",
                "default": 1.2,
            }
        ],
    },
    "insert_stock_footage": {
        "name": "insert_stock_footage",
        "description": (
            "Inserts B-roll to illustrate concepts being discussed — either a short "
            "stock video clip (max 5 seconds) or a still stock photo (max 3 seconds)"
        ),
        "use_case": (
            "Use when speaker describes visual concepts, tells stories, or when visual "
            "variety is needed. Mix both media types: still images for static subjects "
            "(objects, places, portraits), video clips for motion or processes"
        ),
        "parameters": [
            {
                "name": "search_query",
                "type": "string",
                "description": "Keywords to search for relevant stock footage",
                "required": True,
            },
            {
                "name": "media_type",
                "type": "string",
                "description": (
                    '"video" for a short clip or "image" for a still photo'
                ),
                "default": DEFAULT_STOCK_MEDIA_TYPE,
            },
        ],
    },
    "text_overlay": {
        "name": "text_overlay",
        "description": "Adds text overlay to highlight key points or quotes",
        "use_case": "Use for memorable quotes, statistics, key takeaways, or definitions",
        "parameters": [
            {
                "name": "text",
                "type": "string",
                "description": "The text to display",
                "required": True,
            },
        ],
    },
    # "transition": {
    #     "name": "transition",
    #     "description": "Adds a transition effect between segments",
    #     "use_case": "Use between topic changes or to smooth scene transitions",
    #     "parameters": [
    #         {
    #             "name": "type",
    #             "type": "string",
    #             "description": "Transition type (fade, crossfade, slide)",
    #             "default": "crossfade"
    #         }
    #     ]
    # },
}


def get_feature_descriptions_for_llm() -> str:
    """
    Generates a formatted string of all available features for the LLM prompt.

    Returns:
        str: Formatted description of all available features.
    """
    descriptions = []
    for feature_id, feature in AVAILABLE_FEATURES.items():
        desc = f"- {feature['name']}: {feature['description']}\n  Use case: {feature['use_case']}"
        if feature["parameters"]:
            params = []
            for param in feature["parameters"]:
                param_desc = f"{param['name']} ({param['type']})"
                if param.get("required"):
                    param_desc += " [required]"
                params.append(param_desc)
            desc += f"\n  Parameters: {', '.join(params)}"
        descriptions.append(desc)

    return "\n\n".join(descriptions)


def validate_feature_name(feature_name: str) -> bool:
    """
    Validates if a feature name exists in the registry.

    Args:
        feature_name (str): The name of the feature to validate.

    Returns:
        bool: True if the feature exists, False otherwise.
    """
    return feature_name in AVAILABLE_FEATURES
